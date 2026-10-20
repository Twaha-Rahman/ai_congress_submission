"""Contract-level shared primitives: strict models, enums, decimal and amount helpers.

All trust-boundary models forbid unknown fields.  Nothing in this module performs
authorisation or I/O.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1"
PARSER_VERSION = "pymupdf-clause-v1"
PROMPT_VERSION = "extract-v1"
VALIDATOR_VERSION = "validate-v1"
CANONICAL_ENCODING_VERSION = "canon-1"
MERKLE_CONVENTION = "rfc9162-sha256"
ANSWER_TEMPLATE_VERSION = "deterministic-template-v1"
BUILD_VERSION = "0.1.0-mvp"

#: Money is integer minor units (USD cents).  10**15 cents = USD 10 trillion.
MAX_AMOUNT_MINOR = 10**15
MAX_RETENTION_YEARS = Decimal(200)


class StrictModel(BaseModel):
    """Base for every contract: unknown fields rejected at the boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class Region(str, Enum):
    DHAKA = "DHAKA"
    FRANKFURT = "FRANKFURT"
    GATEWAY = "GATEWAY"


class OfficeRegion(str, Enum):
    DHAKA = "DHAKA"
    FRANKFURT = "FRANKFURT"


class Subject(str, Enum):
    LOAN_APPROVAL = "loan_approval"
    RECORD_RETENTION = "record_retention"
    GENERAL_POLICY = "general_policy"


class ScopeKind(str, Enum):
    LOAN = "loan"
    RECORD = "record"


class LoanType(str, Enum):
    BUSINESS = "business"


class Currency(str, Enum):
    USD = "USD"


class RecordClass(str, Enum):
    LOAN_RECORDS = "loan_records"


class Product(str, Enum):
    MTF_CROSS_OFFICE = "MTF_CROSS_OFFICE"


class StartingEvent(str, Enum):
    LOAN_CLOSURE = "loan_closure"


class RuleKind(str, Enum):
    REQUIRED_MINIMUM = "required_minimum"
    MAXIMUM_ALLOWED = "maximum_allowed"
    EXACTLY_REQUIRED = "exactly_required"
    ADVISED_SUFFICIENT = "advised_sufficient"
    OPERATING_EXACT = "operating_exact"


class UnitKind(str, Enum):
    APPROVALS = "approvals"
    YEARS = "years"


class Authority(str, Enum):
    POLICY = "policy"
    PROCEDURE = "procedure"
    INFORMAL = "informal"


class Sensitivity(str, Enum):
    DEMO_SHAREABLE = "demo_shareable"
    RESTRICTED = "restricted"


class SourceType(str, Enum):
    PDF = "pdf"
    SLACK = "slack"


