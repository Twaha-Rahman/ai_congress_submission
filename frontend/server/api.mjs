import { fileURLToPath } from "node:url";
import { Readable } from "node:stream";

const MAX_PDF_BYTES = 20 * 1024 * 1024;

function usesApprovedLocalModel(env, office) {
  const approved = env[`${office}_LLM_LOCAL_ENDPOINT_APPROVED`] || env.LLM_LOCAL_ENDPOINT_APPROVED || "";
  if (!["1", "true", "yes", "on"].includes(approved.toLowerCase())) return false;
  try {
    const url = new URL(env[`${office}_LLM_BASE_URL`] || env.LLM_BASE_URL || "https://openrouter.ai/api/v1");
    if (!["http:", "https:"].includes(url.protocol)) return false;
    const host = url.hostname.replace(/^\[|\]$/g, "");
    return ["localhost", "localhost.localdomain", "::1"].includes(host) ||
      /^(127|10)\./.test(host) || /^192\.168\./.test(host) ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(host) || /^(fc|fd)[0-9a-f]{2}:/i.test(host);
  } catch { return false; }
}

export function loadEnvironment() {
  for (const path of ["../../.env", "../.env.local"]) {
    try {
      process.loadEnvFile(fileURLToPath(new URL(path, import.meta.url)));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
}

function json(res, status, data) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(data));
}

