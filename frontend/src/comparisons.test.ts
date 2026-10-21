import { test } from "node:test";
import assert from "node:assert/strict";
import { generalRequests, receiptCoverage, ruleRequest, sameQuestionContext, type GatewayReceipt } from "./comparisons.ts";
import { newQuestion } from "./questions.ts";
import { readView, viewSearch } from "./viewState.ts";
import type { Answer } from "./types.ts";

test("general comparison sends the real question with identical UTC cutoffs and office-specific source filters", () => {
  const now = new Date("2026-10-21T10:00:00Z");
  const requests = generalRequests({ ...newQuestion("dhaka"), question: "What are our software procurement rules?", dated: true, validAt: "2026-04-01T00:00" }, { dhaka: "src_dha", frankfurt: "src_fra" }, now);
  assert.equal(requests.dhaka.question, "What are our software procurement rules?");
  assert.equal(requests.dhaka.target.subject, "general_policy");
  assert.equal(requests.dhaka.valid_at, requests.frankfurt.valid_at);
  assert.equal(requests.dhaka.known_at, requests.frankfurt.known_at);
  assert.equal(requests.dhaka.known_at, now.toISOString());
  assert.deepEqual(requests.dhaka.source_ids, ["src_dha"]);
  assert.deepEqual(requests.frankfurt.source_ids, ["src_fra"]);
});

test("strict rule requests expose their actual supported scope and preserve amount precision", () => {
  const draft = newQuestion("dhaka");
  const rules = { subject: "record_retention" as const, origin: "dhaka" as const, processing: "frankfurt" as const, amount: "" };
  const request = ruleRequest(draft, rules);
  assert.equal("source_ids" in request, false);
  assert.equal(request.target.product, "MTF_CROSS_OFFICE");
  assert.equal(request.target.origin_office, "DHAKA");
  assert.equal(request.target.processing_office, "FRANKFURT");
  assert.throws(() => ruleRequest(draft, { ...rules, processing: "dhaka" }));
  assert.equal(ruleRequest(draft, { ...rules, subject: "loan_approval", amount: "25000.01" }).target.amount_minor, 2500001);
  for (const amount of ["", "0", "-1", "5.123", "1e3", "1,000", "99999999999999999999"])
    assert.throws(() => ruleRequest(draft, { ...rules, subject: "loan_approval", amount }));
});

test("an answered gateway result with missing or withheld evidence remains incomplete", () => {
  const receipt = { federated_answer: { status: "answered", offices: [{ region: "DHAKA", status: "delivered", claims: 1, withheld_restricted: 0 }, { region: "FRANKFURT", status: "unavailable", claims: 0, withheld_restricted: 0 }], warnings: [] } } as unknown as GatewayReceipt;
  assert.equal(receiptCoverage(receipt).partial, true);
  receipt.federated_answer.offices[1] = { ...receipt.federated_answer.offices[1], status: "delivered", claims: 1 };
  assert.equal(receiptCoverage(receipt).partial, false);
  receipt.federated_answer.offices[0].withheld_restricted = 1;
  assert.equal(receiptCoverage(receipt).partial, true);
  assert.equal(receiptCoverage(receipt).withheld, 1);
});

test("shared comparisons retain both answer identities, gateway mode and the cited office's original location", () => {
  const view = { ...readView(""), compareMode: "rules" as const, compareDhaka: "ans_dha", compareFrankfurt: "ans_fra", compareRequest: "gw_20261021T000000000000", compareSourceOffice: "frankfurt" as const, compareCitation: "0", document: "src_fra", page: 2, zoom: 125 };
  assert.deepEqual(readView(viewSearch(view)), view);
  assert.equal(readView("?compareMode=wrong&evidenceOffice=wrong").compareMode, "general");
  assert.equal(readView("?evidenceOffice=wrong").compareSourceOffice, "dhaka");
});

test("mismatched saved questions or knowledge cutoffs cannot imply a common comparison", () => {
  const answer = { question: "Procurement rules?", valid_at: "2026-01-01T00:00:00Z", known_at: "2026-10-21T00:00:00Z" } as Answer;
  assert.equal(sameQuestionContext([answer, { ...answer }]), true);
  assert.equal(sameQuestionContext([answer, { ...answer, question: "Approvals?" }]), false);
  assert.equal(sameQuestionContext([answer, { ...answer, known_at: "2026-10-20T00:00:00Z" }]), false);
});
