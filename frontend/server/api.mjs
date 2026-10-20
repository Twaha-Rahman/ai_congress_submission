import { fileURLToPath } from "node:url";
import { Readable } from "node:stream";

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
      });
    }
    const match =
      /^\/api\/(dhaka|frankfurt)\/(findings(?:\/[\w:.-]+(?:\/reviews)?)?|sources(?:\/[\w:.-]+(?:\/content)?)?|claims)$/.exec(
        url.pathname,
      );
    const path = match?.[2];
    const isReview = path && /^findings\/[\w:.-]+\/reviews$/.test(path);
    if (
      !match ||
      !(
        (req.method === "GET" && !isReview) ||
        (req.method === "POST" && isReview)
      )
    ) {
      return json(res, 404, {
        error: {
          code: "not_found",
          message: "This route is not available in the findings workspace.",
        },
      });
    }
    if (req.method === "POST") {
      // Forms and cross-origin scripts cannot submit review decisions through this bridge.
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
            message: "Review requests must come from this workspace.",
          },
        });
      }
      if (role !== "reviewer")
        return json(res, 403, {
          error: {
            code: "forbidden",
            message: "This workspace is configured for read-only access.",
          },
        });
    }
    const office = match[1].toUpperCase();
    const token = env[`DEMO_TOKEN_${office}_${role.toUpperCase()}`];
    if (!token)
      return json(res, 503, {
        error: {
          code: "missing_credentials",
          message: `The ${match[1]} ${role} connection is not configured. Run make setup, then restart the frontend.`,
        },
      });
    const base =
      env[`${office}_BASE_URL`] ||
      `http://127.0.0.1:${office === "DHAKA" ? 8081 : 8082}`;
    try {
      let body;
      if (req.method === "POST") {
        const chunks = [];
        let size = 0;
        for await (const chunk of req) {
          size += chunk.length;
          if (size > 65536)
            return json(res, 413, {
              error: {
                code: "invalid_input",
                message: "The review reason is too long.",
              },
            });
          chunks.push(chunk);
        }
        body = Buffer.concat(chunks);
      }
      const upstream = await fetchImpl(
        `${base.replace(/\/$/, "")}/v1/${path}${url.search}`,
        {
          method: req.method,
          headers: {
            Authorization: `Bearer ${token}`,
            ...(body ? { "Content-Type": "application/json" } : {}),
          },
          body,
          redirect: "error",
          signal: AbortSignal.timeout(15000),
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