class Mode(str, Enum):
    LIVE = "live"
    CACHED = "cached"
    REPLAY = "replay"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ClaimStatus(str, Enum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class FindingType(str, Enum):
    CONTRADICTION = "contradiction"
    STALE_GUIDANCE = "stale_guidance"
    INCORRECT_GUIDANCE = "incorrect_guidance"
    COMPLIANCE_GAP = "compliance_gap"
    COMPATIBLE_DIFFERENCE = "compatible_difference"
    SUPERSESSION = "supersession"
    NOT_COMPARABLE = "not_comparable"
    NEEDS_REVIEW = "needs_review"


class Severity(str, Enum):
    HIGH = "high"
    REVIEW = "review"
    INFO = "info"


class ReviewState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewAction(str, Enum):
    ACKNOWLEDGE = "acknowledge"
    RESOLVE = "resolve"
    DISMISS = "dismiss"


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    NEEDS_REVIEW = "needs_review"
    ABSTAINED = "abstained"
    PARTIAL = "partial"


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_CHECKED = "not_checked"


class ClosureKind(str, Enum):
    SUPERSESSION = "supersession"
    RETIREMENT = "retirement"


class EgressChannel(str, Enum):
    OFFICE_TO_OFFICE = "office_to_office"
    HOSTED_MODEL = "hosted_model"


class EgressOutcome(str, Enum):
    DELIVERED = "delivered"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


class ClaimOrigin(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class ErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_CONTENT = "unsupported_content"
    FORBIDDEN = "forbidden"
    UNAUTHENTICATED = "unauthenticated"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTION_NEEDS_REVIEW = "extraction_needs_review"
    CACHE_MISS = "cache_miss"
    REPLAY_FIXTURE_MISSING = "replay_fixture_missing"
    MISSING_CREDENTIALS = "missing_credentials"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_TIMEOUT = "provider_timeout"
    SCHEMA_VIOLATION = "schema_violation"
    HALLUCINATED_EVIDENCE = "hallucinated_evidence"
    MISSING_POLICY = "missing_policy"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    OFFICE_UNAVAILABLE = "office_unavailable"
    VERIFICATION_FAILED = "verification_failed"
    VERSION_PAYLOAD_MISMATCH = "version_payload_mismatch"
    EGRESS_DENIED = "egress_denied"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    INVALID_AMOUNT = "invalid_amount"
    UNSUPPORTED_REPLACEMENT = "unsupported_replacement"
    INTERNAL_ERROR = "internal_error"


class ExplanationCode(str, Enum):
    REQUIREMENT_SETS_DISJOINT = "requirement_sets_disjoint"
    ADVICE_VIOLATES_REQUIREMENT_STALE = "advice_violates_requirement_stale"
    ADVICE_VIOLATES_REQUIREMENT = "advice_violates_requirement"
    OPERATING_BELOW_MINIMUM = "operating_below_minimum"
    OPERATING_ABOVE_MAXIMUM = "operating_above_maximum"
    REQUIREMENTS_OVERLAP = "requirements_overlap"
    REQUIREMENTS_IDENTICAL = "requirements_identical"
    EXPLICIT_SCOPE_REPLACEMENT = "explicit_scope_replacement"
    NO_SCOPE_OVERLAP = "no_scope_overlap"
    NO_TIME_OVERLAP = "no_time_overlap"
    SUBJECT_MISMATCH = "subject_mismatch"
    MISSING_CONDITION = "missing_condition"
    UNKNOWN_APPLICABILITY = "unknown_applicability"
    UNSUPPORTED_REPLACEMENT = "unsupported_replacement"
    AMBIGUOUS_AUTHORITY = "ambiguous_authority"
    ADVICE_ADEQUATE = "advice_adequate"
    UNIT_MISMATCH = "unit_mismatch"
    STARTING_EVENT_MISMATCH = "starting_event_mismatch"
    REVISION_NOT_CURRENT = "revision_not_current"
    INCOMPARABLE_RULE_KINDS = "incomparable_rule_kinds"
    SEMANTIC_CONFLICT = "semantic_conflict"
    SEMANTIC_UNCERTAINTY = "semantic_uncertainty"


class QueryWarningCode(str, Enum):
    STALE_GUIDANCE = "stale_guidance_present"
    STALE_GUIDANCE_COVERED = "stale_guidance_partly_covers_target"
    ONLY_INFORMAL_GUIDANCE = "only_informal_guidance"
    RESTRICTED_EVIDENCE_WITHHELD = "restricted_evidence_withheld"
    REMOTE_CLAUSE_NOT_CHECKED = "remote_clause_not_checked"
    INCOMPLETE_INGESTION = "incomplete_ingestion"
    OFFICE_UNAVAILABLE = "office_unavailable"
    CACHE_MISS = "cache_miss"
    GENERATED_PROSE_REMOVED = "generated_prose_removed"
    KNOWLEDGE_SNAPSHOT = "knowledge_snapshot_differs_from_effective_history"
    PENDING_REPLACEMENT = "pending_replacement"
    REVIEW_REQUIRED = "review_required"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must carry a timezone offset")
    return value.astimezone(timezone.utc)


#: Annotated datetime type that always normalises to UTC.
UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]


def canonical_datetime(value: datetime) -> str:
    """Deterministic UTC ISO-8601 with microseconds only when non-zero."""

    dt = ensure_utc(value)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def normalize_decimal_string(raw: str | int | Decimal) -> str:
    """Normalized decimal string: no exponent, no trailing zeros, no ``+``.

    ``"5.0"``, ``"05"`` and ``Decimal("5")`` all normalize to ``"5"``; ``"0.500"``
    becomes ``"0.5"``.  Only finite values are accepted.
    """

    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"not a decimal value: {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"non-finite decimal rejected: {raw!r}")
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return str(int(normalized))
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


_NUMBER_FORMS = re.compile(
    r"""(?x)
    (?P<value>
        (?P<k>\d+(?:\.\d+)?)\s*[kK]\b            # 50k / 12.5k
      | \d{1,3}(?:,\d{3})+(?:\.\d+)?             # 50,000 / 1,000.50
      | \d+(?:\.\d+)?                            # 50000 / 25000.01
      | (?P<word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)
    )
    """
)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def parse_number_token(token: str) -> Decimal | None:
    """Parse one supported numeric surface form (``50k``, ``50,000``, ``five``)."""

    match = _NUMBER_FORMS.fullmatch(token.strip())
    if match is None:
        return None
    if match.group("word"):
        return Decimal(_NUMBER_WORDS[match.group("word")])
    raw = match.group("k") or match.group("value")
    value = Decimal(raw.replace(",", ""))
    if match.group("k") is not None:
        value *= 1000
    return value


def find_number_tokens(text: str) -> list[tuple[str, Decimal, int, int]]:
    """Return ``(token, value, start, end)`` for every supported number in ``text``."""

    out: list[tuple[str, Decimal, int, int]] = []
    for match in _NUMBER_FORMS.finditer(text):
        token = match.group(0)
        value = parse_number_token(token)
        if value is not None:
            out.append((token, value, match.start(), match.end()))
    return out


def usd_minor_from_text(text: str) -> Decimal | None:
    """Interpret a textual USD amount as minor units (cents)."""

    tokens = find_number_tokens(text)
    if len(tokens) != 1:
        return None
    return tokens[0][1] * 100


class AmountInterval(StrictModel):
    """Discrete integer amount interval in minor units (cents).

    ``lower``/``upper`` are inclusive or exclusive according to the flags; ``None``
    means unbounded on that side.  Bounds are never negative.
    """

    lower: int | None = None
    lower_inclusive: bool = True
    upper: int | None = None
    upper_inclusive: bool = False

    @field_validator("lower", "upper")
    @classmethod
    def _bounds_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("amount bounds must be non-negative")
        if value is not None and value > MAX_AMOUNT_MINOR:
            raise ValueError("amount bound exceeds supported range")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> "AmountInterval":
        if self.lower is None and self.upper is None:
            raise ValueError("amount interval must be bounded on at least one side")
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                raise ValueError("amount interval lower bound exceeds upper bound")
            if self.lower == self.upper and not (self.lower_inclusive and self.upper_inclusive):
                raise ValueError("empty amount interval")
        return self

    def contains(self, amount_minor: int) -> bool:
        if self.lower is not None:
            if amount_minor < self.lower:
                return False
            if amount_minor == self.lower and not self.lower_inclusive:
                return False
        if self.upper is not None:
            if amount_minor > self.upper:
                return False
            if amount_minor == self.upper and not self.upper_inclusive:
                return False
        return True

    def is_empty(self) -> bool:
        if self.lower is None or self.upper is None:
            return False
        if self.lower < self.upper:
            return False
        return not (self.lower_inclusive and self.upper_inclusive)


class TimeInterval(StrictModel):
    """Half-open interval ``[start, end)``; ``None`` end means unbounded."""

    start: datetime | None
    end: datetime | None

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @model_validator(mode="after")
    def _ordered(self) -> "TimeInterval":
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("time interval start must precede end")
        return self

    def contains(self, moment: datetime) -> bool:
        moment = ensure_utc(moment)
        if self.start is not None and moment < self.start:
            return False
        if self.end is not None and moment >= self.end:
            return False
        return True

    def overlaps(self, other: "TimeInterval") -> bool:
        a_start = self.start
        a_end = self.end
        b_start = other.start
        b_end = other.end
        if a_end is not None and b_start is not None and a_end <= b_start:
            return False
        if b_end is not None and a_start is not None and b_end <= a_start:
            return False
        return True


class AmountScope(StrictModel):
    """Loan scope: currency, loan type, originating office and amount band."""

    kind: Literal["loan"] = "loan"
    loan_type: LoanType
    currency: Currency
    origin_office: OfficeRegion
    amount_minor: AmountInterval


class RecordScope(StrictModel):
    """Record scope: record class, offices, product and retention starting event."""

    kind: Literal["record"] = "record"
    record_class: RecordClass
    origin_office: OfficeRegion
    processing_office: OfficeRegion
    product: Product
    starting_event: StartingEvent


class PolicyScope(StrictModel):
    """Uploader-assigned applicability; textual applicability stays in the rule.

    Attributes are explicit categorical boundaries (e.g. jurisdiction/team), not
    model-inferred facts. Missing keys mean unspecified, never known equality.
    """

    kind: Literal["policy"] = "policy"
    description: str = Field(min_length=1, max_length=1000)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy scope description must not be blank")
        return value

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not k.strip() or not v.strip() or len(k) > 128 or len(v) > 500
               for k, v in value.items()):
            raise ValueError("scope attributes must be nonempty bounded strings")
        return value


