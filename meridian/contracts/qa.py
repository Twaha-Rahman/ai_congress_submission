"""Query, answer, citation and lineage contracts."""

from __future__ import annotations

from datetime import datetime
import json

from pydantic import Field, field_validator, model_validator

from .common import (
    ANSWER_TEMPLATE_VERSION,
    AnswerStatus,
    Currency,
    LoanType,
    Mode,
    OfficeRegion,
    Product,
    QueryWarningCode,
    RecordClass,
    Region,
    StartingEvent,
    StrictModel,
    Subject,
    TimeInterval,
    ensure_utc,
    utc_now,
)


class TargetFacts(StrictModel):
    """Explicit typed target facts for a supported query."""

    subject: Subject
    amount_minor: int | None = None
    currency: Currency | None = None
    loan_type: LoanType | None = None
    record_class: RecordClass | None = None
    origin_office: OfficeRegion | None = None
    processing_office: OfficeRegion | None = None
    product: Product | None = None
    starting_event: StartingEvent | None = None

    @model_validator(mode="after")
    def _required_fields(self) -> "TargetFacts":
        if self.subject is Subject.GENERAL_POLICY:
            if any(value is not None for key, value in self.model_dump().items() if key != "subject"):
                raise ValueError("general questions use source passages, not typed numeric target facts")
            return self
        if self.subject is Subject.LOAN_APPROVAL:
            if self.amount_minor is None:
                raise ValueError("loan_approval queries require amount_minor")
            if self.amount_minor <= 0:
                raise ValueError("loan amount must be positive")
            if self.currency is None:
                raise ValueError("loan_approval queries require currency")
            if self.loan_type is None:
                raise ValueError("loan_approval queries require loan_type")
            if self.origin_office is None:
                raise ValueError("loan_approval queries require origin_office")
        else:
            if self.record_class is None or self.starting_event is None:
                raise ValueError("record_retention queries require record_class and starting_event")
        return self


class QueryRequest(StrictModel):
    """Public query body.  Tenant and office always come from server context."""

    question: str
    target: TargetFacts = Field(default_factory=lambda: TargetFacts(subject=Subject.GENERAL_POLICY))
    valid_at: datetime = Field(default_factory=utc_now)
    known_at: datetime | None = None
    mode: Mode | None = None
    #: Exact recipient-side export snapshots supplied by the gateway.  The office
    #: only uses these when they are the latest complete snapshot known at
    #: ``known_at``; an older or future snapshot is ignored rather than replayed.
    remote_snapshot_ids: list[str] = Field(default_factory=list)
    #: Source-office knowledge cutoff represented by the remote export. This is
    #: distinct from recipient ``known_at`` (the time the recipient knew the import).
    remote_source_known_at: datetime | None = None
    #: Gateway comparisons set this when omission of the expected remote snapshot
    #: would make a local-only result misleading.
    remote_snapshot_required: bool = False
    source_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _general_controls(self) -> "QueryRequest":
        if self.source_ids and self.target.subject is not Subject.GENERAL_POLICY:
            raise ValueError("source filters apply to general source questions only")
        if self.target.subject is Subject.GENERAL_POLICY and (
            self.remote_snapshot_ids or self.remote_source_known_at or self.remote_snapshot_required
        ):
            raise ValueError("general questions are local; gateway snapshot controls are unsupported")
        return self

    @field_validator("valid_at", "known_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @field_validator("remote_source_known_at")
    @classmethod
    def _remote_source_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @field_validator("question")
    @classmethod
    def _question_bounded(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must be non-empty")
        if len(value) > 500:
            raise ValueError("question exceeds 500 characters")
        return value


class Citation(StrictModel):
    """A factual-statement citation bound to a claim revision and its evidence."""

    statement_id: str
    claim_revision_id: str | None
    claim_id: str | None
    source_id: str
    source_identity: str
    source_version_label: str
    clause_id: str
    manifest_root: str
    claim_payload_hash: str | None
    authority: str
    page: int
    section: str | None
    quote: str | None
    start_char: int
    end_char: int
    restricted: bool = False
    remote: bool = False


class AnswerWarning(StrictModel):
    code: QueryWarningCode
    message: str
    claim_revision_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)


class GoverningFact(StrictModel):
    claim_revision_id: str
    claim_id: str
    authority: str
    policy_family: str
    rule_summary: str
    scope_summary: str
    valid_interval: TimeInterval


class AnswerPayload(StrictModel):
    """Signed answer record; ``answer_text`` is bound by its hash."""

    schema_version: str = "1"
    tenant_id: str
    region: Region
    answer_id: str
    status: AnswerStatus
    question: str
    query_hash: str
    answer_text: str
    answer_text_hash: str
    target: TargetFacts
    valid_at: datetime
    known_at: datetime
    governing_facts: list[GoverningFact]
    citations: list[Citation]
    warnings: list[AnswerWarning]
    modes: dict[str, Mode]
    template_version: str = ANSWER_TEMPLATE_VERSION
    signer_key_id: str
    model_metadata: dict[str, str] = Field(default_factory=dict)
    cited_claim_payload_hashes: list[str]
    cited_manifest_roots: list[str]
    partial_reasons: list[str] = Field(default_factory=list)
    created_at: datetime

    def local_source_ids(self) -> set[str]:
        """Authorize model context as well as quoted passages on every later read."""
        result = {citation.source_id for citation in self.citations if not citation.remote}
        if self.target.subject is Subject.GENERAL_POLICY:
            for key in ("source_ids", "visibility_source_ids"):
                values = json.loads(self.model_metadata.get(key, "[]"))
                if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                    raise ValueError("invalid answer source visibility metadata")
                result.update(values)
        return result

    @field_validator("valid_at", "known_at", "created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class LineageNode(StrictModel):
    node_id: str
    node_type: str
    label: str
    attributes: dict[str, str] = Field(default_factory=dict)
    restricted: bool = False


class LineageEdge(StrictModel):
    edge_id: str
    edge_type: str
    from_node_id: str
    to_node_id: str
    attributes: dict[str, str] = Field(default_factory=dict)


class LineageGraph(StrictModel):
    root_id: str
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    truncated: bool = False


class AnswerRecord(StrictModel):
    payload: AnswerPayload
    payload_hash: str
    signature: str
    key_id: str
    answer_text_hash: str
    lineage: LineageGraph | None = None
