"""Evidence-grounded validation of extraction proposals.

The validator is the only path from a model proposal to a persisted claim.  It
resolves exact evidence quotes inside preserved parser text, normalizes supported
number forms, checks operator/modality/negation against supported patterns, preserves
conditions and exceptions, and rejects hallucinated evidence or unsupported fields.

Schema-valid JSON and a matching number are necessary but not sufficient checks: a
proposal that cannot be tied to supported source wording becomes ``needs_review``
rather than an accepted rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re

from ..contracts.common import (
    VALIDATOR_VERSION,
    AmountScope,
    Rule,
    RuleKind,
    Scope,
    Subject,
)
from ..contracts.extraction import (
    EvidenceSpan,
    ExtractionProposal,
    ProposedRule,
    VerifiedEvidence,
)
from ..contracts.manifest import SourceManifest
from ..rules.intervals import scope_intersection

MODALITY_PATTERNS: dict[RuleKind, tuple[str, ...]] = {
    RuleKind.REQUIRED_MINIMUM: (
        r"\bat least\b",
        r"\bminimum\b",
        r"\bno fewer than\b",
        r"\bnot less than\b",
        r"\brequire[sd]?\b",
        r"\bmust\b",
        r"\bneed[sd]?\b",
    ),
    RuleKind.MAXIMUM_ALLOWED: (
        r"\bno more than\b",
        r"\bat most\b",
        r"\bmaximum\b",
        r"\bnot exceed\b",
        r"\bup to\b",
        r"\bmay not exceed\b",
    ),
    RuleKind.EXACTLY_REQUIRED: (r"\bexactly\b", r"\bequal to\b", r"\bmust be\b"),
    RuleKind.ADVISED_SUFFICIENT: (
        r"\bsufficient\b",
        r"\benough\b",
        r"\bneed only\b",
        r"\bdo(?:es)? not need\b",
        r"\bno (?:second|additional|further)\b",
        r"\bonly\b",
    ),
    RuleKind.OPERATING_EXACT: (r"\bexactly\b", r"\bdelete\b", r"\bretain\b", r"\bafter\b"),
}

NEGATION_PATTERNS = (
    r"\bnot\b",
    r"\bno\b",
    r"\bnever\b",
    r"\bwithout\b",
    r"\bdo(?:es)? not\b",
    r"\bneed not\b",
)

#: Negation forms that are consistent with advice that a *lower* value is sufficient.
ADVICE_NEGATION_ALLOWLIST = (
    r"\bdo(?:es)? not need\b",
    r"\bno (?:second|additional|further)\b",
    r"\bnot (?:required|needed)\b",
)

CONDITION_PATTERNS = (
    r"\bunless\b",
    r"\bexcept\b",
    r"\bsubject to\b",
    r"\bprovided that\b",
    r"\bnotwithstanding\b",
    r"\bsee section\b",
    r"\bas defined in\b",
    r"\brefer to\b",
    r"\bper (?:the )?(?:annex|appendix|attachment)\b",
)

UNIT_CONTEXT: dict[str, tuple[str, ...]] = {
    "approvals": (r"\bapproval", r"\bsign[- ]?off", r"\bsignature"),
    "years": (r"\byear", r"\bretain", r"\bdelete\b", r"\bretention\b"),
}

AMOUNT_UNIT_HINT = re.compile(r"[$]|\bUSD\b|\bUSD\s?\$", re.IGNORECASE)


@dataclass(frozen=True)
class ValidatorClause:
    clause_id: str
    page: int
    section: str | None
    text: str
    leaf_hash: str


@dataclass(frozen=True)
class VerifiedRule:
    proposed: ProposedRule
    evidence: VerifiedEvidence
    clause: ValidatorClause
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewItem:
    reason_code: str
    detail: str
    subject: Subject | None = None
    clause_id: str | None = None
    quote: str | None = None
    proposed: ProposedRule | None = None


@dataclass(frozen=True)
class Rejection:
    reason_code: str
    detail: str
    rule_index: int


@dataclass(frozen=True)
class ValidationOutcome:
    accepted: list[VerifiedRule]
    reviews: list[ReviewItem]
    rejections: list[Rejection]
    validator_version: str = VALIDATOR_VERSION


def _find_quote(span: EvidenceSpan, clauses: list[ValidatorClause]) -> list[tuple[ValidatorClause, int]]:
    matches: list[tuple[ValidatorClause, int]] = []
    for clause in clauses:
        start = clause.text.find(span.quote)
        if start >= 0:
            matches.append((clause, start))
    return matches


def _numbers_in(text: str) -> list[Decimal]:
    from ..contracts.common import find_number_tokens

    return [value for _token, value, _start, _end in find_number_tokens(text)]


def _amount_tokens(text: str) -> list[tuple[str, Decimal, int, int]]:
    """Number tokens that are used as money amounts in ``text``.

    Approval counts must never satisfy a currency bound merely because the digits
    coincide.  A token qualifies when currency appears immediately beside it, when it
    uses the ``50k`` shorthand in a sentence that declares USD, or when it is followed
    by ``dollars``/``USD``.
    """

    from ..contracts.common import find_number_tokens

    has_currency = AMOUNT_UNIT_HINT.search(text) is not None
    out: list[tuple[str, Decimal, int, int]] = []
    for token, value, start, end in find_number_tokens(text):
        before = text[max(0, start - 12) : start]
        after = text[end : end + 12]
        immediate_currency = re.search(r"(?:USD|\$)\s*$", before, re.IGNORECASE)
        trailing_currency = re.match(r"\s*(?:dollars?|USD)\b", after, re.IGNORECASE)
        # A trailing k is an amount shorthand when the trusted proposal scope is a
        # currency scope; it must not depend on the prose separately repeating USD.
        shorthand = token.strip().lower().endswith("k")
        if immediate_currency or trailing_currency or shorthand:
            out.append((token, value, start, end))
    return out


def _has_amount_in_evidence(scope: Scope, quote: str) -> list[str]:
    """Return a list of finite non-zero amount bounds missing from the quote."""

    if not isinstance(scope, AmountScope):
        return []
    numbers = [value for _token, value, _start, _end in _amount_tokens(quote)]
    missing: list[str] = []
    for bound in (scope.amount_minor.lower, scope.amount_minor.upper):
        if bound is None or bound == 0:
            continue
        dollars = Decimal(bound) / Decimal(100)
        if dollars not in numbers:
            missing.append(format(dollars.normalize(), "f"))
    return missing


# Operator phrases that must be adjacent to the proposed *value* and its unit.
MIN_PRE = re.compile(
    r"(?:\bat least|\bno fewer than|\bnot less than|\bminimum(?: of)?)\s*$",
    re.IGNORECASE,
)
MAX_PRE = re.compile(
    r"(?:\bno more than|\bnot more than|\bat most|\bmaximum(?: of)?|\bup to|"
    r"\bmay not exceed|\bnot exceed)\s*$",
    re.IGNORECASE,
)
EXACT_PRE = re.compile(r"(?:\bexactly|\bequal to)\s*$", re.IGNORECASE)
MIN_POST = re.compile(r"^\s*(?:approvals?|years?)\s+(?:or more|and above|or greater)\b", re.IGNORECASE)
MAX_POST = re.compile(r"^\s*(?:approvals?|years?)\s+(?:or fewer|or less|and below|or lower)\b", re.IGNORECASE)
ADVICE_PRE = re.compile(r"(?:\bneed(?:s|ed)? only|\bonly)\s*$", re.IGNORECASE)
ADVICE_POST = re.compile(
    r"^\s*(?:approvals?|collateral\s+sign[- ]?offs?|sign[- ]?offs?|"
    r"signatures?|reviewers?)\s+"
    r"(?:are|is)\s+(?:sufficient|enough)\b",
    re.IGNORECASE,
)
ADVICE_NO_EXTRA = re.compile(
    r"\bno (?:second|additional|further)\s+(?:approval|sign[- ]?off|signature|review)",
    re.IGNORECASE,
)
OPERATING_EXACT_PRE = re.compile(r"\bexactly\s*$", re.IGNORECASE)
UNIT_AFTER = re.compile(
    r"\s*(?:collateral\s+sign[- ]?offs?|approvals?|sign[- ]?offs?|"
    r"signatures?|reviewers?|years?)\b",
    re.IGNORECASE,
)

LOWER_EXCLUSIVE_PRE = re.compile(
    r"(?:greater than|more than|above|over|exceeding)\s*(?:USD\s*|\$)?\s*$", re.IGNORECASE
)
LOWER_INCLUSIVE_PRE = re.compile(
    r"(?:at least|no less than|not less than)\s*(?:USD\s*|\$)?\s*$", re.IGNORECASE
)
LOWER_INCLUSIVE_POST = re.compile(r"^\s*(?:or (?:more|greater|above)|and above)\b", re.IGNORECASE)
UPPER_INCLUSIVE_PRE = re.compile(
    r"(?:up to|at most|no more than|not more than|maximum(?: of)?)\s*"
    r"(?:USD\s*|\$)?\s*$",
    re.IGNORECASE,
)
UPPER_INCLUSIVE_POST = re.compile(
    r"^\s*(?:or (?:less|fewer|lower|below)|and below)\b", re.IGNORECASE
)
UPPER_EXCLUSIVE_PRE = re.compile(
    r"(?:less than|fewer than|below|under)\s*(?:USD\s*|\$)?\s*$", re.IGNORECASE
)


def _bound_direction(quote: str, start: int, end: int) -> tuple[str, bool] | None:
    """Classify a money token's bound direction and inclusivity from its wording."""

    before = quote[max(0, start - 48) : start]
    after = quote[end : end + 48]
    if LOWER_EXCLUSIVE_PRE.search(before):
        return "lower", False
    if LOWER_INCLUSIVE_PRE.search(before) or LOWER_INCLUSIVE_POST.search(after):
        return "lower", True
    if UPPER_EXCLUSIVE_PRE.search(before):
        return "upper", False
    if UPPER_INCLUSIVE_PRE.search(before) or UPPER_INCLUSIVE_POST.search(after):
        return "upper", True
    return None