/** Local demo bridge. The configured principal is fixed on the server, never by a browser header. */
export function createApiHandler({
  env = process.env,
  fetchImpl = fetch,
} = {}) {
  const role = env.UI_ROLE || "reviewer";
  if (!["reviewer", "reader"].includes(role))
    throw new Error("UI_ROLE must be reviewer or reader");
  return async function handle(req, res) {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "same-origin");
    // Bind browser access to loopback names as well as a loopback listener.
    // This blocks DNS rebinding to a local demo principal.
    let host;
    try {
      host = new URL(`http://${req.headers.host}`).hostname;
    } catch {
      host = "";
    }
    if (!["localhost", "127.0.0.1", "[::1]"].includes(host)) {
      return json(res, 403, {
        error: {
          code: "forbidden",
          message: "Open this workspace through its localhost address.",
        },
      });
    }
    const url = new URL(req.url, "http://localhost");
    if (req.method === "GET" && url.pathname === "/api/session") {
      return json(res, 200, {
        role,
        canReview: role === "reviewer",
        demo: true,
        queries: Object.fromEntries(["dhaka", "frankfurt"].map(office => [office,
          !!env[`DEMO_TOKEN_${office.toUpperCase()}_${role.toUpperCase()}`],
        ])),
        uploads: Object.fromEntries(["dhaka", "frankfurt"].map((office) => [office, {
          enabled: role === "reviewer" && !!env[`DEMO_TOKEN_${office.toUpperCase()}_UPLOADER`],
          processing: usesApprovedLocalModel(env, office.toUpperCase()) ? "local" : "hosted",
          maxBytes: MAX_PDF_BYTES,
        }])),
      });
    }
    const match =
      /^\/api\/(dhaka|frankfurt)\/(findings(?:\/[\w:.-]+(?:\/(?:reviews|lineage))?)?|sources(?:\/[\w:.-]+(?:\/(?:content|comparisons|lineage))?)?|answers(?:\/[\w:.-]+(?:\/(?:lineage|bundle))?)?|queries|verifications\/(?:source|bundle)|claims(?:\/reviews)?|jobs(?:\/[\w.-]+)?|ingestions\/pdf)$/.exec(
        url.pathname,
      );
    const path = match?.[2];
    const isReview = path && /^findings\/[\w:.-]+\/reviews$/.test(path);
    const isUpload = path === "ingestions/pdf";
    const isQuery = path === "queries";
    const isComparison = path && /^sources\/[\w:.-]+\/comparisons$/.test(path);
    const isVerification = path?.startsWith("verifications/");
    const isSourceVerification = path === "verifications/source";
    if (
      !match ||
      !(
        (req.method === "GET" && !isReview && !isUpload && !isComparison && !isVerification && !isQuery) ||
        (req.method === "POST" && (isReview || isUpload || isComparison || isVerification || isQuery))
      )
    ) {
      return json(res, 404, {
        error: {
          code: "not_found",
          message: "This route is not available in this workspace.",
        },
      });
    }
    if (req.method === "POST") {
      // Browser writes require this same-origin workspace, regardless of action.
      const origin = req.headers.origin;
      let sameOrigin = !origin;
      try {
        if (origin) sameOrigin = new URL(origin).host === req.headers.host;
      } catch {
        sameOrigin = false;
      }
      if (req.headers["x-meridian-ui"] !== "1" || !sameOrigin) {
        return json(res, 403, {
          error: {
            code: "forbidden",
            message: "Write requests must come from this workspace.",
          },
        });
      }
      if (role !== "reviewer" && !isVerification && !isQuery)
        return json(res, 403, {
          error: {
            code: "forbidden",
            message: "This workspace is configured for read-only access.",
          },
        });
    }
    const office = match[1].toUpperCase();
    const connectionRole = isUpload || isComparison ? "uploader" : role;
    const token = env[`DEMO_TOKEN_${office}_${connectionRole.toUpperCase()}`];
    if (!token)
      return json(res, 503, {
        error: {
          code: "missing_credentials",
          message: `The ${match[1]} ${connectionRole} connection is not configured. Run make setup, then restart the frontend.`,
        },
      });
    const base =
      env[`${office}_BASE_URL`] ||
      `http://127.0.0.1:${office === "DHAKA" ? 8081 : 8082}`;
    try {
      let body;
      let contentType;
      if (req.method === "POST") {
        const chunks = [];
        let size = 0;
        for await (const chunk of req) {
          size += chunk.length;
          if (size > (isUpload || isSourceVerification ? MAX_PDF_BYTES + 65536 : isVerification ? MAX_PDF_BYTES : 65536))
            return json(res, 413, {
              error: {
                code: "invalid_input",
                message: isUpload ? "Choose a PDF smaller than 20 MB." : isVerification ? "Choose evidence smaller than 20 MB." : "The request is too large.",
              },
            });
          chunks.push(chunk);
        }
        body = Buffer.concat(chunks);
        contentType = "application/json";
        if (isUpload) {
          const header = req.headers["content-type"] || "";
          if (!header.toLowerCase().startsWith("multipart/form-data;"))
            return json(res, 422, { error: { code: "invalid_input", message: "Upload a PDF using the upload form." } });
          try {
            const form = await new Request("http://localhost/upload", {
              method: "POST", headers: { "Content-Type": header }, body,
            }).formData();
            const file = form.get("file");
            const metadata = JSON.parse(form.get("manifest"));
            if (!(file instanceof Blob) || !file.size || file.size > MAX_PDF_BYTES)
              throw new Error("Choose a nonempty PDF smaller than 20 MB.");
            const start = Buffer.from(await file.slice(0, 1024).arrayBuffer());
            if (!start.includes(Buffer.from("%PDF-"))) throw new Error("The selected file is not a PDF.");
            if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) throw new Error();
            // Office/tenant/source kind are fixed by this server. Browser headers
            // and fields cannot select another principal or tenant.
            metadata.tenant_id = env.TENANT_ID || "meridian_demo";
            metadata.region = office;
            metadata.source_type = "pdf";
            metadata.subject = "general_policy";
            const forwarded = new FormData();
            forwarded.set("file", file, file.name || "policy.pdf");
            forwarded.set("manifest", JSON.stringify(metadata));
            forwarded.set("mode", "live");
            body = forwarded;
            contentType = undefined; // fetch generates the new multipart boundary.
          } catch (error) {
            return json(res, 422, { error: { code: "invalid_input", message:
              error instanceof SyntaxError ? "The upload metadata is invalid." :
              error.message && !error.message.includes("formData") ? error.message : "The upload form is invalid.",
            } });
          }
        } else if (isSourceVerification) {
          try {
            const header = req.headers["content-type"] || "";
            if (!header.toLowerCase().startsWith("multipart/form-data;")) throw new Error();
            const form = await new Request("http://localhost/verification", {
              method: "POST", headers: { "Content-Type": header }, body,
            }).formData();
            const file = form.get("file");
            const sourceId = form.get("source_id");
            if (!(file instanceof Blob) || !file.size || file.size > MAX_PDF_BYTES ||
                typeof sourceId !== "string" || !/^[\w:.-]+$/.test(sourceId)) throw new Error();
            const forwarded = new FormData();
            forwarded.set("source_id", sourceId);
            forwarded.set("file", file, file.name || "source-copy");
            body = forwarded;
            contentType = undefined;
          } catch {
            return json(res, 422, { error: { code: "invalid_input", message: "Choose a source and a nonempty copy up to 20 MB." } });
          }
        } else if (isQuery) {
          try {
            const query = JSON.parse(body.toString("utf8"));
            // Local questions cannot supply gateway snapshot controls or select
            // another tenant, principal, execution mode, or office connection.
            if (!query || typeof query !== "object" || Array.isArray(query) ||
                Object.keys(query).some(key => !["question", "target", "valid_at", "known_at", "source_ids"].includes(key)) ||
                (query.target && !["general_policy", "loan_approval", "record_retention"].includes(query.target.subject))) throw new Error();
          } catch {
            return json(res, 422, { error: { code: "invalid_input", message: "Supply a local question with optional source and date filters." } });
          }
        } else if (isVerification) {
          try {
            const evidence = JSON.parse(body.toString("utf8"));
            if (!evidence || typeof evidence !== "object" || Array.isArray(evidence)) throw new Error();
          } catch {
            return json(res, 422, { error: { code: "invalid_input", message: "Choose a JSON evidence bundle." } });
          }
        }
      }
      const upstream = await fetchImpl(
        `${base.replace(/\/$/, "")}/v1/${path}${url.search}`,
        {
          method: req.method,
          headers: {
            Authorization: `Bearer ${token}`,
            ...(body && contentType ? { "Content-Type": contentType } : {}),
          },
          body,
          redirect: "error",
          signal: AbortSignal.timeout(isQuery ? 610000 : isUpload || isVerification ? 60000 : 15000),
        },
      );
      const headers = {
        "Content-Type":
          upstream.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
      };
      // Open original evidence in a separate tab without exposing a bearer token.
      if (upstream.headers.has("content-disposition"))
        headers["Content-Disposition"] = upstream.headers.get(
          "content-disposition",
        );
      res.writeHead(upstream.status, headers);
      if (upstream.body)
        Readable.fromWeb(upstream.body)
          .on("error", () => res.destroy())
          .pipe(res);
      else res.end();
    } catch {
      if (!res.headersSent)
        json(res, 503, {
          error: {
            code: "office_unavailable",
            message: `The ${match[1]} office could not be reached. Check that its backend is running, then retry.`,
          },
        });
      else res.destroy();
    }
  };
}
