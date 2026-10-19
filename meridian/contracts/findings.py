"""Findings, signed finding snapshots and reviewer audit events."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from .common import (
    ExplanationCode,
    FindingType,
    OfficeRegion,
    ReviewAction,
    ReviewState,
    Scope,
    Severity,
    StrictModel,
    Subject,
    TimeInterval,
    ensure_utc,
)


class FindingEvidenceRef(StrictModel):
    """Evidence references for a finding; quotes stay local to the office store."""

    claim_revision_id: str
    clause_id: str
    source_id: str
    page: int
    section: str | None
    quote: str
    start_char: int
    end_char: int
    manifest_root: str


class FindingPayload(StrictModel):
    """Immutable signed snapshot of one finding."""

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    finding_id: str
    finding_key: str
    finding_type: FindingType
    severity: Severity
    explanation_code: ExplanationCode
    subject: Subject
    claim_revision_ids: list[str]
    affected_scope: Scope
    affected_valid_interval: TimeInterval
    authority_basis: str
    evidence: list[FindingEvidenceRef]
    staleness_link_revision_ids: list[str] = Field(default_factory=list)
    detail: dict[str, str] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ReviewEvent(StrictModel):
    """Append-only reviewer audit event; never deletes evidence."""

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    event_id: str
    finding_id: str
    snapshot_id: str | None
    actor: str
    action: ReviewAction
    reason: str
    prior_state: ReviewState
    new_state: ReviewState
    referenced_revision_ids: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class FindingRecord(StrictModel):
    """Stored finding view: signed snapshot plus mutable review state."""

    payload: FindingPayload
    snapshot_id: str
    snapshot_hash: str
    signature: str
    key_id: str
    review_state: ReviewState = ReviewState.OPEN
    superseded_by_snapshot_id: str | None = None


class ComparisonResult(StrictModel):
    """Result of comparing two normalized claims (pure engine output)."""

    finding_type: FindingType
    severity: Severity
    explanation_code: ExplanationCode
    left_revision_id: str
    right_revision_id: str
    subject: Subject
    affected_scope: Scope | None = None
    affected_valid_interval: TimeInterval | None = None
    authority_basis: str | None = None
    staleness_link_revision_ids: list[str] = Field(default_factory=list)
    detail: dict[str, str] = Field(default_factory=dict)
    alert: bool = False

    def claim_revision_ids(self) -> list[str]:
        return [self.left_revision_id, self.right_revision_id]
