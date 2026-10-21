import { test } from "node:test";
import assert from "node:assert/strict";
import { blankDraft, buildPolicyManifest, jobDescription, validatePdf, visibleSources, utcDate, keepUploadSelection, elapsedMilliseconds, durationLabel } from "./uploads.ts";
import type { PolicyManifest, Source, UploadJob } from "./types";

const draft = () => ({ ...blankDraft(), name: "Travel policy", family: "travel", scope: "All employees", published: "2026-10-01", effective: "2026-10-02" });
test("PDF selection checks actual bytes, empty files and the size cap", async () => {
  assert.equal(await validatePdf(new Blob(["%PDF-1.7\nPDF content"])), "");
  assert.match(await validatePdf(new Blob()), /empty/);
  assert.match(await validatePdf(new Blob(["not a PDF"])), /not a PDF/);
  assert.match(await validatePdf(new Blob(["%PDF-1.7"]), 3), /smaller/);
});
test("manifests preserve explicit metadata and keep office export disabled", () => {
  const manifest = buildPolicyManifest({ ...draft(), hosted: true, attributes: [{ key: "country", value: "BD" }] });
  assert.equal(manifest.publication_time, "2026-10-01T00:00:00Z");
  assert.equal(manifest.effective_from, "2026-10-02T00:00:00Z");
  assert.deepEqual(manifest.permissions, { hosted_model: true, office_export: false });
  assert.deepEqual(manifest.scope.attributes, { country: "BD" });
  assert.equal(buildPolicyManifest({ ...draft(), effective: "" }).effective_from, null);
});
test("invalid dates, reversed intervals and ambiguous scope labels are rejected", () => {
  assert.throws(() => utcDate("2026-02-30"), /valid calendar/);
  assert.throws(() => utcDate("2026-2-3"), /complete date/);
  assert.throws(() => buildPolicyManifest({ ...draft(), until: "2026-10-01" }), /after/);
  assert.throws(() => buildPolicyManifest({ ...draft(), attributes: [{ key: "country", value: "BD" }, { key: "country", value: "UK" }] }), /only once/);
  assert.throws(() => buildPolicyManifest({ ...draft(), attributes: [{ key: "country", value: "" }] }), /name and a value/);
});
test("replacement is explicit, binds clauses and requires compatible scope and a new version", () => {
  const earlier = buildPolicyManifest(draft());
  const target = { manifest: earlier, clauses: ["travel:v1:1", "travel:v1:2"] };
  const next = buildPolicyManifest({ ...draft(), version: "v2", effective: "2026-11-01" }, target);
  assert.equal(next.supersedes?.supersedes_version_label, "v1");
  assert.deepEqual(next.supersedes?.replaced_clause_ids, target.clauses);
  assert.throws(() => buildPolicyManifest(draft(), target), /new version/);
  assert.throws(() => buildPolicyManifest({ ...draft(), version: "v2", effective: "" }, target), /effective date/);
  assert.throws(() => buildPolicyManifest({ ...draft(), version: "v2", effective: "2026-11-01", scope: "Different team" }, target), /scope/);
  assert.throws(() => buildPolicyManifest({ ...draft(), version: "v2", effective: "2026-09-01" }, target), /after/);
});
test("source sorting/filtering never mutates data or selects a different document", () => {
  const sources = [
    { source_id: "b", source_identity: "Travel", version_label: "v2", source_type: "pdf", authority: "policy", ingested_at: "2026-10-20T00:00:00Z", policy_family: "expenses" },
    { source_id: "a", source_identity: "Leave", version_label: "v1", source_type: "pdf", authority: "policy", ingested_at: "2026-10-01T00:00:00Z" },
  ] as Source[];
  assert.equal(visibleSources(sources, "", "all", "name")[0].source_id, "a");
  assert.equal(visibleSources(sources, "expenses", "pdf", "newest")[0].source_id, "b");
  assert.equal(sources[0].source_id, "b");
});
test("job status copy distinguishes incomplete processing from a completed check", () => {
  assert.match(jobDescription({ status: "needs_review", review_reason: "policy_retrieval_limited" } as UploadJob), /incomplete/);
  assert.match(jobDescription({ status: "running", kind: "pdf" } as UploadJob), /extracting/);
  assert.match(jobDescription({ status: "succeeded" } as UploadJob), /does not certify/);
});

test("new uploads preserve the open job and duration displays handle live, finished and legacy records", () => {
  assert.equal(keepUploadSelection("job-in-progress", "new-job"), "job-in-progress");
  assert.equal(keepUploadSelection("", "new-job"), "new-job");
  assert.equal(durationLabel(elapsedMilliseconds("2026-10-20T00:00:00Z", "2026-10-20T00:02:46Z")), "2m 46s");
  assert.equal(durationLabel(elapsedMilliseconds("2026-10-20T00:00:00Z", null, Date.parse("2026-10-20T00:00:12Z"))), "12s");
  assert.equal(durationLabel(elapsedMilliseconds(null, null)), "Not recorded");
  assert.equal(elapsedMilliseconds("invalid", null), null);
  assert.equal(durationLabel(10), "<1s");
});

test("upload badges follow current review progress while preserving processing failures and warnings",async()=>{
  const {jobDisplayState,jobDisplayLabel,processingWarnings}=await import("./uploads");
  const job={status:"needs_review",review_reason:"policy_comparison_limit",review_summary:{total:2,open:1,acknowledged:0,resolved:1,dismissed:0,state:"needs_review"}} as UploadJob;
  assert.equal(jobDisplayLabel(job),"Needs review");assert.match(jobDescription(job),/1 of 2/);
  const ack={...job,review_summary:{...job.review_summary!,open:0,acknowledged:1,state:"acknowledged" as const}};
  assert.equal(jobDisplayLabel(ack),"Acknowledged");assert.match(jobDescription(ack),/follow-up remains/);
  const done={...job,review_summary:{total:2,open:0,acknowledged:0,resolved:1,dismissed:1,state:"reviewed" as const}};
  assert.equal(jobDisplayLabel(done),"Reviewed");assert.match(jobDescription(done),/resolved or dismissed/);
  assert.match(processingWarnings(done),/comparison limit/);assert.equal(done.status,"needs_review");
  for(const status of ["running","failed","queued"] as const)assert.equal(jobDisplayState({...done,status}),status);
  assert.equal(jobDisplayState({...job,review_summary:{total:0,open:0,acknowledged:0,resolved:0,dismissed:0,state:"none"}}),"needs_review");
});
