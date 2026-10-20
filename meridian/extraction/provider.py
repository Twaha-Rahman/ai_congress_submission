"""Provider-neutral extraction interface and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from ..contracts.common import ErrorCode, Mode, SourceType, Subject
from ..contracts.extraction import ExtractionProposal, PolicyComparisonProposal


@dataclass(frozen=True)
class ClauseInput:
    clause_id: str
    page: int
    section: str | None
    text: str


@dataclass(frozen=True)
class ExtractionRequest:
    tenant_id: str
    region: str
    source_identity: str
    version_label: str
    source_type: SourceType
    subject: Subject
    authority: str
    content_sha256: str
    manifest_scope_summary: str
    clauses: Sequence[ClauseInput]
    mode: Mode
    prompt_version: str
    schema_version: str
    request_id: str
    #: Copied from the trusted manifest's ``permissions.hosted_model`` before any
    #: extraction run.  ``False`` forbids a hosted transport or cache persistence.
    hosted_model_allowed: bool = True
    #: Optional remaining stage budget; it never affects cache identity.
    model_budget_seconds: float | None = None


@dataclass
class ProviderResult:
    """Result of one model-stage attempt (live, cached or replay)."""

    mode: Mode
    provider: str
    proposal: ExtractionProposal | PolicyComparisonProposal | None = None
    error_code: ErrorCode | None = None
    error_detail: str | None = None
    model: str | None = None
    route: str | None = None
    attempts: int = 1
    latency_ms: int | None = None
    usage: dict[str, int] = field(default_factory=dict)
    status_code: int | None = None
    cache_key: str | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    raw_output_sha256: str | None = None
    raw_output: dict | None = None

    @property
    def ok(self) -> bool:
        return self.proposal is not None and self.error_code is None


class ExtractionProvider(Protocol):
    name: str

    def extract(self, request: ExtractionRequest) -> ProviderResult: ...


class ProviderPrerequisiteError(RuntimeError):
    """Raised when a provider cannot run at all (e.g. missing credentials)."""

    def __init__(self, error_code: ErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
