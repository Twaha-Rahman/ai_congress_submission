import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createApiHandler } from './api.mjs';

async function bridge(t, options = {}) {
  const calls = [];
  const handler = createApiHandler({
    env: { DEMO_TOKEN_DHAKA_REVIEWER: 'server-only-secret', DEMO_TOKEN_FRANKFURT_REVIEWER: 'other-office-secret', ...options.env },
    fetchImpl: options.fetchImpl || (async (url, init) => { calls.push({ url, ...init }); return Response.json({ findings: [] }); }),
  });
  const server = createServer(handler);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  return { url: `http://127.0.0.1:${server.address().port}`, calls };
}

test('session contains capabilities, never credentials; browser authorization cannot select a principal', async t => {
  const { url, calls } = await bridge(t);
  const session = await (await fetch(`${url}/api/session`)).json();
  assert.deepEqual(session, { role: 'reviewer', canReview: true, demo: true });
  const response = await fetch(`${url}/api/dhaka/findings`, { headers: { Authorization: 'Bearer browser-supplied' } });
  assert.equal(response.status, 200);
  assert.equal(calls[0].headers.Authorization, 'Bearer server-only-secret');
  await fetch(`${url}/api/frankfurt/sources`);
  assert.equal(calls[1].headers.Authorization, 'Bearer other-office-secret');
});

test('blocks internal routes, writes to other endpoints, and cross-origin review submissions', async t => {
  const { url, calls } = await bridge(t);
  for (const path of ['federation/claims', 'audit/egress', 'findings/f_1/reviews']) {
    assert.equal((await fetch(`${url}/api/dhaka/${path}`)).status, 404);
  }
  assert.equal((await fetch(`${url}/api/dhaka/sources`, { method: 'POST' })).status, 404);
  assert.equal((await fetch(`${url}/api/dhaka/findings/f_1/reviews`, { method: 'POST', headers: { Origin: 'https://other.example', 'X-Meridian-UI': '1' } })).status, 403);
  assert.equal((await fetch(`${url}/api/dhaka/findings/f_1/reviews`, { method: 'POST' })).status, 403);
  assert.equal(calls.length, 0);
});

test('read-only configuration enforces review prohibition on the server', async t => {
  const { url, calls } = await bridge(t, { env: { UI_ROLE: 'reader', DEMO_TOKEN_DHAKA_READER: 'reader-only' } });
  assert.equal((await (await fetch(`${url}/api/session`)).json()).canReview, false);
  const response = await fetch(`${url}/api/dhaka/findings/f_1/reviews`, { method: 'POST', headers: { 'X-Meridian-UI': '1' }, body: '{}' });
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});

test('forwards review payloads and preserves office errors without reporting success', async t => {
  const { url, calls } = await bridge(t, { fetchImpl: async (_, init) => {
    calls.push(init);
    return Response.json({ error: { code: 'not_found', message: 'no such finding' } }, { status: 404 });
  } });
  const body = JSON.stringify({ action: 'resolve', reason: 'Updated guidance' });
  const response = await fetch(`${url}/api/dhaka/findings/f_1/reviews`, { method: 'POST', headers: { 'X-Meridian-UI': '1' }, body });
  assert.equal(response.status, 404);
  assert.equal(calls[0].body.toString(), body);
  assert.equal((await response.json()).error.code, 'not_found');
});

test('reports missing office connection and connection failure explicitly', async t => {
  const missing = await bridge(t, { env: { DEMO_TOKEN_DHAKA_REVIEWER: '' } });
  assert.equal((await fetch(`${missing.url}/api/dhaka/findings`)).status, 503);
  const offline = await bridge(t, { fetchImpl: async () => { throw new Error('private network detail'); } });
  const response = await fetch(`${offline.url}/api/dhaka/findings`);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error.code, 'office_unavailable');
});
