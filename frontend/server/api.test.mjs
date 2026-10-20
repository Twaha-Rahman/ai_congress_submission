import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createApiHandler } from "./api.mjs";

async function bridge(t, options = {}) {
  const calls = [];
  const handler = createApiHandler({
    env: {
      DEMO_TOKEN_DHAKA_REVIEWER: "server-only-secret",
      DEMO_TOKEN_FRANKFURT_REVIEWER: "other-office-secret",
      ...options.env,
    },
    fetchImpl:
      options.fetchImpl ||
      (async (url, init) => {
        calls.push({ url, ...init });
        return Response.json({ findings: [] });
      }),
  });
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(
    () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(resolve);
      }),
  );
  return { url: `http://127.0.0.1:${server.address().port}`, calls };
}

test("session contains capabilities, never credentials; browser authorization cannot select a principal", async (t) => {
  const { url, calls } = await bridge(t);
  const session = await (await fetch(`${url}/api/session`)).json();
  assert.deepEqual(session, { role: "reviewer", canReview: true, demo: true, uploads: {
    dhaka: { enabled: false, maxBytes: 20 * 1024 * 1024, processing: "hosted" },
    frankfurt: { enabled: false, maxBytes: 20 * 1024 * 1024, processing: "hosted" },
  } });
  const response = await fetch(`${url}/api/dhaka/findings`, {
    headers: { Authorization: "Bearer browser-supplied" },
  });
  assert.equal(response.status, 200);
  assert.equal(calls[0].headers.Authorization, "Bearer server-only-secret");
  await fetch(`${url}/api/frankfurt/sources`);
  assert.equal(calls[1].headers.Authorization, "Bearer other-office-secret");
});

test("blocks internal routes, writes to other endpoints, and cross-origin review submissions", async (t) => {
  const { url, calls } = await bridge(t);
  for (const path of [
    "federation/claims",
    "audit/egress",
    "findings/f_1/reviews",
  ]) {
    assert.equal((await fetch(`${url}/api/dhaka/${path}`)).status, 404);
  }
  assert.equal(
    (await fetch(`${url}/api/dhaka/sources`, { method: "POST" })).status,
    404,
  );
  assert.equal(
    (
      await fetch(`${url}/api/dhaka/findings/f_1/reviews`, {
        method: "POST",
        headers: { Origin: "https://other.example", "X-Meridian-UI": "1" },
      })
    ).status,
    403,
  );
  assert.equal(
    (await fetch(`${url}/api/dhaka/findings/f_1/reviews`, { method: "POST" }))
      .status,
    403,
  );
  assert.equal(calls.length, 0);
});

test("read-only configuration enforces review prohibition on the server", async (t) => {
  const { url, calls } = await bridge(t, {
    env: { UI_ROLE: "reader", DEMO_TOKEN_DHAKA_READER: "reader-only" },
  });
  assert.equal(
    (await (await fetch(`${url}/api/session`)).json()).canReview,
    false,
  );
  const response = await fetch(`${url}/api/dhaka/findings/f_1/reviews`, {
    method: "POST",
    headers: { "X-Meridian-UI": "1" },
    body: "{}",
  });
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});

test("rejects non-loopback hostnames to protect the local demo principal", async (t) => {
  const { url, calls } = await bridge(t);
  const { request } = await import("node:http");
  const status = await new Promise((resolve, reject) => {
    const req = request(
      `${url}/api/dhaka/findings`,
      { headers: { Host: "attacker.example" } },
      (res) => {
        res.resume();
        resolve(res.statusCode);
      },
    );
    req.on("error", reject);
    req.end();
  });
  assert.equal(status, 403);
  assert.equal(calls.length, 0);
});

test("forwards review payloads and preserves office errors without reporting success", async (t) => {
  const { url, calls } = await bridge(t, {
    fetchImpl: async (_, init) => {
      calls.push(init);
      return Response.json(
        { error: { code: "not_found", message: "no such finding" } },
        { status: 404 },
      );
    },
  });
  const body = JSON.stringify({
    action: "resolve",
    reason: "Updated guidance",
  });
  const response = await fetch(`${url}/api/dhaka/findings/f_1/reviews`, {
    method: "POST",
    headers: { "X-Meridian-UI": "1" },
    body,
  });
  assert.equal(response.status, 404);
  assert.equal(calls[0].body.toString(), body);
  assert.equal((await response.json()).error.code, "not_found");
});

test("reports missing office connection and connection failure explicitly", async (t) => {
  const missing = await bridge(t, { env: { DEMO_TOKEN_DHAKA_REVIEWER: "" } });
  assert.equal((await fetch(`${missing.url}/api/dhaka/findings`)).status, 503);
  const offline = await bridge(t, {
    fetchImpl: async () => {
      throw new Error("private network detail");
    },
  });
  const response = await fetch(`${offline.url}/api/dhaka/findings`);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, "office_unavailable");
});

function uploadForm(metadata = {}) {
  const body = new FormData();
  body.set("file", new Blob(["%PDF-1.7\nsynthetic request bytes"], { type: "application/pdf" }), "policy.pdf");
  body.set("manifest", JSON.stringify({ source_identity: "Travel", version_label: "v1", ...metadata }));
  return body;
}

