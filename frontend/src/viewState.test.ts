import { test } from "node:test";
import assert from "node:assert/strict";
import {
  pinSelection,
  readView,
  selectedFinding,
  viewSearch,
} from "./viewState.ts";
import type { Finding } from "./types.ts";

const a = { finding_id: "find_aaa_12345678" } as Finding;
const b = { finding_id: "find_bbb_abcdefab" } as Finding;
test("shared URLs round-trip filters, selected finding, tab, pane, auto-refresh, and source location", () => {
  const view = {
    ...readView("?office=frankfurt&tag=%23abcdefab"),
    finding: b.finding_id,
    search: "a & b #tag",
    state: "resolved",
    type: "compliance_gap",
    severity: "high",
    sort: "oldest" as const,
    tab: "reviews" as const,
    pane: "detail" as const,
    autoRefresh: true,
    source: "policy:v3:4.1",
    sourceMode: "original" as const,
    page: 3,
  };
  assert.deepEqual(readView(viewSearch(view)), view);
});
test("pinning an implicitly viewed finding preserves it when order changes", () => {
  const initial = readView("");
  assert.equal(selectedFinding(initial, [a, b], [a, b]).id, a.finding_id);
  const sorted = { ...pinSelection(initial, a), sort: "newest" as const };
  assert.equal(selectedFinding(sorted, [a, b], [b, a]).id, a.finding_id);
  assert.equal(readView(viewSearch(sorted)).tag, "12345678");
});
test("tag-only links resolve uniquely; collisions and unknown tags never open an arbitrary finding", () => {
  assert.equal(
    selectedFinding(readView("?tag=abcdefab"), [a, b], []).id,
    b.finding_id,
  );
  const collision = { finding_id: "find_other_abcdefab" } as Finding;
  assert.equal(
    selectedFinding(readView("?tag=abcdefab"), [b, collision], [b, collision])
      .ambiguous,
    true,
  );
  assert.equal(
    selectedFinding(readView("?tag=00000000"), [a, b], [a, b]).missingTag,
    true,
  );
  assert.equal(
    selectedFinding(
      readView(`?finding=${b.finding_id}&tag=12345678`),
      [a, b],
      [],
    ).id,
    b.finding_id,
  );
});
test("old finding links stay valid and malformed options use safe defaults", () => {
  const view = readView("?finding=find_old&sort=bogus&page=-3&tab=bad&auto=no");
  assert.equal(view.finding, "find_old");
  assert.equal(view.pane, "detail");
  assert.equal(view.sort, "severity");
  assert.equal(view.page, 1);
  assert.equal(view.tab, "evidence");
  assert.equal(view.autoRefresh, false);
});

test("source library links preserve search, sort, inspected document, job and related findings", () => {
  const view = { ...readView(""), sourceSearch: "Travel & leave", sourceType: "pdf" as const,
    sourceSort: "name" as const, document: "src_original", uploadJob: "job_123", forSource: "src_policy", page: 3, zoom: 125 };
  assert.deepEqual(readView(viewSearch(view)), view);
});

test("Questions links preserve saved answer, search, mobile pane and cited source location", () => {
  const view = { ...readView(""), questionId: "ans_123", questionSearch: "loan & USD", questionPane: "answer" as const,
    questionCitation: "2", questionPanel: "recent" as const, document: "src_loan", page: 2, zoom: 125 };
  assert.deepEqual(readView(viewSearch(view)), view);
  assert.equal(readView("?answer=ans_123").questionPane, "answer");
  assert.equal(readView("?questionPane=bad").questionPane, "compose");
});

test("activity and source-version links restore filters, selections and comparison direction",()=>{
  const view={...readView(""),activitySearch:"req_42",activityCategory:"transfer" as const,activityOutcome:"blocked",activitySince:"2026-10-21T09:00",activityUntil:"2026-10-22T18:30",activityId:"transfer:egress_1",versionSource:"src2",versionBase:"src1",versionNext:"src2",versionFilter:"changed" as const,versionSearch:"HR"};
  const restored=readView(viewSearch(view));
  for(const key of ["activitySearch","activityCategory","activityOutcome","activitySince","activityUntil","activityId","versionSource","versionBase","versionNext","versionFilter","versionSearch"] as const)assert.equal(restored[key],view[key]);
  const invalid=readView("?activityType=secret&activityOutcome=unknown&activitySince=garbage&versionFilter=unknown");
  assert.equal(invalid.activityCategory,"all");assert.equal(invalid.activityOutcome,"all");assert.equal(invalid.activitySince,"");assert.equal(invalid.versionFilter,"changes");
});