def _amount_direction_findings(scope: Scope, quote: str) -> list[tuple[str, str]]:
    """Detect flipped bounds, inclusivity confusion and unmarked amount limits."""

    if not isinstance(scope, AmountScope):
        return []
    tokens = _amount_tokens(quote)
    findings: list[tuple[str, str]] = []
    checks = (
        ("lower", scope.amount_minor.lower, scope.amount_minor.lower_inclusive),
        ("upper", scope.amount_minor.upper, scope.amount_minor.upper_inclusive),
    )
    for expected_kind, bound, inclusive in checks:
        if bound is None or bound == 0:
            continue
        dollars = Decimal(bound) / Decimal(100)
        candidates = [item for item in tokens if item[1] == dollars]
        if not candidates:
            continue  # reported by the missing-amount check
        observed = [
            (item, _bound_direction(quote, item[2], item[3])) for item in candidates
        ]
        conflicts = [
            (item, direction)
            for item, direction in observed
            if direction is not None
            and (direction[0] != expected_kind or direction[1] != inclusive)
        ]
        if conflicts:
            item, direction = conflicts[0]
            assert direction is not None
            findings.append(
                (
                    "amount_direction_mismatch",
                    f"scope {expected_kind} bound {format(dollars.normalize(), 'f')} "
                    f"(inclusive={inclusive}) contradicts the source wording "
                    f"{item[0]!r}, which denotes a {direction[0]} bound with "
                    f"inclusive={direction[1]}",
                )
            )
            continue
        if not any(direction is not None for _item, direction in observed):
            findings.append(
                (
                    "amount_direction_unsupported",
                    f"source wording does not state whether {format(dollars.normalize(), 'f')} "
                    f"is an inclusive or exclusive {expected_kind} bound",
                )
            )
    return findings