test("PDF uploads use the office uploader credential and server-owned metadata", async (t) => {
  const { url, calls } = await bridge(t, { env: { TENANT_ID: "server-tenant", DEMO_TOKEN_DHAKA_UPLOADER: "upload-only" } });
  const response = await fetch(`${url}/api/dhaka/ingestions/pdf`, { method: "POST", headers: {
    "X-Meridian-UI": "1", Authorization: "Bearer browser-selected", Origin: url,
  }, body: uploadForm({ tenant_id: "other", region: "FRANKFURT", source_type: "slack", subject: "loan_approval" }) });
  assert.equal(response.status, 200);
  assert.equal(calls[0].headers.Authorization, "Bearer upload-only");
  assert.equal(calls[0].headers["Content-Type"], undefined);
  const form = calls[0].body;
  assert.equal(form.get("file").name, "policy.pdf");
  assert.equal(await form.get("file").text(), "%PDF-1.7\nsynthetic request bytes");
  const metadata = JSON.parse(form.get("manifest"));
  assert.equal(metadata.tenant_id, "server-tenant"); assert.equal(metadata.region, "DHAKA");
  assert.equal(metadata.subject, "general_policy"); assert.equal(metadata.source_type, "pdf");
  assert.equal(form.get("mode"), "live");
  const session = await (await fetch(`${url}/api/session`)).json();
  assert.equal(session.uploads.dhaka.enabled, true); assert.equal(session.uploads.frankfurt.enabled, false);
  assert.equal(JSON.stringify(session).includes("upload-only"), false);
});

test("reader access, missing upload credentials and cross-origin uploads cannot ingest", async (t) => {
  const readonly = await bridge(t, { env: { UI_ROLE: "reader", DEMO_TOKEN_DHAKA_UPLOADER: "upload-only" } });
  assert.equal((await (await fetch(`${readonly.url}/api/session`)).json()).uploads.dhaka.enabled, false);
  assert.equal((await fetch(`${readonly.url}/api/dhaka/ingestions/pdf`, { method: "POST", headers: { "X-Meridian-UI": "1" }, body: uploadForm() })).status, 403);
  assert.equal(readonly.calls.length, 0);
  const missing = await bridge(t);
  assert.equal((await fetch(`${missing.url}/api/dhaka/ingestions/pdf`, { method: "POST", headers: { "X-Meridian-UI": "1" }, body: uploadForm() })).status, 503);
  const enabled = await bridge(t, { env: { DEMO_TOKEN_DHAKA_UPLOADER: "upload-only" } });
  assert.equal((await fetch(`${enabled.url}/api/dhaka/ingestions/pdf`, { method: "POST", headers: { "X-Meridian-UI": "1", Origin: "https://elsewhere.example" }, body: uploadForm() })).status, 403);
  assert.equal(enabled.calls.length, 0);
});

test("rejects invalid and oversized PDF payloads before reaching an office", async (t) => {
  const { url, calls } = await bridge(t, { env: { DEMO_TOKEN_DHAKA_UPLOADER: "upload-only" } });
  const request = (body) => fetch(`${url}/api/dhaka/ingestions/pdf`, { method: "POST", headers: { "X-Meridian-UI": "1" }, body });
  assert.equal((await request("not multipart")).status, 422);
  const invalid = uploadForm(); invalid.set("file", new Blob(["This is not a PDF"]), "wrong.pdf");
  assert.equal((await request(invalid)).status, 422);
  const large = uploadForm(); large.set("file", new Blob(["%PDF-", new Uint8Array(20 * 1024 * 1024)]), "too-big.pdf");
  assert.equal((await request(large)).status, 422);
  const badJson = uploadForm(); badJson.set("manifest", "{");
  assert.equal((await request(badJson)).status, 422);
  assert.equal(calls.length, 0);
});

test("job reads retain the reader's access and comparison retries use uploader access", async (t) => {
  const { url, calls } = await bridge(t, { env: { DEMO_TOKEN_DHAKA_UPLOADER: "upload-only" } });
  await fetch(`${url}/api/dhaka/jobs?limit=50`);
  await fetch(`${url}/api/dhaka/jobs/job_123`);
  await fetch(`${url}/api/dhaka/claims/reviews`);
  await fetch(`${url}/api/dhaka/sources/src_123/comparisons?mode=live`, { method: "POST", headers: { "X-Meridian-UI": "1" } });
  assert.equal(calls[0].url.endsWith("/v1/jobs?limit=50"), true);
  assert.equal(calls[1].headers.Authorization, "Bearer server-only-secret");
  assert.equal(calls[3].headers.Authorization, "Bearer upload-only");
  assert.equal((await fetch(`${url}/api/dhaka/ingestions/pdf`)).status, 404);
  assert.equal((await fetch(`${url}/api/dhaka/sources/src_123/comparisons`)).status, 404);
});

test("an approval flag cannot describe a public hosted endpoint as a local model", async (t) => {
  const hosted = await bridge(t, { env: { LLM_LOCAL_ENDPOINT_APPROVED: "1", LLM_BASE_URL: "https://openrouter.ai/api/v1" } });
  assert.equal((await (await fetch(`${hosted.url}/api/session`)).json()).uploads.dhaka.processing, "hosted");
  const local = await bridge(t, { env: { LLM_LOCAL_ENDPOINT_APPROVED: "1", LLM_BASE_URL: "http://127.0.0.1:9000/v1" } });
  assert.equal((await (await fetch(`${local.url}/api/session`)).json()).uploads.dhaka.processing, "local");
});
