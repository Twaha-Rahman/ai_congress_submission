import type { PolicyManifest, Source, UploadJob } from "./types";

export const maxPdfBytes = 20 * 1024 * 1024;
export const isProcessing = (job: UploadJob) => ["queued", "running"].includes(job.status);
export const keepUploadSelection = (current: string, incoming: string) => current || incoming;

export function elapsedMilliseconds(start: string | null | undefined, end: string | null | undefined, now = Date.now()) {
  if (!start) return null;
  const duration = (end ? Date.parse(end) : now) - Date.parse(start);
  return Number.isFinite(duration) ? Math.max(0, duration) : null;
}
export function durationLabel(milliseconds: number | null) {
  if (milliseconds === null) return "Not recorded";
  if (milliseconds < 1000) return "<1s";
  const seconds = Math.floor(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes}m ${seconds % 60}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export const stageLabels: Record<string, string> = {
  reading: "Reading document", extraction: "Extracting statements", validation: "Validating evidence",
  comparison: "Comparing policies", publication: "Saving results",
};
export const jobLabels: Record<UploadJob["status"], string> = {
  queued: "Queued", running: "Processing", succeeded: "Processed",
  needs_review: "Needs review", failed: "Failed",
};

export function jobDisplayState(job: UploadJob): UploadJob["status"] | "acknowledged" | "reviewed" {
  const review=job.review_summary;
  return ["succeeded","needs_review"].includes(job.status)&&review?.total&&review.state!=="none" ? review.state : job.status;
}
export function jobDisplayLabel(job: UploadJob) {
  const state=jobDisplayState(job);
  return state==="reviewed"?"Reviewed":state==="acknowledged"?"Acknowledged":jobLabels[state];
}
export function jobReviewDescription(job: UploadJob) {
  const review=job.review_summary;
  if(!review?.total||!["succeeded","needs_review"].includes(job.status))return "";
  if(review.open)return `${review.total-review.open} of ${review.total} findings reviewed; ${review.open} still open.`;
  if(review.acknowledged)return `${review.acknowledged} ${review.acknowledged===1?"finding is":"findings are"} acknowledged; follow-up remains.`;
  return `${review.total} ${review.total===1?"finding has":"findings have"} been resolved or dismissed.`;
}

export function fileSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export async function validatePdf(file: Blob & { name?: string }, limit = maxPdfBytes): Promise<string> {
  if (!file.size) return "This file is empty. Choose a text-based PDF.";
  if (file.size > limit) return `Choose a PDF smaller than ${Math.round(limit / (1024 * 1024))} MB.`;
  if (!(await file.slice(0, 1024).text()).includes("%PDF-")) return "This file is not a PDF. Choose a PDF document.";
  return "";
}

export interface PolicyDraft {
  name: string; version: string; family: string; published: string;
  effective: string; until: string; scope: string;
  authority: "policy" | "procedure"; sensitivity: "demo_shareable" | "restricted";
  hosted: boolean; attributes: { key: string; value: string }[];
}

export const blankDraft = (): PolicyDraft => ({
  name: "", version: "v1", family: "", published: "", effective: "", until: "", scope: "",
  authority: "policy", sensitivity: "demo_shareable", hosted: false, attributes: [],
});

export function utcDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Enter a complete date.");
  const iso = `${value}T00:00:00Z`;
  const parsed = new Date(iso);
  if (!Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value)
    throw new Error("Enter a valid calendar date.");
  return iso;
}

