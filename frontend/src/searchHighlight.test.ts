import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Highlight from "./Highlight.tsx";
import { matchingExcerpt, searchRanges } from "./searchHighlight.ts";

test("search highlights every literal case-insensitive match, ignoring surrounding query spaces", () => {
  assert.deepEqual(searchRanges("Approval needs approval", " APPROVAL "), [
    { start: 0, end: 8 }, { start: 15, end: 23 },
  ]);
  assert.deepEqual(searchRanges("Above $0 and up to $25,000", "$0"), [{ start: 6, end: 8 }]);
  assert.deepEqual(searchRanges("Literal [a]+, not a regex", "[a]+"), [{ start: 8, end: 12 }]);
  assert.deepEqual(searchRanges("No match", ""), []);
  assert.deepEqual(searchRanges("No match", "missing"), []);
});

test("hash-prefixed queries highlight only identifiers", () => {
  assert.deepEqual(searchRanges("#2B6375FB", "#2b63", true), [{ start: 1, end: 5 }]);
  assert.deepEqual(searchRanges("2B63 in a quote", "#2b63"), []);
  assert.deepEqual(searchRanges("#2B6375FB", "#", true), []);
});

test("Unicode case expansion preserves original text offsets", () => {
  assert.deepEqual(searchRanges("İX approval", "x"), [{ start: 1, end: 2 }]);
  assert.deepEqual(searchRanges("😀 approval", "approval"), [{ start: 3, end: 11 }]);
});

test("long evidence excerpts retain the entire match and indicate omitted text", () => {
  const short = "You do not need a second sign-off.";
  assert.equal(matchingExcerpt(short, "second sign-off"), short);
  const quote = "Before ".repeat(30) + "one approval is sufficient" + " after".repeat(30);
  const excerpt = matchingExcerpt(quote, "approval is sufficient");
  assert.ok(excerpt.startsWith("…"));
  assert.ok(excerpt.endsWith("…"));
  assert.ok(excerpt.includes("approval is sufficient"));
  assert.ok(excerpt.length < quote.length);
  assert.equal(matchingExcerpt(quote, "no match"), "");
});

test("highlight markup preserves source content and escapes HTML", () => {
  assert.equal(
    renderToStaticMarkup(createElement(Highlight, { text: "One <script> and one approval", query: "one" })),
    '<span><mark class="search-match">One</mark> &lt;script&gt; and <mark class="search-match">one</mark> approval</span>',
  );
});
