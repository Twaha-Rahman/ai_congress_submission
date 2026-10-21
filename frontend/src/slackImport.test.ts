import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseSavedSlack, slackTimestamp, buildSavedSlackManifest, maxSlackBytes } from "../shared/slackImport.mjs";

const message = (ts = "1792454400.000001", text = "Employees request leave in the HR system.") => ({ type: "message", ts, text, user: "USER" });
const metadata = () => ({ source_identity: "Team guidance", version_label: "v1", policy_family: "people", scope: { kind: "policy", description: "All employees", attributes: { country: "BD" } }, sensitivity: "restricted", permissions: { hosted_model: true } });
const parse = (value: unknown) => parseSavedSlack(JSON.stringify(value));

test("saved import accepts the committed event fixture and preserves message content", () => {
  const raw = readFileSync(new URL("../../fixtures/slack/dhaka_credit_update_2026_03_03.json", import.meta.url), "utf8");
  const saved = parseSavedSlack(raw);
  assert.equal(saved.count, 1); assert.equal(saved.channelLabel, "#dhaka-credit-policy");
  assert.equal(saved.newest, "2026-03-03T09:15:00.000000Z");
  assert.equal(saved.payload.events[0].text, JSON.parse(raw).event.text);
});
test("batch timestamps retain microseconds and publication is the latest message", () => {
  const saved = parse({ channel: "C123", events: [message("1792454400.000002"), message()] });
  assert.equal(saved.oldest, "2026-10-20T00:00:00.000001Z");
  assert.equal(saved.newest, "2026-10-20T00:00:00.000002Z");
  assert.equal(saved.payload.channel?.id, "C123");
  assert.equal(saved.payload.events[0].ts, "1792454400.000002");
  assert.equal(slackTimestamp("2026-10-20T06:00:00.123456+06:00"), "2026-10-20T00:00:00.123456Z");
  assert.equal(slackTimestamp("1792454400"), "2026-10-20T00:00:00.000000Z");
});
test("invalid JSON, ambiguous envelopes, empty files and export arrays fail clearly", () => {
  assert.throws(() => parseSavedSlack(""), /nonempty/);
  assert.throws(() => parseSavedSlack("not json"), /valid JSON/);
  assert.throws(() => parse([message()]), /event or events/);
  assert.throws(() => parse({ event: message(), events: [message()] }), /event or events/);
  assert.throws(() => parse({ events: [] }), /no messages/);
  assert.throws(() => parse({ events: [message(), null] }), /Message 2/);
  assert.throws(() => parse({ event: { ...message(), text: " " } }), /no text/);
  assert.equal(parseSavedSlack(`\ufeff${JSON.stringify({ event: message() })}`).count, 1);
});
test("timestamps reject impossible dates, missing timezone, excess precision and bad offsets", () => {
  for (const ts of ["2026-02-30T00:00:00Z", "2026-10-20T00:00:00", "1792454400.1234567", "2026-10-20T24:00:00Z", "2026-10-20T00:00:00+25:00", "NaN", 1792454400]) assert.throws(() => slackTimestamp(ts));
});
test("threads require their parent and channel batches cannot mix offices' channels", () => {
  const root = message(), reply = { ...message("1792454401.000001"), thread_ts: root.ts };
  assert.throws(() => parse({ events: [reply] }), /missing its parent/);
  assert.equal(parse({ events: [reply, root] }).count, 2);
  assert.throws(() => parse({ events: [{ ...root, channel: "C1" }, { ...reply, channel: "C2" }] }), /one channel/);
  assert.throws(() => parse({ channel: { id: "C1" }, event: { ...root, channel: "C2" } }), /one channel/);
  assert.throws(() => parse({ events: [root, { ...root, ts: "2026-10-20T00:00:00.000001Z" }] }), /same message/);
});
test("lifecycle notices are not imported as standalone snapshots", () => {
  for (const subtype of ["message_changed", "message_deleted", "channel_join"]) assert.throws(() => parse({ event: { ...message(), subtype } }), /snapshot/);
});
test("message and byte limits reject oversized batches without silently truncating", () => {
  assert.throws(() => parseSavedSlack(" ".repeat(maxSlackBytes + 1) + "{}"), /5 MB/);
  assert.throws(() => parse({ events: Array.from({ length: 201 }, (_, i) => message(`1792454400.${String(i).padStart(6, "0")}`)) }), /200 messages/);
  assert.throws(() => parse({ event: message(undefined, "x".repeat(100001)) }), /100,000/);
});
test("saved manifests fix authority, dates and export independently of file metadata", () => {
  const m = buildSavedSlackManifest({ ...metadata(), authority: "policy", publication_time: "2020-01-01T00:00:00Z", permissions: { hosted_model: true, office_export: true }, supersedes: { anything: "forged" } }, "2026-10-20T00:00:00.000002Z");
  assert.equal(m.authority, "informal"); assert.equal(m.source_type, "slack"); assert.equal(m.subject, "general_policy");
  assert.equal(m.publication_time, "2026-10-20T00:00:00.000002Z");
  assert.deepEqual(m.permissions, { hosted_model: true, office_export: false });
  assert.equal(m.effective_from, null); assert.equal(m.effective_to, null); assert.equal("supersedes" in m, false);
  assert.throws(() => buildSavedSlackManifest({ ...metadata(), source_identity: "slack:T:C:123" }, m.publication_time), /reserved/);
  assert.throws(() => buildSavedSlackManifest({ ...metadata(), scope: { kind: "policy", description: "Employees", attributes: { "country ": "BD", country: "UK" } } }, m.publication_time), /only once/);
});
