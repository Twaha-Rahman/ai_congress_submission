import { test } from "node:test";
import assert from "node:assert/strict";
import { amountRange, money, scopeLabel, scopeContext, findingTitle, explanation, ruleSummary } from "./presentation.ts";
import type { Claim, Finding, Scope } from "./types";

test("general policy findings describe evidence and uncertainty without numeric assumptions", () => {
  const scope: Scope = { kind: "policy", description: "All employees", attributes: { country: "BD" } };
  const finding = { subject: "general_policy", finding_type: "incorrect_guidance", detail: {
    assessment: "model_assisted", explanation: "The stated deadlines differ.",
  } } as unknown as Finding;
  assert.equal(scopeLabel(scope), "All employees");
  assert.equal(scopeContext(scope), "Country: BD");
  assert.equal(findingTitle(finding), "Guidance may conflict with policy");
  assert.match(explanation(finding), /model-assisted assessment/);
  assert.equal(ruleSummary({ rule: { kind: "policy_statement", statement: "Submit expenses within 30 days." } } as Claim), "Submit expenses within 30 days.");
  assert.equal(findingTitle({ ...finding, detail: { assessment: "historical" } }), "Previous policy assessment");
});

test("money uses cents without dropping boundary precision", () => {
  assert.equal(money(2500000), "$25,000");
  assert.equal(money(2500001), "$25,000.01");
});
test("scope descriptions preserve open and closed amount boundaries", () => {
  assert.equal(
    amountRange({
      lower: 2500000,
      lower_inclusive: false,
      upper: 5000000,
      upper_inclusive: true,
    }),
    "Above $25,000 and up to $50,000",
  );
  assert.equal(
    amountRange({
      lower: 0,
      lower_inclusive: true,
      upper: 2500000,
      upper_inclusive: false,
    }),
    "From $0 to below $25,000",
  );
  assert.equal(
    amountRange({
      lower: 0,
      lower_inclusive: false,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "Above $0 and up to $25,000",
  );
  assert.equal(
    amountRange({
      lower: 0,
      lower_inclusive: true,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "From $0 up to $25,000",
  );
  assert.equal(
    amountRange({
      lower: null,
      lower_inclusive: false,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "up to $25,000",
  );
  assert.equal(
    amountRange({
      lower: 2500000,
      lower_inclusive: true,
      upper: 2500000,
      upper_inclusive: true,
    }),
    "Exactly $25,000",
  );
});