export function buildPolicyManifest(draft: PolicyDraft, replaced?: { manifest: PolicyManifest; clauses: string[] }): PolicyManifest {
  for (const [label, value] of [["Policy name", draft.name], ["Version", draft.version], ["Policy category", draft.family]])
    if (!value.trim() || value.trim().length > 128) throw new Error(`${label} must contain between 1 and 128 characters.`);
  if (!draft.scope.trim() || draft.scope.trim().length > 1000) throw new Error("Describe who and what the policy applies to (up to 1,000 characters).");
  const attributes: Record<string, string> = {};
  for (const row of draft.attributes) {
    const key = row.key.trim(), value = row.value.trim();
    if (!key && !value) continue;
    if (!key || !value || key.length > 128 || value.length > 500) throw new Error("Each scope label needs a name and a value.");
    if (Object.hasOwn(attributes, key)) throw new Error("Use each scope label only once.");
    Object.defineProperty(attributes, key, { value, enumerable: true });
  }
  const effective = draft.effective ? utcDate(draft.effective) : null;
  const until = draft.until ? utcDate(draft.until) : null;
  if (effective && until && effective >= until) throw new Error("The end date must be after the effective date.");
  const manifest: PolicyManifest = {
    source_identity: draft.name.trim(), version_label: draft.version.trim(),
    policy_family: draft.family.trim(), authority: draft.authority,
    scope: { kind: "policy", description: draft.scope.trim(), attributes },
    effective_from: effective, effective_to: until, publication_time: utcDate(draft.published),
    sensitivity: draft.sensitivity, permissions: { hosted_model: draft.hosted, office_export: false },
  };
  if (replaced) {
    if (!effective) throw new Error("A replacement needs an effective date.");
    if (!replaced.clauses.length) throw new Error("The earlier version has no clauses to replace.");
    if (manifest.version_label === replaced.manifest.version_label) throw new Error("Give the replacement a new version label.");
    if (replaced.manifest.effective_from && effective <= replaced.manifest.effective_from)
      throw new Error("The replacement must take effect after the earlier version began.");
    const previous = replaced.manifest.scope;
    if (manifest.scope.description !== previous.description
      || Object.keys(attributes).length !== Object.keys(previous.attributes).length
      || Object.entries(attributes).some(([key, value]) => previous.attributes[key] !== value)
      || manifest.policy_family !== replaced.manifest.policy_family
      || manifest.source_identity !== replaced.manifest.source_identity)
      throw new Error("A replacement must keep the earlier policy's name, category and scope.");
    manifest.supersedes = {
      supersedes_source_identity: replaced.manifest.source_identity,
      supersedes_version_label: replaced.manifest.version_label,
      replaced_clause_ids: replaced.clauses, replaced_scope: replaced.manifest.scope,
      effective_from: effective,
    };
  }
  return manifest;
}

export function visibleSources(sources: Source[], query: string, type: string, sort: string) {
  const search = query.trim().toLocaleLowerCase();
  return sources.filter((s) => (type === "all" || s.source_type === type) &&
    [s.source_identity, s.version_label, s.policy_family || "", s.authority].join(" ").toLocaleLowerCase().includes(search))
    .sort((a, b) => (sort === "name" ? a.source_identity.localeCompare(b.source_identity) : Date.parse(b.ingested_at) - Date.parse(a.ingested_at)) || a.source_id.localeCompare(b.source_id));
}

const reasonLabels: Record<string, string> = {
  policy_reference_missing: "No accepted policy was available to compare against.",
  policy_retrieval_limited: "Only the most relevant statements were compared; coverage is incomplete.",
  policy_comparison_limit: "The comparison limit was reached; some statements still need checking.",
  policy_comparison_budget: "The comparison time limit was reached. Retry the comparison to continue.",
  policy_extraction_limit: "Some document clauses were not extracted; coverage is incomplete.",
  policy_context_unavailable: "Complete source context was unavailable or too large to compare.",
  policy_comparison_failed: "The model comparison failed. Check the model connection, then retry.",
  insufficient_context: "Applicability, timing or an exception needs human interpretation.",
  comparison_evidence_mismatch: "The model's quotations did not match the source. Its assessment was withheld.",
  pending_replacement: "The replacement could not be fully validated. The earlier policy remains current.",
};
export function processingWarnings(job: UploadJob) {
  return (job.review_reason?.split(";").map(s=>s.trim()).filter(Boolean)||[]).map(s=>reasonLabels[s]||s.replaceAll("_"," ")).join(" ");
}
export function jobDescription(job: UploadJob) {
  if (job.status === "queued") return "Waiting for this office to begin processing.";
  if (job.status === "running") {
    const descriptions: Record<string, string> = {
      reading: "Reading the document and locating its text passages.",
      extraction: "The model is extracting policy statements from the document.",
      validation: "Matching quotations to the source and validating the extracted statements.",
      comparison: "Checking relevant statement pairs against their full source context.",
      publication: "Saving statements, findings and their evidence.",
    };
    return descriptions[job.progress?.current_stage || ""] || (job.kind === "policy_comparison" ? "Comparing accepted statements with relevant policies." : job.kind === "slack" ? "Reading Slack messages, extracting statements and checking relevant policies." : "Reading the PDF, extracting statements and checking relevant policies.");
  }
  const review=jobReviewDescription(job);
  if(review)return review;
  if (job.status === "succeeded") return "Processing finished. Findings are candidates for review; this does not certify compliance.";
  return processingWarnings(job) || "Open the source and review its context before drawing a conclusion.";
}