def _source_amount_bounds(text: str) -> tuple[dict[str, tuple[int, bool]], str | None]:
    """Parse explicit, supported amount bounds from source text independently.

    This is intentionally separate from the proposed scope: otherwise a model can
    omit a restriction and leave the validator with no proposed value to check.
    The parser recognizes the same narrow direction/inclusivity grammar as the
    proposal-side check and refuses conflicting or unclassified amount mentions.
    """

    bounds: dict[str, tuple[int, bool]] = {}
    for token, dollars, start, end in _amount_tokens(text):
        direction = _bound_direction(text, start, end)
        if direction is None:
            # An amount token in an unrelated context is not an applicability bound.
            continue
        minor = dollars * Decimal(100)
        if minor != minor.to_integral_value():
            return {}, f"source amount {token!r} cannot be represented in minor units"
        kind, inclusive = direction
        candidate = (int(minor), inclusive)
        if kind in bounds and bounds[kind] != candidate:
            return {}, f"source text states conflicting {kind} amount bounds"
        bounds[kind] = candidate
    return bounds, None


def _source_scope_mismatches(scope: Scope, source_text: str) -> list[str]:
    """Compare every explicit source amount bound with the complete proposed scope."""

    if not isinstance(scope, AmountScope):
        return []
    expected, error = _source_amount_bounds(source_text)
    if error:
        return [error]
    mismatches: list[str] = []
    actual = {
        "lower": (scope.amount_minor.lower, scope.amount_minor.lower_inclusive),
        "upper": (scope.amount_minor.upper, scope.amount_minor.upper_inclusive),
    }
    for kind, expected_bound in expected.items():
        if actual[kind] != expected_bound:
            expected_minor, expected_inclusive = expected_bound
            proposed_minor, proposed_inclusive = actual[kind]
            mismatches.append(
                f"source {kind} bound is {expected_minor} minor units "
                f"(inclusive={expected_inclusive}), but proposed scope is "
                f"{proposed_minor} (inclusive={proposed_inclusive})"
            )
    return mismatches


