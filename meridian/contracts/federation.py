"""Federation and egress-audit contracts.

Exports contain only allowlisted enums, numbers, opaque identifiers, commitments and
signatures.  Source quotes, titles, author/channel names, explanations and unknown
fields cannot be represented by these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from .common import (
    Authority,
    Currency,
    EgressChannel,
    EgressOutcome,
    LoanType,
    OfficeRegion,
    Product,
    RecordClass,
    Region,
    Rule,
    PolicyScope,
    Scope,
    StartingEvent,
    StrictModel,
    Subject,
    ensure_utc,
)


class LoanTarget(StrictModel):
    kind: Literal["loan"] = "loan"
    subject: Literal["loan_approval"] = "loan_approval"
    loan_type: LoanType
    currency: Currency
    origin_office: OfficeRegion
    amount_minor: int = Field(gt=0)


class RecordTarget(StrictModel):
    kind: Literal["record"] = "record"
    subject: Literal["record_retention"] = "record_retention"
    record_class: RecordClass
    origin_office: OfficeRegion
    processing_office: OfficeRegion
    product: Product
    starting_event: StartingEvent


FederationTarget = Annotated[Union[LoanTarget, RecordTarget], Field(discriminator="kind")]


class FederationSubquery(StrictModel):
    """Typed subquery accepted by an office's federation endpoint.

    ``target_fingerprint`` binds the request to the exact canonical target when the
    gateway supplies it; the office rejects a fingerprint that does not match its own
    canonicalisation of ``target``.
    """

    request_id: str
    subject: Subject
    target: FederationTarget
    valid_at: datetime
    known_at: datetime
    target_fingerprint: str | None = None
    egress_policy: Literal["structured_claims_only"] = "structured_claims_only"

    @field_validator("valid_at", "known_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _subject_matches_target(self) -> "FederationSubquery":
        if self.subject.value != self.target.subject:
            raise ValueError("subquery subject must match the typed target")
        return self


class ExportClaim(StrictModel):
    """Allowlisted projection of one accepted claim revision."""

    claim_revision_id: str
    claim_id: str
    subject: Subject
    scope: Scope
    rule: Rule
    authority: Authority
    policy_family: str
    valid_from: datetime | None
    valid_to: datetime | None
    system_from: datetime
    system_to: datetime | None
    claim_payload_hash: str
    manifest_root: str
    source_ref: str
    source_kind: str

    @model_validator(mode="after")
    def _numeric_export_only(self) -> "ExportClaim":
        if self.subject is Subject.GENERAL_POLICY or isinstance(self.scope, PolicyScope):
            raise ValueError("general policy text is office-local and cannot use numeric federation exports")
        return self

    @field_validator("valid_from", "valid_to", "system_from", "system_to")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class FederationExportPayload(StrictModel):
    schema_version: str = "1"
    tenant_id: str
    origin_region: OfficeRegion
    request_id: str
    subject: Subject
    valid_at: datetime
    known_at: datetime
    #: Canonical hash of the requested typed target.  The gateway verifies that it
    #: matches the target it asked for, so a signed export cannot be replayed for a
    #: different loan amount or record scope.
    target_fingerprint: str
    claims: list[ExportClaim]
    commitments: list[str]
    withheld_restricted: int = 0
    not_checked: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    complete: bool = True
    signer_key_id: str
    generated_at: datetime

    @field_validator("valid_at", "known_at", "generated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class FederationExport(StrictModel):
    payload: FederationExportPayload
    payload_hash: str
    signature: str
    key_id: str


class ModelCallMetadata(StrictModel):
    """Non-secret provider metadata recorded for hosted-model egress."""

    mode: str
    provider: str
    route: str | None = None
    model: str | None = None
    prompt_version: str
    schema_version: str
    attempts: int = 1
    latency_ms: int | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    status_code: int | None = None
    outcome: str | None = None


class EgressEvent(StrictModel):
    """Audited serialization of one outbound transport payload."""

    schema_version: str = "1"
    event_id: str
    tenant_id: str
    region: Region
    channel: EgressChannel
    destination: str
    request_id: str
    payload_type: str
    payload_bytes: int
    payload_sha256: str
    raw_source_bytes: int
    outcome: EgressOutcome
    error_code: str | None = None
    model_metadata: ModelCallMetadata | None = None
    created_at: datetime
    prev_hash: str | None = None

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class EgressSummary(StrictModel):
    """Counters derived from audited egress events, never from a constant."""

    region: Region
    office_to_office_events: int
    office_to_office_bytes: int
    hosted_model_events: int
    hosted_model_request_bytes: int
    raw_source_text_bytes_between_offices: int
    blocked_exports: int
    failed_transfers: int
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)
