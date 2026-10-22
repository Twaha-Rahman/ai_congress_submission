import { test } from "node:test";
import assert from "node:assert/strict";
import { availableSource } from "./sourceWithdrawal";
import { visibleSources, jobDisplayLabel, jobDescription } from "./uploads";
import { unreviewedFindings } from "./reviewQueue";
import { readView, viewSearch, selectedFinding } from "./viewState";
import type { Source, UploadJob, Finding } from "./types";

test("withdrawn sources stay in history while current selectors exclude them", () => {
  const active = {
    source_id: "active",
    source_identity: "Policy",
    version_label: "v2",
    source_type: "pdf",
    authority: "policy",
    ingested_at: "2026-01-01",
    status: "published",
  } as Source;
  const withdrawn = {
    ...active,
    source_id: "old",
    version_label: "v1",
    status: "withdrawn",
    withdrawal: { withdrawn_at: "2026-10-22T12:00:00Z", reason: "Retired" },
  };
  assert.equal(availableSource(active), true);
  assert.equal(availableSource(withdrawn), false);
  assert.equal(availableSource(withdrawn, "2026-10-22T11:59"), true);
  assert.equal(availableSource(withdrawn, "2026-10-22T12:00"), false);
  assert.equal(availableSource(withdrawn, "invalid"), false);
  assert.equal(availableSource(withdrawn, "2026-10-22T17:59:00+06:00"), true);
  assert.deepEqual(
    visibleSources([active, withdrawn], "", "all", "name", "active").map(
      (source) => source.source_id,
    ),
    ["active"],
  );
  assert.deepEqual(
    visibleSources([active, withdrawn], "", "all", "name", "withdrawn").map(
      (source) => source.source_id,
    ),
    ["old"],
  );
  const shared = {
    ...readView(""),
    sourceStatus: "withdrawn" as const,
    document: "old",
  };
  assert.deepEqual(readView(viewSearch(shared)), shared);
});

test("withdrawal updates job display and queue counts without changing review decisions or deep links", () => {
  const finding = {
    finding_id: "historical",
    review_state: "open",
    detail: { assessment: "historical" },
    explanation_code: "revision_not_current",
  } as unknown as Finding;
  assert.deepEqual(unreviewedFindings([finding]), []);
  assert.equal(
    selectedFinding(readView("?finding=historical"), [finding], []).id,
    "historical",
  );
  assert.equal(finding.review_state, "open");
  const job = {
    status: "needs_review",
    review_summary: {
      total: 0,
      open: 0,
      acknowledged: 0,
      resolved: 0,
      dismissed: 0,
      state: "withdrawn",
    },
  } as UploadJob;
  assert.equal(jobDisplayLabel(job), "Withdrawn");
  assert.match(jobDescription(job), /history remain available/);
  assert.equal(
    jobDisplayLabel({
      status: "failed",
      error_code: "source_withdrawn",
    } as UploadJob),
    "Withdrawn",
  );
});
