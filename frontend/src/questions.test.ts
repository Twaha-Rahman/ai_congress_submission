import { test } from "node:test";
import assert from "node:assert/strict";
import { amountMinor, answerSearchContext, draftFromAnswer, matchesAnswer, newQuestion, questionRequest } from "./questions.ts";
import type { Answer } from "./types.ts";

test("loan facts preserve exact cents and UTC dates independently of browser timezone", () => {
  const draft = { ...newQuestion("dhaka", new Date("2026-03-03T12:30:00Z")), amount: "25000.01" };
  const body = questionRequest(draft);
  assert.equal(body.target.amount_minor, 2500001);
  assert.equal(body.valid_at, "2026-03-03T12:30:00.000Z");
  assert.equal(body.known_at, undefined);
  assert.match(body.question, /25,000.01/);
  for (const invalid of ["", "0", "-1", "1.001", "2e4", "25,000", "NaN", "10000000000000.01"])
    assert.throws(() => amountMinor(invalid));
  assert.equal(amountMinor("0.01"), 1);
  assert.equal(amountMinor("10000000000000"), 10 ** 15);
});

test("retention queries omit unspecified scope and validate historical dates and labels", () => {
  const draft = { ...newQuestion("frankfurt"), subject: "record_retention" as const, origin: "" as const,
    historical: true, knownAt: "2026-02-01T00:00", validAt: "2026-01-01T00:00" };
  const body = questionRequest(draft);
  assert.deepEqual(body.target, { subject: "record_retention", record_class: "loan_records", starting_event: "loan_closure", product: "MTF_CROSS_OFFICE" });
  assert.equal(body.known_at, "2026-02-01T00:00:00.000Z");
  assert.throws(() => questionRequest({ ...draft, knownAt: "" }), /knowledge cutoff/);
  assert.throws(() => questionRequest({ ...draft, validAt: "wrong" }), /policy date/);
  assert.throws(() => questionRequest({ ...draft, validAt: "2026-02-30T00:00" }), /policy date/);
  assert.throws(() => questionRequest({ ...draft, question: "x".repeat(501) }), /500/);
});

test("reusing saved facts preserves the exact knowledge cutoff without rerunning on selection", () => {
  const answer = { target: { subject: "loan_approval", amount_minor: 3000001, currency: "USD", loan_type: "business", origin_office: "DHAKA" },
    question: "Historical loan", valid_at: "2026-01-01T00:00:00Z", known_at: "2026-03-03T12:34:56.123Z" } as Answer;
  assert.deepEqual(questionRequest(draftFromAnswer(answer)), {
    question: answer.question, target: answer.target, valid_at: "2026-01-01T00:00:00.000Z", known_at: answer.known_at,
  });
  const precise = { ...answer, known_at: "2026-03-03T12:34:56.123456Z" };
  const draft = draftFromAnswer(precise);
  assert.equal(draft.knownAt, "2026-03-03T12:34:56.123");
  assert.equal(questionRequest(draft).known_at, precise.known_at);
  assert.equal(questionRequest({ ...draft, knownAt: "2026-03-03T12:35" }).known_at, "2026-03-03T12:35:00.000Z");
});

test("saved answer search matches labels, dates, and identifiers literally", () => {
  const answer = { answer_id: "ans_example", question: "Approvals [USD]", status: "abstained", created_at: "2026-03-03T00:00:00Z" };
  for (const search of ["[usd]", "3 Mar 2026", "unable to answer", "ans_example"]) assert.equal(matchesAnswer(answer, search), true);
  assert.equal(matchesAnswer(answer, "HR policy"), false);
  assert.equal(answerSearchContext(answer, "2026-03"), answer.created_at);
  assert.equal(answerSearchContext(answer, "ans_example"), answer.answer_id);
  assert.equal(answerSearchContext(answer, "unable to answer"), "");
});
