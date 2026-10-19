"""Verification contracts: independent checks, never one aggregate green status."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .claims import ClaimRevision
from .common import CheckStatus, OfficeRegion, Region, StrictModel, ensure_utc
from .extraction import ExtractionProvenance
from .qa import AnswerPayload


class CheckResult(StrictModel):
    check: str
    status: CheckStatus
    reason: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)


class VerificationReport(StrictModel):
    schema_version: str = "1"
    tenant_id: str
    region: Region
    target_type: str
    target_id: str
    checks: list[CheckResult]
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    def summary(self) -> dict[str, str]:
        return {item.check: item.status.value for item in self.checks}

    def any_failed(self) -> bool:
        return any(item.status is CheckStatus.FAILED for item in self.checks)


class ClauseProof(StrictModel):
    """RFC 9162 inclusion proof for one committed clause leaf."""

    clause_id: str
    leaf_index: int
    tree_size: int
    leaf_hash: str
    siblings: list[str]
    merkle_root: str


class BundleClause(StrictModel):
    """Disclosed clause text carried inside a verification bundle."""

    clause_id: str
    page: int
    section: str | None
    start_char: int
    end_char: int
    text: str


class ManifestBundleEntry(StrictModel):
    source_id: str
    region: OfficeRegion
    source_identity: str
    version_label: str
    source_sha256: str
    merkle_root: str
    tree_size: int
    manifest_payload: dict
    manifest_hash: str
    signature: str
    key_id: str
    clause_proofs: list[ClauseProof] = Field(default_factory=list)
    clauses: list[BundleClause] = Field(default_factory=list)
    clauses_disclosed: bool = False
    sensitivity: str
    office_export: bool


class ClaimBundleEntry(StrictModel):
    claim: ClaimRevision
    claim_hash: str
    signature: str
    key_id: str
    extraction: ExtractionProvenance
    clause_proof: ClauseProof | None = None
    clause_disclosed: bool = False


class EvidenceBundle(StrictModel):
    """Self-contained verification bundle for one answer."""

    schema_version: str = "1"
    bundle_id: str
    tenant_id: str
    region: OfficeRegion
    answer: AnswerPayload
    answer_hash: str
    answer_signature: str
    answer_key_id: str
    manifests: list[ManifestBundleEntry] = Field(default_factory=list)
    claims: list[ClaimBundleEntry] = Field(default_factory=list)
    remote_references: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)
