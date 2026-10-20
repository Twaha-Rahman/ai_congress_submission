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
  kind: "loan" | "record";
  origin_office: string;
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
  rule: { kind: string; value: string | number; unit: string };
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