Scope = Annotated[Union[AmountScope, RecordScope, PolicyScope], Field(discriminator="kind")]


class PolicyRule(StrictModel):
    """Domain-independent statement. All text fields are source excerpts.

    This is evidence-grounded extraction, not a proof that the model understood
    the obligation correctly. Semantic findings always require human review.
    """

    kind: Literal["policy_statement"] = "policy_statement"
    statement: str = Field(min_length=1, max_length=12000)
    modality: Literal["required", "prohibited", "permitted", "advice", "assertion"]
    actor: str | None = Field(default=None, min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=2000)
    object: str | None = Field(default=None, min_length=1, max_length=2000)
    constraint: str | None = Field(default=None, min_length=1, max_length=2000)
    applies_to: list[str] = Field(default_factory=list, max_length=30)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    exceptions: list[str] = Field(default_factory=list, max_length=30)


class Rule(StrictModel):
    """A normalized rule.

    ``value`` is an ``int`` for approval counts and a normalized decimal *string*
    for retention years; ``unit`` decides which representation is required.
    """

    kind: RuleKind
    unit: UnitKind
    value: int | str

    @model_validator(mode="after")
    def _check_value(self) -> "Rule":
        if self.unit is UnitKind.APPROVALS:
            if not isinstance(self.value, int) or isinstance(self.value, bool):
                raise ValueError("approval values must be integers")
            if self.value < 1:
                raise ValueError("approval values must be positive")
            if self.value > 1000:
                raise ValueError("approval value out of supported range")
            if self.kind is RuleKind.OPERATING_EXACT:
                raise ValueError("operating_exact is a retention rule kind")
        else:
            if not isinstance(self.value, str):
                raise ValueError("retention values must be normalized decimal strings")
            normalized = normalize_decimal_string(self.value)
            if normalized != self.value:
                raise ValueError("retention value must already be normalized")
            years = Decimal(self.value)
            if years < 0:
                raise ValueError("retention years must be non-negative")
            if years > MAX_RETENTION_YEARS:
                raise ValueError("retention years out of supported range")
            if self.kind is RuleKind.ADVISED_SUFFICIENT:
                raise ValueError("advised_sufficient is an approvals rule kind")
        return self

    def decimal_value(self) -> Decimal:
        return Decimal(str(self.value))
