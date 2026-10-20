"""Accepted claim revisions and append-only revision closures."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .common import (
    Authority,
    ClaimOrigin,
    ClaimStatus,
    ClosureKind,
    OfficeRegion,
    PolicyRule,
    PolicyScope,
    Rule,
    Scope,
    StrictModel,
    Subject,
    ensure_utc,
)
from .extraction import EvidenceSpan, ExtractionProvenance, VerifiedEvidence


class ClaimRevision(StrictModel):
    """Immutable signed payload of one accepted claim revision.

    ``system_from`` is the *actual* backend receipt time of the source version that
    produced this revision; ``system_to`` is deliberately absent — it is derived from
    append-only closure events and never written into signed content.
    """

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    claim_id: str
    revision_id: str
    subject: Subject
    scope: Scope
    rule: Rule | PolicyRule
    authority: Authority
    policy_family: str
    source_id: str
    source_identity: str
    source_version_label: str
    source_clause_id: str
    valid_from: datetime | None
    valid_to: datetime | None
    system_from: datetime
    evidence: VerifiedEvidence
    extraction: ExtractionProvenance
    status: ClaimStatus = ClaimStatus.ACCEPTED
    origin: ClaimOrigin = ClaimOrigin.LOCAL

    @field_validator("valid_from", "valid_to", "system_from")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _ordered(self) -> "ClaimRevision":
        general = self.subject is Subject.GENERAL_POLICY
        if general != isinstance(self.rule, PolicyRule) or general != isinstance(self.scope, PolicyScope):
            raise ValueError("general_policy requires a policy rule and policy scope")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from >= self.valid_to
        ):
            raise ValueError("valid_from must precede valid_to")
        return self


class ClaimRevisionRecord(StrictModel):
    """Stored view: signed payload plus derived, non-signed bookkeeping."""

    payload: ClaimRevision
    payload_hash: str
    signature: str
    key_id: str
    origin: ClaimOrigin = ClaimOrigin.LOCAL
    remote_request_id: str | None = None
    system_to: datetime | None = None
    closed_by_closure_id: str | None = None
    review_state: str | None = None


class RevisionClosure(StrictModel):
    """Append-only signed event ending a revision's system interval."""

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    closure_id: str
    revision_id: str
    closure_kind: ClosureKind
    system_to: datetime
    policy_family: str
    superseding_source_id: str | None = None
    replaced_clause_ids: list[str] = Field(default_factory=list)
    replacement_revision_ids: list[str] = Field(default_factory=list)
    carried_forward_revision_ids: list[str] = Field(default_factory=list)
    effective_from: datetime | None = None
    created_at: datetime

    @field_validator("system_to", "effective_from", "created_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class ClaimWithdraw(StrictModel):
    """Marker payload used when an accepted claim must be re-classified."""

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    revision_id: str
    status: ClaimStatus
    reason_code: str
    detail: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


__all__ = [
    "ClaimRevision",
    "ClaimRevisionRecord",
    "RevisionClosure",
    "ClaimWithdraw",
    "EvidenceSpan",
]
