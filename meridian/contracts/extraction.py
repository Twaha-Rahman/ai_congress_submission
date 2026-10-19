"""Extraction proposals returned by the configured model adapter.

A proposal is *not* a backend record: it carries no trusted IDs, timestamps,
authority, permissions or supersession relationships.  Unknown fields are rejected,
so a model that tries to set authority/permissions fails schema validation instead of
influencing trusted metadata.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .common import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    Rule,
    Scope,
    StrictModel,
    Subject,
    UnitKind,
)


class EvidenceSpan(StrictModel):
    """Model-proposed evidence locator; offsets are re-resolved by the backend."""

    page: int | None = None
    section: str | None = None
    quote: str
    start_char: int | None = None
    end_char: int | None = None

    @model_validator(mode="after")
    def _offsets_paired(self) -> "EvidenceSpan":
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("start_char and end_char must be supplied together")
        if self.start_char is not None and self.start_char < 0:
            raise ValueError("start_char must be non-negative")
        if self.start_char is not None and self.end_char is not None:
            if self.end_char <= self.start_char:
                raise ValueError("end_char must be greater than start_char")
        return self


class ProposedRule(StrictModel):
    subject: Subject
    scope: Scope
    rule: Rule
    evidence: EvidenceSpan
    conditions: list[str] = Field(default_factory=list)
    unsupported_conditions: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    ambiguous_reason: str | None = None

    @model_validator(mode="after")
    def _conditions_consistent(self) -> "ProposedRule":
        if self.ambiguous and not self.ambiguous_reason:
            raise ValueError("ambiguous proposals must carry ambiguous_reason")
        return self


class UnsupportedCase(StrictModel):
    description: str
    reason_code: str
    quote: str | None = None


class ExtractionProposal(StrictModel):
    """Strict schema for a model extraction result."""

    schema_version: str = SCHEMA_VERSION
    source_language: str = "en"
    rules: list[ProposedRule]
    unsupported_cases: list[UnsupportedCase] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _subject_matches_unit(self) -> "ExtractionProposal":
        expected = {
            Subject.LOAN_APPROVAL: UnitKind.APPROVALS,
            Subject.RECORD_RETENTION: UnitKind.YEARS,
        }
        for rule in self.rules:
            if rule.rule.unit is not expected[rule.subject]:
                raise ValueError(
                    f"subject {rule.subject.value} requires unit "
                    f"{expected[rule.subject].value}, got {rule.rule.unit.value}"
                )
        return self


class VerifiedEvidence(StrictModel):
    """Evidence resolved against preserved parser text by the backend."""

    clause_id: str
    page: int
    section: str | None
    quote: str
    start_char: int
    end_char: int
    leaf_hash: str
    manifest_root: str


class ExtractionProvenance(StrictModel):
    """How a persisted claim was produced (never contains credentials)."""

    mode: str
    provider: str
    model: str | None
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION
    cache_key: str | None = None
    attempts: int = 1
    latency_ms: int | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    raw_output_sha256: str | None = None
    validator_version: str
    notes: list[str] = Field(default_factory=list)