def _wording_match(
    rule: Rule, quote: str
) -> tuple[bool, str | None, tuple[int, int] | None, str | None]:
    """Bind the proposed rule kind to an operator next to the value and unit.

    Returns ``(accepted, failure_reason, span, detail)``.  A number that appears only
    as an unrelated quantity, or whose operator contradicts the proposed semantics,
    is rejected for review rather than accepted because a separate modality word
    happened to occur elsewhere in the quote.
    """

    from ..contracts.common import find_number_tokens

    value = rule.decimal_value()
    candidates = [
        (start, end)
        for _token, token_value, start, end in find_number_tokens(quote)
        if token_value == value
    ]
    if not candidates:
        return False, "value_not_supported_by_evidence", None, None
    unit_bound = [
        (start, end)
        for start, end in candidates
        if UNIT_AFTER.match(quote[end:]) is not None
    ]
    if not unit_bound:
        return (
            False,
            "value_unit_binding_failed",
            None,
            "the rule value is present but is not bound to the rule's unit",
        )

    opposite_seen: str | None = None
    for start, end in unit_bound:
        before = quote[max(0, start - 48) : start]
        after = quote[end : end + 64]
        unit_match = UNIT_AFTER.match(quote[end:])
        unit_end = end + (unit_match.end() if unit_match is not None else 0)
        span = (start, unit_end)
        if rule.kind is RuleKind.REQUIRED_MINIMUM:
            max_match = MAX_PRE.search(before)
            exact_match = EXACT_PRE.search(before)
            if max_match:
                opposite_seen = "maximum wording"
                continue
            if exact_match:
                opposite_seen = "exact wording"
                continue
            min_match = MIN_PRE.search(before)
            post_match = MIN_POST.match(after)
            if min_match:
                return (
                    True,
                    None,
                    (start - (len(before) - min_match.start()), unit_end),
                    None,
                )
            if post_match:
                return True, None, (start, end + post_match.end()), None
        elif rule.kind is RuleKind.MAXIMUM_ALLOWED:
            min_match = MIN_PRE.search(before)
            exact_match = EXACT_PRE.search(before)
            if min_match:
                opposite_seen = "minimum wording"
                continue
            if exact_match:
                opposite_seen = "exact wording"
                continue
            max_match = MAX_PRE.search(before)
            post_match = MAX_POST.match(after)
            if max_match:
                return (
                    True,
                    None,
                    (start - (len(before) - max_match.start()), unit_end),
                    None,
                )
            if post_match:
                return True, None, (start, end + post_match.end()), None
        elif rule.kind is RuleKind.EXACTLY_REQUIRED:
            min_match = MIN_PRE.search(before)
            max_match = MAX_PRE.search(before)
            exact_match = EXACT_PRE.search(before)
            if min_match:
                opposite_seen = "minimum wording"
                continue
            if max_match:
                opposite_seen = "maximum wording"
                continue
            if exact_match:
                return (
                    True,
                    None,
                    (start - (len(before) - exact_match.start()), unit_end),
                    None,
                )
        elif rule.kind is RuleKind.ADVISED_SUFFICIENT:
            advice_match = ADVICE_PRE.search(before)
            post_match = ADVICE_POST.match(after)
            if advice_match:
                return (
                    True,
                    None,
                    (start - (len(before) - advice_match.start()), unit_end),
                    None,
                )
            if post_match:
                return True, None, (start, end + post_match.end()), None
            if value == 1 and ADVICE_NO_EXTRA.search(quote):
                return True, None, span, None
        elif rule.kind is RuleKind.OPERATING_EXACT:
            exact_match = OPERATING_EXACT_PRE.search(before)
            if exact_match:
                return (
                    True,
                    None,
                    (start - (len(before) - exact_match.start()), unit_end),
                    None,
                )
            if MIN_PRE.search(before) or MAX_PRE.search(before):
                opposite_seen = "non-exact retention wording"
                continue
    if opposite_seen:
        return (
            False,
            "operator_direction_mismatch",
            None,
            f"proposed rule kind {rule.kind.value} conflicts with the source's {opposite_seen}",
        )
    return (
        False,
        "unsupported_modality",
        None,
        f"evidence does not contain an unambiguous supported phrase for rule kind "
        f"{rule.kind.value} bound to the proposed value and unit",
    )


