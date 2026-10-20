import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, extname, sep } from "node:path";
import { createApiHandler, loadEnvironment } from "./api.mjs";

loadEnvironment();
const api = createApiHandler();
const root = fileURLToPath(new URL("../dist", import.meta.url));
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".wasm": "application/wasm",
};
const server = createServer(async (req, res) => {
  if (req.url?.startsWith("/api/")) return api(req, res);
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405);
    return res.end();
  }
  try {
    const path = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    let file = resolve(root, `.${path}`);
    if (!file.startsWith(root + sep) && file !== root) {
      res.writeHead(404);
      return res.end();
    }
    try {
      if (!(await stat(file)).isFile()) file = resolve(root, "index.html");
    } catch {
      if (extname(path)) {
        res.writeHead(404);
        return res.end();
      }
      file = resolve(root, "index.html");
    }
    await stat(file);
    res.writeHead(200, {
      "Content-Type": types[extname(file)] || "application/octet-stream",
      "Cache-Control": "no-cache",
      "X-Content-Type-Options": "nosniff",
    });
    if (req.method === "HEAD") res.end();
    else createReadStream(file).pipe(res);
  } catch {
    res.writeHead(500);
    res.end("Build the frontend with npm run build before starting it.");
  }
});
const port = Number(process.env.UI_PORT || 5173);
server.listen(port, "127.0.0.1", () =>
  console.log(`Meridian workspace: http://127.0.0.1:${port}`),
);
