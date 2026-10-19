"""Trusted source manifest contracts.

The manifest is supplied by an authorised uploader (or by the gateway for federated
metadata) and is *not* derived from document instructions.  A model can never set
authority, permissions, sensitivity or supersession relationships.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .common import (
    Authority,
    OfficeRegion,
    Region,
    Scope,
    Sensitivity,
    SourceType,
    StrictModel,
    Subject,
    ensure_utc,
)


class SourcePermissions(StrictModel):
    """Separate egress decisions: inter-office export vs hosted-model processing."""

    office_export: bool
    hosted_model: bool


class SupersessionClaim(StrictModel):
    """An authorised, explicit replacement relationship declared in the manifest."""

    supersedes_source_identity: str
    supersedes_version_label: str
    replaced_clause_ids: list[str] = Field(min_length=1)
    replaced_scope: Scope
    effective_from: datetime

    @field_validator("effective_from")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class SourceManifest(StrictModel):
    """Immutable, trusted description of one source version."""

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    source_identity: str
    version_label: str
    source_type: SourceType
    subject: Subject
    authority: Authority
    policy_family: str
    scope: Scope
    effective_from: datetime | None
    effective_to: datetime | None
    publication_time: datetime | None
    sensitivity: Sensitivity
    permissions: SourcePermissions
    supersedes: SupersessionClaim | None = None
    declared_conditions: list[str] = Field(default_factory=list)
    rationale: str | None = None

    @field_validator("effective_from", "effective_to", "publication_time")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @field_validator("tenant_id", "source_identity", "version_label", "policy_family")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must be non-empty")
        if len(value) > 128:
            raise ValueError("value exceeds 128 characters")
        return value

    @model_validator(mode="after")
    def _consistency(self) -> "SourceManifest":
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_from >= self.effective_to
        ):
            raise ValueError("manifest effective_from must precede effective_to")
        if self.source_type is SourceType.PDF and self.publication_time is None:
            raise ValueError("PDF sources require a publication_time")
        if self.source_type is SourceType.SLACK and self.publication_time is None:
            raise ValueError("Slack sources require a message publication time")
        if self.supersedes is not None:
            if self.supersedes.supersedes_version_label == self.version_label and (
                self.supersedes.supersedes_source_identity == self.source_identity
            ):
                raise ValueError("a source version cannot supersede itself")
        return self

    def egress_metadata(self) -> dict[str, object]:
        """Non-sensitive manifest projection safe for audit logs."""

        return {
            "source_identity": self.source_identity,
            "version_label": self.version_label,
            "source_type": self.source_type.value,
            "subject": self.subject.value,
            "authority": self.authority.value,
            "policy_family": self.policy_family,
            "sensitivity": self.sensitivity.value,
            "office_export": self.permissions.office_export,
            "hosted_model": self.permissions.hosted_model,
            "region": self.region.value,
        }


class IngestRequestManifest(StrictModel):
    """Manifest envelope accepted by the ingestion endpoints (pre-validation)."""

    manifest: SourceManifest
    region: Region = Region.DHAKA