def validate_proposal(
    proposal: ExtractionProposal,
    *,
    manifest: SourceManifest,
    clauses: list[ValidatorClause],
    manifest_root: str,
) -> ValidationOutcome:
    """Validate one proposal against trusted metadata and preserved parser text."""

    accepted: list[VerifiedRule] = []
    reviews: list[ReviewItem] = []
    rejections: list[Rejection] = []

    for index, rule in enumerate(proposal.rules):
        notes: list[str] = []
        if rule.subject is not manifest.subject:
            rejections.append(
                Rejection(
                    reason_code="subject_mismatch",
                    detail=(
                        f"proposal subject {rule.subject.value} does not match the manifest "
                        f"subject {manifest.subject.value}"
                    ),
                    rule_index=index,
                )
            )
            continue

        if rule.unsupported_conditions:
            reviews.append(
                ReviewItem(
                    reason_code="unsupported_condition",
                    detail="proposal declares unsupported conditions: "
                    + "; ".join(rule.unsupported_conditions),
                    subject=rule.subject,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        if rule.ambiguous:
            reviews.append(
                ReviewItem(
                    reason_code="ambiguous_proposal",
                    detail=rule.ambiguous_reason or "model reported an ambiguous statement",
                    subject=rule.subject,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        matches = _find_quote(rule.evidence, clauses)
        if not matches:
            rejections.append(
                Rejection(
                    reason_code="hallucinated_evidence",
                    detail="evidence quote was not found in the preserved parser text",
                    rule_index=index,
                )
            )
            continue
        if len(matches) > 1:
            hints = [clause for clause, _ in matches if rule.evidence.page is None or clause.page == rule.evidence.page]
            if len(hints) == 1:
                matches = hints
            else:
                reviews.append(
                    ReviewItem(
                        reason_code="ambiguous_evidence",
                        detail="evidence quote occurs in more than one clause; add page/section",
                        subject=rule.subject,
                        quote=rule.evidence.quote,
                        proposed=rule,
                    )
                )
                continue
        clause, offset = matches[0]

        if rule.evidence.page is not None and rule.evidence.page != clause.page:
            reviews.append(
                ReviewItem(
                    reason_code="evidence_locator_mismatch",
                    detail=(
                        f"proposal located the quote on page {rule.evidence.page} but the parser "
                        f"found it on page {clause.page}"
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue
        if rule.evidence.section is not None and clause.section is not None:
            if rule.evidence.section != clause.section:
                reviews.append(
                    ReviewItem(
                        reason_code="evidence_locator_mismatch",
                        detail=(
                            f"proposal section {rule.evidence.section} differs from parser "
                            f"section {clause.section}"
                        ),
                        subject=rule.subject,
                        clause_id=clause.clause_id,
                        quote=rule.evidence.quote,
                        proposed=rule,
                    )
                )
                continue
        start = offset
        end = offset + len(rule.evidence.quote)
        if rule.evidence.start_char is not None:
            if rule.evidence.start_char != start or rule.evidence.end_char != end:
                notes.append(
                    "backend resolved evidence offsets differing from the proposal"
                )

        # -------------------------------------------------------------- conditions
        condition_hit = _first_pattern(clause.text, CONDITION_PATTERNS)
        if condition_hit:
            reviews.append(
                ReviewItem(
                    reason_code="unsupported_condition",
                    detail=(
                        f"clause text contains the unsupported condition marker {condition_hit!r}; "
                        "the condition is preserved for review instead of being dropped"
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        # ------------------------------------------------------------------ scope
        intersection = scope_intersection(manifest.scope, rule.scope)
        if intersection is None or intersection != rule.scope:
            reviews.append(
                ReviewItem(
                    reason_code="scope_outside_manifest",
                    detail="proposed applicability is not covered by the trusted manifest scope",
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        source_scope_mismatches = _source_scope_mismatches(
            rule.scope, rule.evidence.quote
        )
        if source_scope_mismatches:
            reviews.append(
                ReviewItem(
                    reason_code="source_scope_not_preserved",
                    detail=(
                        "the proposed applicability does not preserve the amount limits "
                        "stated in the source: " + "; ".join(source_scope_mismatches)
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        # -------------------------------------------------------------- numbers
        numbers = _numbers_in(rule.evidence.quote)
        if rule.rule.decimal_value() not in numbers:
            reviews.append(
                ReviewItem(
                    reason_code="value_not_supported_by_evidence",
                    detail=(
                        f"normalized rule value {rule.rule.value!r} does not appear in the "
                        "evidence quote in a supported number form"
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue
        missing_amounts = _has_amount_in_evidence(rule.scope, rule.evidence.quote)
        if missing_amounts:
            reviews.append(
                ReviewItem(
                    reason_code="amount_not_supported_by_evidence",
                    detail=(
                        "scope amount bound(s) not present as money amounts in the evidence "
                        "quote: " + ", ".join(missing_amounts)
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue
        amount_findings = _amount_direction_findings(rule.scope, rule.evidence.quote)
        if amount_findings:
            reason_code, detail = amount_findings[0]
            reviews.append(
                ReviewItem(
                    reason_code=reason_code,
                    detail=detail,
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        # -------------------------------------------------------------- modality
        wording_ok, wording_reason, modality_span, wording_detail = _wording_match(
            rule.rule, rule.evidence.quote
        )
        if not wording_ok:
            failure_reason = wording_reason or "unsupported_modality"
            if failure_reason in {
                "unsupported_modality",
                "value_unit_binding_failed",
            } and _first_pattern(rule.evidence.quote, NEGATION_PATTERNS):
                failure_reason = "unsupported_negation"
            reviews.append(
                ReviewItem(
                    reason_code=failure_reason,
                    detail=(
                        wording_detail
                        or (
                            f"evidence does not contain a supported phrase for rule kind "
                            f"{rule.rule.kind.value}"
                        )
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue
        assert modality_span is not None

        # -------------------------------------------------------------- negation
        negation = _first_pattern(rule.evidence.quote, NEGATION_PATTERNS)
        if negation:
            # A negation marker that is part of the required modality phrase itself
            # ("no fewer than", "no more than", "may not exceed") carries the meaning
            # of the rule rather than negating it; a marker anywhere else must be
            # confirmed by a reviewer.  Advice phrased as a negation of an extra
            # step ("do not need", "no second") stays explicitly allowed.
            negation_span = _first_pattern_span(rule.evidence.quote, NEGATION_PATTERNS)
            inside_modality = (
                negation_span is not None
                and modality_span[0] <= negation_span[0] < modality_span[1]
            )
            advice_allowed = rule.rule.kind is RuleKind.ADVISED_SUFFICIENT and _first_pattern(
                rule.evidence.quote, ADVICE_NEGATION_ALLOWLIST
            )
            if not (inside_modality or advice_allowed):
                reviews.append(
                    ReviewItem(
                        reason_code="unsupported_negation",
                        detail=(
                            f"evidence contains negation marker {negation!r}; polarity must be "
                            "confirmed by a reviewer"
                        ),
                        subject=rule.subject,
                        clause_id=clause.clause_id,
                        quote=rule.evidence.quote,
                        proposed=rule,
                    )
                )
                continue
            notes.append(
                "negation is part of the supported modality phrase"
                if inside_modality
                else "negation accepted as reinforcement of sufficient advice"
            )

        # -------------------------------------------------------------- unit context
        unit_patterns = UNIT_CONTEXT[rule.rule.unit.value]
        if _first_pattern(clause.text, unit_patterns) is None:
            reviews.append(
                ReviewItem(
                    reason_code="unsupported_unit_context",
                    detail=(
                        f"clause text does not mention wording associated with unit "
                        f"{rule.rule.unit.value}"
                    ),
                    subject=rule.subject,
                    clause_id=clause.clause_id,
                    quote=rule.evidence.quote,
                    proposed=rule,
                )
            )
            continue

        accepted.append(
            VerifiedRule(
                proposed=rule,
                clause=clause,
                notes=notes,
                evidence=VerifiedEvidence(
                    clause_id=clause.clause_id,
                    page=clause.page,
                    section=clause.section,
                    quote=rule.evidence.quote,
                    start_char=start,
                    end_char=end,
                    leaf_hash=clause.leaf_hash,
                    manifest_root=manifest_root,
                ),
            )
        )

    for case in proposal.unsupported_cases:
        reviews.append(
            ReviewItem(
                reason_code=f"model_reported_unsupported:{case.reason_code}",
                detail=case.description,
                subject=manifest.subject,
                quote=case.quote,
            )
        )

    return ValidationOutcome(accepted=accepted, reviews=reviews, rejections=rejections)


def _first_pattern(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def _first_pattern_span(text: str, patterns: tuple[str, ...]) -> tuple[int, int] | None:
    """Span of the first pattern (in declared order) that matches ``text``."""

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            return match.span()
    return None


def rule_summary(rule: Rule) -> str:
    from ..rules.values import describe, constraint_for

    if rule.kind in (RuleKind.ADVISED_SUFFICIENT, RuleKind.OPERATING_EXACT):
        verb = "advised sufficient" if rule.kind is RuleKind.ADVISED_SUFFICIENT else "planned operating"
        return f"{verb} value {rule.value} {rule.unit.value}"
    return describe(constraint_for(rule), rule.unit)
