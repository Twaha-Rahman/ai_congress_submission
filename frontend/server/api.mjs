import { fileURLToPath } from "node:url";
import { Readable } from "node:stream";
import { createAuthStore, AuthError, capabilities, sessionCookie, sameOriginWrite } from "./auth.mjs";
import { parseSavedSlack, buildSavedSlackManifest, maxSlackBytes } from "../shared/slackImport.mjs";

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

function sessionData(user,env,legacy=false) {
  const access=capabilities(user);
  const available=(office,role)=>!legacy||!!env[`DEMO_TOKEN_${office.toUpperCase()}_${role.toUpperCase()}`];
  return {user,role:user.role,canManageUsers:access.manage,canReview:access.review,demo:true,
    offices:user.offices,activity:access.audit,
    comparisons:{rules:access.review&&user.offices.length===2&&user.readRestricted&&(!legacy||!!env.DEMO_TOKEN_GATEWAY_SERVICE)},
    queries:Object.fromEntries(["dhaka","frankfurt"].map(office=>[office,user.offices.includes(office)&&available(office,user.role)])),
    uploads:Object.fromEntries(["dhaka","frankfurt"].map(office=>[office,{enabled:access.upload&&user.offices.includes(office)&&available(office,"uploader"),processing:usesApprovedLocalModel(env,office.toUpperCase())?"local":"hosted",maxBytes:MAX_PDF_BYTES}]))};
}
async function accountBody(req,keys) {
  const chunks=[];let size=0;
  for await(const chunk of req){size+=chunk.length;if(size>16384)throw new AuthError(413,"invalid_input","The account request is too large.");chunks.push(chunk);}
  let data;try{data=JSON.parse(Buffer.concat(chunks).toString("utf8"));}catch{throw new AuthError(422,"invalid_input","Supply valid account details.");}
  if(!data||typeof data!=="object"||Array.isArray(data)||Object.keys(data).some(key=>!keys.includes(key)))throw new AuthError(422,"invalid_input","Unsupported account details.");
  return data;
}

