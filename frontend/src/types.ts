export type Office = "dhaka" | "frankfurt";
export type ReviewState = "open" | "acknowledged" | "resolved" | "dismissed";
export type ReviewAction = "acknowledge" | "resolve" | "dismiss";
export type FindingType =
  | "stale_guidance"
  | "incorrect_guidance"
  | "contradiction"
  | "compliance_gap"
  | "compatible_difference"
  | "supersession"
  | "not_comparable"
  | "needs_review";
export interface AmountInterval {
  lower: number | null;
  upper: number | null;
  lower_inclusive: boolean;
  upper_inclusive: boolean;
}
export interface Scope {
  kind: "loan" | "record" | "policy";
  origin_office?: string;
  description?: string;
  attributes?: Record<string, string>;
  amount_minor?: AmountInterval;
  currency?: string;
  loan_type?: string;
  processing_office?: string;
  record_class?: string;
  starting_event?: string;
  product?: string;
}
export interface Evidence {
  claim_revision_id: string;
  clause_id: string;
  source_id: string;
  page: number;
  section: string | null;
  quote: string;
  start_char: number;
  end_char: number;
  manifest_root: string;
}
export interface Finding {
  finding_id: string;
  finding_type: FindingType;
  subject: string;
  severity: "high" | "review" | "info";
  explanation_code: string;
  affected_scope: Scope;
  affected_valid_interval: { start: string | null; end: string | null };
  authority_basis: string;
  claim_revision_ids: string[];
  detail: Record<string, string>;
  evidence: Evidence[];
  review_state: ReviewState;
  created_at: string;
  snapshot_id: string;
  snapshot_hash: string;
  signature: string;
  key_id: string;
  superseded_by_snapshot_id?: string | null;
}
export interface Source {
  source_id: string;
  source_identity: string;
  version_label: string;
  source_type: "pdf" | "slack";
  authority: "policy" | "procedure" | "informal";
  sensitivity: string;
  publication_time: string | null;
  effective_from: string | null;
  effective_to: string | null;
  ingested_at: string;
  subject?: string;
  policy_family?: string;
  hosted_model?: boolean;
  office_export?: boolean;
  supersedes: {
    supersedes_source_identity: string;
    supersedes_version_label: string;
    effective_from: string;
  } | null;
}
export interface Claim {
  revision_id: string;
  source_id: string;
  source_identity: string;
  source_version_label: string;
  authority: string;
  valid_from: string | null;
  valid_to: string | null;
  system_from: string;
  system_to: string | null;
  rule: { kind: string; value?: string | number; unit?: string; statement?: string; modality?: string };
  extraction_mode: "live" | "cached" | "replay";
}
export interface ReviewEvent {
  event_id: string;
  actor: string;
  action: ReviewAction;
  reason: string;
  prior_state: ReviewState;
  new_state: ReviewState;
  created_at: string;
  snapshot_id: string | null;
}
export interface Session {
  role: "reviewer" | "reader";
  canReview: boolean;
  demo: boolean;
  uploads?: Record<Office, { enabled: boolean; processing: "local" | "hosted"; maxBytes: number }>;
}

export interface UploadJob {
  job_id: string;
  kind: "pdf" | "slack" | "policy_comparison";
  status: "queued" | "running" | "succeeded" | "needs_review" | "failed";
  mode: "live" | "cached" | "replay";
  stage_modes: Record<string, string>;
  attempts?: number;
  max_attempts?: number;
  progress?: { attempt: number; current_stage: string | null; stages: JobStage[]; previous_attempts?: unknown[] };
  error_code: string | null;
  review_reason: string | null;
  source_id: string | null;
  source_identity: string | null;
  version_label: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobStage {
  key: string;
  status: "running" | "completed" | "failed" | "interrupted";
  started_at: string;
  finished_at: string | null;
  elapsed_ms: number | null;
  completed?: number;
  total?: number;
}

export interface PolicyManifest {
  source_identity: string;
  version_label: string;
  policy_family: string;
  authority: "policy" | "procedure";
  scope: { kind: "policy"; description: string; attributes: Record<string, string> };
  effective_from: string | null;
  effective_to: string | null;
  publication_time: string;
  sensitivity: "demo_shareable" | "restricted";
  permissions: { hosted_model: boolean; office_export: boolean };
  supersedes?: {
    supersedes_source_identity: string;
    supersedes_version_label: string;
    replaced_clause_ids: string[];
    replaced_scope: PolicyManifest["scope"];
    effective_from: string;
  };
}

export interface SourceDetail {
  source: Source & { manifest: PolicyManifest };
  clauses: { clause_id: string; page: number; section: string | null }[];
}
export interface WorkspaceData {
  findings: Finding[];
  sources: Source[];
  claims: Claim[];
}
export interface FindingResponse {
  finding: Pick<
    Finding,
    | "snapshot_id"
    | "snapshot_hash"
    | "signature"
    | "key_id"
    | "review_state"
    | "superseded_by_snapshot_id"
  > & {
    payload: Omit<
      Finding,
      | "review_state"
      | "snapshot_id"
      | "snapshot_hash"
      | "signature"
      | "key_id"
      | "superseded_by_snapshot_id"
    >;
  };
  reviews?: ReviewEvent[];
}

export type CheckStatus = "passed" | "failed" | "not_checked";
export interface VerificationReport {
  target_type: string;
  target_id: string;
  generated_at?: string;
  checks: { check: string; status: CheckStatus; reason?: string | null; detail: Record<string, string> }[];
}
export interface LineageNode {
  node_id: string;
  node_type: string;
  label: string;
  attributes: Record<string, string>;
  restricted: boolean;
}
export interface LineageGraph {
  root_id: string;
  nodes: LineageNode[];
  edges: { edge_id: string; edge_type: string; from_node_id: string; to_node_id: string; attributes: Record<string, string> }[];
  truncated: boolean;
}
export interface RecentAnswer { answer_id: string; question: string; status: string; created_at: string; }
export interface StoredAnswer {
  answer: {
    answer_id: string; question: string; answer_text: string; status: string; created_at: string;
    valid_at: string; known_at: string; modes: Record<string, string>;
  };
}
