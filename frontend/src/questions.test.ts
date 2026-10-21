import { test } from "node:test";
import assert from "node:assert/strict";
import { answerSearchContext, draftFromAnswer, matchesAnswer, newQuestion, questionRequest } from "./questions.ts";
import type { Answer } from "./types.ts";

test("general questions require real question text and carry optional source/date filters", () => {
  const draft = { ...newQuestion("dhaka"), question: " Who approves software purchases? ", sourceId: "src_policy" };
  const body = questionRequest(draft);
  assert.equal(body.question, "Who approves software purchases?");
  assert.deepEqual(body.target, { subject: "general_policy" });
  assert.deepEqual(body.source_ids, ["src_policy"]);
  assert.ok(Number.isFinite(Date.parse(body.valid_at)));
  assert.equal(body.known_at, undefined);
  assert.throws(() => questionRequest({ ...draft, question: " " }), /Enter a question/);
  assert.throws(() => questionRequest({ ...draft, question: "x".repeat(501) }), /500/);
});

test("date filters use UTC and reject missing or normalized-invalid dates", () => {
  const draft = { ...newQuestion("frankfurt"), question: "When are expenses due?", dated: true,
    historical: true, knownAt: "2026-02-01T00:00", validAt: "2026-01-01T00:00" };
  assert.equal(questionRequest(draft).valid_at, "2026-01-01T00:00:00.000Z");
  assert.equal(questionRequest(draft).known_at, "2026-02-01T00:00:00.000Z");
  assert.throws(() => questionRequest({ ...draft, knownAt: "" }), /knowledge cutoff/);
  assert.throws(() => questionRequest({ ...draft, validAt: "2026-02-30T00:00" }), /policy date/);
});

test("reusing an answer preserves its question, source selection and exact cutoff", () => {
  const answer = { target: { subject: "general_policy" }, question: "Who approves software?",
    model_metadata: { source_ids: '["src_software"]' }, valid_at: "2026-01-01T00:00:00Z", known_at: "2026-03-03T12:34:56.123456Z" };
  const draft = draftFromAnswer(answer);
  assert.equal(draft.sourceId, "src_software");
  assert.equal(draft.knownAt, "2026-03-03T12:34:56.123");
  assert.equal(questionRequest(draft).known_at, answer.known_at);
  assert.equal(questionRequest({ ...draft, knownAt: "2026-03-03T12:35" }).known_at, "2026-03-03T12:35:00.000Z");
  assert.equal(questionRequest(draft).question, answer.question);
});

test("saved answer search matches labels, dates, and identifiers literally", () => {
  const answer = { answer_id: "ans_example", question: "Approvals [USD]", status: "abstained", created_at: "2026-03-03T00:00:00Z" };
  for (const search of ["[usd]", "3 Mar 2026", "unable to answer", "ans_example"]) assert.equal(matchesAnswer(answer, search), true);
  assert.equal(matchesAnswer(answer, "HR policy"), false);
  assert.equal(answerSearchContext(answer, "2026-03"), answer.created_at);
  assert.equal(answerSearchContext(answer, "ans_example"), answer.answer_id);
  assert.equal(answerSearchContext(answer, "unable to answer"), "");
});
