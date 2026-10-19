"""SQL migrations for the office store.

Schema version 1 is the complete MVP schema; later versions are appended, never
edited, because office databases are durable across demo runs.
"""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    version_label TEXT NOT NULL,
    source_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    policy_family TEXT NOT NULL,
    authority TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    office_export INTEGER NOT NULL,
    hosted_model INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    tree_size INTEGER NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_payload_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    manifest_signature TEXT NOT NULL,
    manifest_key_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    contract_schema_version TEXT NOT NULL,
    publication_time TEXT,
    effective_from TEXT,
    effective_to TEXT,
    status TEXT NOT NULL,
    supersedes_json TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE (tenant_id, region, source_identity, version_label)
);
CREATE INDEX IF NOT EXISTS idx_sources_identity
    ON sources (tenant_id, region, source_identity);

CREATE TABLE IF NOT EXISTS clauses (
    clause_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources (source_id),
    clause_index INTEGER NOT NULL,
    page INTEGER NOT NULL,
    section TEXT,
    text TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    leaf_hash TEXT NOT NULL,
    restricted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_clauses_source ON clauses (source_id);

CREATE VIRTUAL TABLE IF NOT EXISTS clause_fts USING fts5(
    text,
    clause_id UNINDEXED,
    source_id UNINDEXED,
    tenant_id UNINDEXED,
    region UNINDEXED,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS claim_revisions (
    revision_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    authority TEXT NOT NULL,
    policy_family TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    system_from TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_clause_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    extraction_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    key_id TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'local',
    remote_request_id TEXT,
    status TEXT NOT NULL,
    review_state TEXT,
    closed_by_closure_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_subject
    ON claim_revisions (tenant_id, region, subject);
CREATE INDEX IF NOT EXISTS idx_claim_source ON claim_revisions (source_id);
CREATE INDEX IF NOT EXISTS idx_claim_policy_family
    ON claim_revisions (tenant_id, region, policy_family);

CREATE TABLE IF NOT EXISTS revision_closures (
    closure_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    revision_id TEXT NOT NULL UNIQUE,
    closure_kind TEXT NOT NULL,
    system_to TEXT NOT NULL,
    policy_family TEXT NOT NULL,
    superseding_source_id TEXT,
    replaced_clause_ids_json TEXT NOT NULL DEFAULT '[]',
    replacement_revision_ids_json TEXT NOT NULL DEFAULT '[]',
    carried_forward_revision_ids_json TEXT NOT NULL DEFAULT '[]',
    effective_from TEXT,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    key_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_closure_source ON revision_closures (superseding_source_id);

CREATE TABLE IF NOT EXISTS claim_reviews (
    review_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    source_id TEXT NOT NULL,
    subject TEXT,
    reason_code TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reviews_source ON claim_reviews (source_id);

CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    finding_key TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    subject TEXT NOT NULL,
    alert INTEGER NOT NULL,
    claim_revision_ids_json TEXT NOT NULL,
    current_snapshot_id TEXT NOT NULL,
    review_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, region, finding_key)
);
CREATE INDEX IF NOT EXISTS idx_findings_type ON findings (tenant_id, region, finding_type);

CREATE TABLE IF NOT EXISTS finding_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    finding_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    key_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_finding ON finding_snapshots (finding_id);

CREATE TABLE IF NOT EXISTS review_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    snapshot_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    prior_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    referenced_revision_ids_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    key_id TEXT NOT NULL,
    prev_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    answer_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    status TEXT NOT NULL,
    question TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    answer_text_hash TEXT NOT NULL,
    valid_at TEXT NOT NULL,
    known_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    key_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    stage_modes_json TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_code TEXT,
    review_reason TEXT,
    source_id TEXT,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, updated_at);

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    node_type TEXT NOT NULL,
    label TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    restricted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edges (
    edge_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (tenant_id, region, edge_type, from_node_id, to_node_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges (from_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges (to_node_id);

CREATE TABLE IF NOT EXISTS egress_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    channel TEXT NOT NULL,
    destination TEXT NOT NULL,
    request_id TEXT NOT NULL,
    payload_type TEXT NOT NULL,
    payload_bytes INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    raw_source_bytes INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    error_code TEXT,
    model_metadata_json TEXT,
    prev_hash TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_egress_channel ON egress_events (channel, created_at);

CREATE TABLE IF NOT EXISTS model_calls (
    call_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    job_id TEXT,
    source_id TEXT,
    mode TEXT NOT NULL,
    provider TEXT NOT NULL,
    route TEXT,
    model TEXT,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    latency_ms INTEGER,
    usage_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    error_code TEXT,
    cache_key TEXT,
    raw_output_sha256 TEXT,
    created_at TEXT NOT NULL
);
""",
    ),
    (
        2,
        """
CREATE TABLE IF NOT EXISTS remote_claims (
    remote_claim_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    origin_region TEXT NOT NULL,
    request_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    authority TEXT NOT NULL,
    policy_family TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    system_from TEXT,
    system_to TEXT,
    source_ref TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    claim_payload_hash TEXT NOT NULL,
    manifest_root TEXT NOT NULL,
    export_payload_hash TEXT NOT NULL,
    export_signature TEXT NOT NULL,
    export_key_id TEXT NOT NULL,
    not_checked_json TEXT NOT NULL DEFAULT '[]',
    received_at TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (tenant_id, region, origin_region, revision_id, export_payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_remote_claims_subject
    ON remote_claims (tenant_id, region, subject);
""",
    ),
    (
        3,
        """
-- Recipient-side record of each verified export snapshot.  Remote claims are only
-- eligible for a query when they belong to the exact snapshot selected for that
-- query, so history can never leak into a current comparison merely because it was
-- imported earlier.
CREATE TABLE IF NOT EXISTS remote_export_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    region TEXT NOT NULL,
    origin_region TEXT NOT NULL,
    request_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL DEFAULT '',
    valid_at TEXT,
    known_at TEXT,
    export_payload_hash TEXT NOT NULL,
    export_signature TEXT NOT NULL,
    export_key_id TEXT NOT NULL,
    complete INTEGER NOT NULL DEFAULT 1,
    claim_revision_ids_json TEXT NOT NULL DEFAULT '[]',
    claim_payload_hashes_json TEXT NOT NULL DEFAULT '[]',
    received_at TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (tenant_id, region, export_payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_remote_snapshots_subject
    ON remote_export_snapshots (tenant_id, region, subject, origin_region, imported_at);
ALTER TABLE remote_claims ADD COLUMN snapshot_id TEXT;

-- Membership is many-to-many: an unchanged remote claim re-exported in a later
-- complete snapshot remains eligible, while claims dropped from the latest export
-- disappear from current answers.
CREATE TABLE IF NOT EXISTS remote_snapshot_claims (
    snapshot_id TEXT NOT NULL,
    remote_claim_id TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, remote_claim_id)
);
""",
    ),
    (
        4,
        """
-- Temporal resolution moments let historical queries reproduce whether a pending
-- replacement was open at their requested knowledge cutoff.
ALTER TABLE claim_reviews ADD COLUMN resolved_at TEXT;
""",
    ),
]
