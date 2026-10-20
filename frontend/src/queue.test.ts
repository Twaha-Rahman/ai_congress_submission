import { test } from "node:test";
import assert from "node:assert/strict";
import { findingTag, matchesFinding, orderFindings } from "./presentation.ts";
import type { Finding } from "./types.ts";

function finding(
  id: string,
  at: string,
  severity: Finding["severity"],
  state: Finding["review_state"] = "open",
): Finding {
  return {
    finding_id: `find_${id}`,
    created_at: at,
    severity,
    review_state: state,
    finding_type: "stale_guidance",
    subject: "loan_approval",
    detail: {},
    evidence: [],
    affected_scope: {
      kind: "loan",
      origin_office: "DHAKA",
      currency: "USD",
      amount_minor: {
        lower: 2500000,
        lower_inclusive: false,
        upper: 5000000,
        upper_inclusive: true,
      },
    },
  } as unknown as Finding;
}
const oldHigh = finding("2b6375fb", "2026-01-01T00:00:00Z", "high", "resolved");
const newInfo = finding("a1234567", "2026-03-01T00:00:00Z", "info");
const middleReview = finding(
  "01234567",
  "2026-02-01T00:00:00Z",
  "review",
  "acknowledged",
);
const data = [newInfo, oldHigh, middleReview];

test("finding tags match pasted hash tags, plain suffixes and full IDs", () => {
  assert.equal(findingTag(oldHigh), "#2B6375FB");
  for (const query of [
    "#2B6375FB",
    "  #2b6375fb  ",
    "2B6375FB",
    "find_2b6375fb",
    "#6375fb",
  ])
    assert.equal(matchesFinding(oldHigh, query), true, query);
  assert.equal(matchesFinding(oldHigh, "#A1234567"), false);
  assert.equal(matchesFinding(oldHigh, "stale"), true);
  assert.equal(matchesFinding(oldHigh, "$25,000"), true);
});
test("each sort choice produces its intended order without mutating the input", () => {
  assert.deepEqual(orderFindings(data, "severity"), [
    oldHigh,
    middleReview,
    newInfo,
  ]);
  assert.deepEqual(orderFindings(data, "newest"), [
    newInfo,
    middleReview,
    oldHigh,
  ]);
  assert.deepEqual(orderFindings(data, "oldest"), [
    oldHigh,
    middleReview,
    newInfo,
  ]);
  assert.deepEqual(orderFindings(data, "status"), [
    newInfo,
    middleReview,
    oldHigh,
  ]);
  assert.deepEqual(orderFindings(data, "id"), [middleReview, oldHigh, newInfo]);
  assert.deepEqual(data, [newInfo, oldHigh, middleReview]);
});
test("ties are deterministic, including findings sharing the short tag", () => {
  const a = finding("aaa_2b6375fb", oldHigh.created_at, "high");
  const b = finding("bbb_2b6375fb", oldHigh.created_at, "high");
  assert.deepEqual(orderFindings([b, a], "newest"), [a, b]);
  assert.equal(orderFindings([b, a], "id")[0], a);
});

test("date sorting handles optional fractional seconds and equivalent timezone offsets", () => {
  const second = finding("ffffffff", "2026-01-01T00:00:00Z", "info");
  const fraction = finding("00000000", "2026-01-01T00:00:00.500Z", "info");
  const later = finding("11111111", "2026-01-01T01:00:01+01:00", "info");
  assert.deepEqual(orderFindings([fraction, second, later], "newest"), [
    later,
    fraction,
    second,
  ]);
  assert.deepEqual(orderFindings([fraction, later, second], "oldest"), [
    second,
    fraction,
    later,
  ]);
});
