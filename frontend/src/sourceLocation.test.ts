import { test } from "node:test";
import assert from "node:assert/strict";
import { locatePassage, savedSourcePassage } from "./sourceLocation.ts";

test("PDF passage matching handles wrapped lines and ligatures without inventing a match", () => {
  const items = [
    { str: "Heading" },
    { str: "Two approvals from the" },
    { str: "credit ofﬁce are required." },
    { str: "Other rule" },
  ];
  assert.deepEqual(
    locatePassage(items, "Two approvals from the credit office are required.")
      .indices,
    [1, 2],
  );
  assert.deepEqual(
    locatePassage(items, "One approval is sufficient.").indices,
    [],
  );
});
test("repeated PDF quotes do not receive a guessed highlight", () => {
  const match = locatePassage(
    [{ str: "Two approvals." }, { str: "Two approvals." }],
    "Two approvals.",
  );
  assert.deepEqual(match, { indices: [], ambiguous: true });
});
test("saved source highlighting uses the actual JSON content and preserves escaped characters", () => {
  const quote = 'Use "two" approvals.\nKeep evidence.';
  const result = savedSourcePassage(
    JSON.stringify({ event: { text: quote } }),
    quote,
  );
  assert.equal(
    result.text.slice(result.start, result.end),
    JSON.stringify(quote).slice(1, -1),
  );
  assert.equal(
    savedSourcePassage('{"text":"Something else"}', quote).start,
    -1,
  );
});