/** Session-authenticated local bridge. Bearer credentials never enter the browser. */
export function createApiHandler({env=process.env,fetchImpl=fetch,authStore,resolveSession}={}) {
  // Dependency injection is used by transport tests; there is no environment login bypass.
  const auth=authStore||(resolveSession?null:createAuthStore(env));
  return async function handle(req,res) {
    try {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "same-origin");
    // Bind browser access to loopback names as well as a loopback listener.
    // This blocks DNS rebinding to a local account session.
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
    if(url.pathname.startsWith("/api/auth/")&&auth){
      if(req.method!=="GET"&&!sameOriginWrite(req))return json(res,403,{error:{code:"forbidden",message:"Account changes must come from this workspace."}});
      const secure=!!req.socket.encrypted;
      if(url.pathname==="/api/auth/login"&&req.method==="POST"){
        const body=await accountBody(req,["username","password"]);
        const login=await auth.login(body.username,body.password,req.socket.remoteAddress||"local");
        res.setHeader("Set-Cookie",sessionCookie(login.token,secure));return json(res,200,sessionData(login.user,env));
      }
      const session=auth.authenticate(req);
      if(url.pathname==="/api/auth/logout"&&req.method==="POST"){auth.logout(session);res.setHeader("Set-Cookie",sessionCookie("",secure));return json(res,200,{loggedOut:true});}
      if(!session)throw new AuthError(401,"unauthenticated","Sign in to continue.");
      if(url.pathname==="/api/auth/password"&&req.method==="POST"){
        const body=await accountBody(req,["currentPassword","newPassword"]);
        const changed=await auth.changePassword(session,body.currentPassword,body.newPassword);
        res.setHeader("Set-Cookie",sessionCookie(changed.token,secure));return json(res,200,sessionData(changed.user,env));
      }
      if(url.pathname==="/api/auth/users"&&req.method==="GET")return json(res,200,{users:auth.listUsers(session.user)});
      if(url.pathname==="/api/auth/users"&&req.method==="POST")return json(res,201,{user:await auth.createUser(session.user,await accountBody(req,["username","password","role","offices","readRestricted","active"]))});
      const userPath=/^\/api\/auth\/users\/([a-f0-9-]{36})(\/password)?$/.exec(url.pathname);
      if(userPath&&req.method==="PATCH"&&!userPath[2])return json(res,200,{user:auth.updateUser(session.user,userPath[1],await accountBody(req,["role","offices","readRestricted","active"]))});
      if(userPath&&req.method==="POST"&&userPath[2]){const body=await accountBody(req,["password"]);return json(res,200,{user:await auth.resetPassword(session.user,userPath[1],body.password)});}
      return json(res,404,{error:{code:"not_found",message:"Account action not found."}});
    }
    const context=resolveSession?await resolveSession(req):auth.authenticate(req);
    if(!context){res.setHeader("Set-Cookie",sessionCookie("",!!req.socket.encrypted));throw new AuthError(401,"unauthenticated","Sign in to continue.");}
    const user=context.user,role=user.role,access=capabilities(user);
    if(req.method==="GET"&&url.pathname==="/api/session")return json(res,200,sessionData(user,env,!!resolveSession));
    const match =
      /^\/api\/(dhaka|frankfurt|gateway)\/(findings(?:\/[\w:.-]+(?:\/(?:reviews|lineage))?)?|sources(?:\/[\w:.-]+(?:\/(?:content|comparisons|lineage|versions|diff|withdrawal))?)?|answers(?:\/[\w:.-]+(?:\/(?:lineage|bundle))?)?|queries(?:\/gw_\d{8}T\d{12})?|verifications\/(?:source|bundle)|claims(?:\/reviews)?|jobs(?:\/[\w.-]+)?|ingestions\/(?:pdf|slack)|integrations\/slack|activity(?:\/[\w:.-]+)?)$/.exec(
        url.pathname.replace(/%3a/gi, ":"),
      );
    const path = match?.[2];
    const isGateway = match?.[1] === "gateway";
    const isActivity = path === "activity" || path?.startsWith("activity/");
    const isReview = path && /^findings\/[\w:.-]+\/reviews$/.test(path);
    const isUpload = path === "ingestions/pdf";
    const isSavedSlack = path === "ingestions/slack";
    const isSlack = path === "integrations/slack";
    const isQuery = path === "queries";
    const isComparison = path && /^sources\/[\w:.-]+\/comparisons$/.test(path);
    const isWithdrawal = path && /^sources\/[\w:.-]+\/withdrawal$/.test(path);
    const isVerification = path?.startsWith("verifications/");
    const isSourceVerification = path === "verifications/source";
    if (
      !match || (!isGateway && path?.startsWith("queries/")) || (isGateway && path !== "queries" && !/^queries\/gw_\d{8}T\d{12}$/.test(path)) ||
      !(
        (req.method === "GET" && !isReview && !isUpload && !isSavedSlack && !isComparison && !isVerification && !isQuery) ||
        (req.method === "POST" && (isReview || isUpload || isComparison || isVerification || isQuery || isSlack || isSavedSlack || isWithdrawal))
      )
    ) {
      return json(res, 404, {
        error: {
          code: "not_found",
          message: "This route is not available in this workspace.",
        },
      });
    }
    // Federation can import signed claims at another office. Require a reviewer
    // account with access to both offices before accepting that operation.
    if (isWithdrawal && !access.manage)
      return json(res,403,{error:{code:"forbidden",message:"Only an administrator can withdraw sources."}});
    if (isActivity && !access.audit)
      return json(res, 403, { error: { code: "forbidden", message: "Activity requires audit access." } });
    if (isSlack && !access.upload)
      return json(res, 403, { error: { code: "forbidden", message: "Slack connection settings require an authorized workspace." } });
    if (isGateway && (!access.review || user.offices.length!==2 || !user.readRestricted))
      return json(res, 403, { error: { code: "forbidden", message: "Signed-rule comparisons require reviewer access to both offices and restricted sources." } });
    if (req.method === "POST") {
      // Browser writes require this same-origin workspace, regardless of action.
      if (!sameOriginWrite(req)) {
        return json(res, 403, {
          error: {
            code: "forbidden",
            message: "Write requests must come from this workspace.",
          },
        });
      }
      if ((isReview&&!access.review)||((isUpload||isSavedSlack||isComparison||isSlack)&&!access.upload))
        return json(res, 403, {
          error: {
            code: "forbidden",
            message: "This workspace is configured for read-only access.",
          },
        });
    }
    if(!isGateway&&!user.offices.includes(match[1]))return json(res,403,{error:{code:"forbidden",message:"Your account does not have access to this office."}});
    const office = match[1].toUpperCase();
    const connectionRole = isUpload || isComparison || isSlack || isSavedSlack ? "uploader" : role;
    const token = resolveSession ? env[`DEMO_TOKEN_${office}_${isGateway ? "SERVICE" : connectionRole.toUpperCase()}`] : auth.delegationToken(user,office,env.TENANT_ID||"meridian_demo");
    if (!token)
      return json(res, 503, {
        error: {
          code: "missing_credentials",
          message: `The ${match[1]} ${connectionRole} connection is not configured. Run make setup, then restart the frontend.`,
        },
      });
    const base =
      env[`${office}_BASE_URL`] ||
      `http://127.0.0.1:${isGateway ? 8080 : office === "DHAKA" ? 8081 : 8082}`;
    try {
      let body;
      let contentType;
      if (req.method === "POST") {
        const chunks = [];
        let size = 0;
        for await (const chunk of req) {
          size += chunk.length;
          if (size > (isUpload || isSourceVerification ? MAX_PDF_BYTES + 65536 : isVerification ? MAX_PDF_BYTES : isSavedSlack ? maxSlackBytes + 65536 : 65536))
            return json(res, 413, {
              error: {
                code: "invalid_input",
                message: isSavedSlack ? "Choose a saved Slack file smaller than 5 MB." : isUpload ? "Choose a PDF smaller than 20 MB." : isVerification ? "Choose evidence smaller than 20 MB." : "The request is too large.",
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
        } else if (isSavedSlack) {
          try {
            const submission = JSON.parse(body.toString("utf8"));
            if (!submission || typeof submission !== "object" || Array.isArray(submission) ||
                Object.keys(submission).some(key => !["manifest", "payload"].includes(key))) throw new Error("Use the saved Slack import form.");
            const saved = parseSavedSlack(JSON.stringify(submission.payload));
            const metadata = buildSavedSlackManifest(submission.manifest, saved.newest);
            if (usesApprovedLocalModel(env, office) === false && !metadata.permissions.hosted_model)
              throw new Error("Allow hosted-model processing to import these messages with the configured model.");
            body = JSON.stringify({ ...saved.payload, manifest: { ...metadata, tenant_id: env.TENANT_ID || "meridian_demo", region: office }, mode: "live" });
          } catch (error) {
            return json(res, 422, { error: { code: "invalid_input", message: error instanceof SyntaxError ? "The saved Slack import is not valid JSON." : error.message || "The saved Slack import is invalid." } });
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
            if (isGateway && (!query.target || !["loan_approval", "record_retention"].includes(query.target.subject) ||
                "source_ids" in query || Object.keys(query.target).some(key => !["subject", "amount_minor", "currency", "loan_type", "origin_office", "processing_office", "record_class", "starting_event", "product"].includes(key)))) throw new Error();
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
          signal: AbortSignal.timeout(isQuery ? isGateway ? 100000 : 610000 : isUpload || isSavedSlack || isVerification ? 60000 : 15000),
        },
      );
      if(!resolveSession&&upstream.status===401)return json(res,503,{error:{code:"office_authentication_failed",message:"The office cannot verify account access. Restart the backend services and check the shared UI authentication key."}});
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
    } catch(error) {
      if(!res.headersSent&&error instanceof AuthError&&error.code==="unauthenticated")res.setHeader("Set-Cookie",sessionCookie("",!!req.socket.encrypted));
      if(!res.headersSent)json(res,error instanceof AuthError?error.status:500,{error:{code:error instanceof AuthError?error.code:"account_error",message:error instanceof AuthError?error.message:"The account service could not complete this request."}});
      else res.destroy();
    }
  };
}
