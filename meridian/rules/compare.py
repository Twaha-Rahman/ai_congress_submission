"""Deterministic comparison and classification of two normalized claims.

The comparison works on allowed value sets, never on raw numbers alone.  A
different minimum is not a contradiction unless the allowed sets are disjoint for
the same applicability and time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from ..contracts.claims import ClaimRevision
from ..contracts.common import (
    ClosureKind,
    ExplanationCode,
    FindingType,
    Scope,
    Severity,
    Subject,
    TimeInterval,
    UnitKind,
)
from ..contracts.findings import ComparisonResult
from .intervals import (
    format_amount_interval,
    scope_intersection,
    time_intersection,
    valid_interval,
)
from .values import (
    ADVICE_KINDS,
    OPERATING_KINDS,
    REQUIREMENT_KINDS,
    Constraint,
    Domain,
    constraint_for,
    contains,
    describe,
    domain_for,
    intersect,
    witness_value,
)


def aggregate_requirements(
    views: Sequence["ClaimView"],
) -> tuple[Constraint | None, UnitKind | None]:
    """Allowed-set intersection across every applicable requirement.

    Shared by the finding and query paths so an answer can never claim a weaker
    conclusion than the persisted classification supports.  ``None`` means the
    authoritative requirements are mutually unsatisfiable.
    """

    ordered = list(views)
    if not ordered:
        return None, None
    unit = ordered[0].revision.rule.unit
    domain = domain_for(unit)
    merged = constraint_for(ordered[0].revision.rule)
    for view in ordered[1:]:
        candidate = intersect(merged, constraint_for(view.revision.rule), domain)
        if candidate is None:
            return None, unit
        merged = candidate
    return merged, unit


@dataclass(frozen=True)
class ClaimView:
    """A claim revision plus its derived (non-signed) currentness information."""

    revision: ClaimRevision
    system_to: datetime | None = None
    closure_kind: ClosureKind | None = None
    superseding_source_id: str | None = None
    supersession_effective_from: datetime | None = None
    carrier_of_revision_id: str | None = None
    #: True when this revision exists only to carry a closed claim's corrected
    #: effective history after supersession.  History is queryable but is not a
    #: new policy statement, so it is excluded from fresh finding publication.
    carried_forward: bool = False
    #: Original signed payload hash when the view was reconstructed from a remote
    #: export; local views resolve it through the store instead.
    payload_hash: str | None = None

    @property
    def revision_id(self) -> str:
        return self.revision.revision_id

    @property
    def is_current(self) -> bool:
        return self.system_to is None


def _base_result(
    left: ClaimView,
    right: ClaimView,
    *,
    finding_type: FindingType,
    severity: Severity,
    explanation: ExplanationCode,
    affected_scope: Scope | None = None,
    affected_interval: TimeInterval | None = None,
    authority_basis: str | None = None,
    staleness_links: Sequence[str] = (),
    detail: dict[str, str] | None = None,
    alert: bool = False,
) -> ComparisonResult:
    a, b = sorted([left.revision_id, right.revision_id])
    return ComparisonResult(
        finding_type=finding_type,
        severity=severity,
        explanation_code=explanation,
        left_revision_id=a,
        right_revision_id=b,
        subject=left.revision.subject,
        affected_scope=affected_scope,
        affected_valid_interval=affected_interval,
        authority_basis=authority_basis,
        staleness_link_revision_ids=list(staleness_links),
        detail=detail or {},
        alert=alert,
    )


def find_staleness_links(
    *,
    advice: ClaimRevision,
    requirement: ClaimRevision,
    affected_scope: Scope,
    affected_interval: TimeInterval,
    candidates: Sequence[ClaimView],
) -> list[str]:
    """Evidence-backed links from an advised value to a *superseded* requirement.

    A link requires an explicitly superseded revision in the same policy family as
    the current requirement whose allowed set contains the advised value over the
    affected scope and time.  An older message date alone is never sufficient.
    """

    domain = domain_for(requirement.rule.unit)
    links: set[str] = set()
    for candidate in candidates:
        other = candidate.revision
        if other.revision_id == requirement.revision_id:
            continue
        if other.subject is not advice.subject:
            continue
        if candidate.is_current:
            continue
        if candidate.closure_kind is not ClosureKind.SUPERSESSION:
            continue
        if other.policy_family != requirement.policy_family:
            continue
        if other.rule.kind not in REQUIREMENT_KINDS:
            continue
        if domain_for(other.rule.unit) is not domain:
            continue
        scope_overlap = scope_intersection(other.scope, affected_scope)
        if scope_overlap is None:
            continue
        if not contains(constraint_for(other.rule), advice.rule.decimal_value(), domain):
            continue
        other_interval = valid_interval(other.valid_from, other.valid_to)
        if time_intersection(other_interval, affected_interval) is None:
            continue
        links.add(other.revision_id)
    return sorted(links)


def compare_claims(
    left: ClaimView,
    right: ClaimView,
    *,
    staleness_candidates: Sequence[ClaimView] = (),
    explicit_supersession: bool = False,
) -> ComparisonResult:
    """Classify the relationship between two claim revisions."""

    l_rev, r_rev = left.revision, right.revision

    if l_rev.claim_id == r_rev.claim_id:
        # Same claim identity carried across an effective-history update: the
        # closure logic already handles this relation.
        return _base_result(
            left,
            right,
            finding_type=FindingType.SUPERSESSION,
            severity=Severity.INFO,
            explanation=ExplanationCode.EXPLICIT_SCOPE_REPLACEMENT,
            authority_basis="effective-history update",
            detail={"note": "revision carried forward for a new effective interval"},
        )

    if l_rev.subject is not r_rev.subject:
        return _base_result(
            left,
            right,
            finding_type=FindingType.NOT_COMPARABLE,
            severity=Severity.INFO,
            explanation=ExplanationCode.SUBJECT_MISMATCH,
        )

    scope = scope_intersection(l_rev.scope, r_rev.scope)
    if scope is None:
        return _base_result(
            left,
            right,
            finding_type=FindingType.NOT_COMPARABLE,
            severity=Severity.INFO,
            explanation=ExplanationCode.NO_SCOPE_OVERLAP,
        )

    interval = time_intersection(
        valid_interval(l_rev.valid_from, l_rev.valid_to),
        valid_interval(r_rev.valid_from, r_rev.valid_to),
    )
    if interval is None:
        return _base_result(
            left,
            right,
            finding_type=FindingType.NOT_COMPARABLE,
            severity=Severity.INFO,
            explanation=ExplanationCode.NO_TIME_OVERLAP,
            affected_scope=scope,
        )

    if explicit_supersession:
        return _base_result(
            left,
            right,
            finding_type=FindingType.SUPERSESSION,
            severity=Severity.INFO,
            explanation=ExplanationCode.EXPLICIT_SCOPE_REPLACEMENT,
            affected_scope=scope,
            affected_interval=interval,
            authority_basis=f"{l_rev.authority.value}/{r_rev.authority.value}",
        )

    if l_rev.subject is Subject.GENERAL_POLICY:
        return _base_result(
            left, right, finding_type=FindingType.NEEDS_REVIEW,
            severity=Severity.REVIEW, explanation=ExplanationCode.SEMANTIC_UNCERTAINTY,
            affected_scope=scope, affected_interval=interval,
            detail={"reason": "general policies require the evidence-grounded semantic comparison stage"},
        )

    lk, rk = l_rev.rule.kind, r_rev.rule.kind

    # ---------------------------------------------------- requirement vs requirement
    if lk in REQUIREMENT_KINDS and rk in REQUIREMENT_KINDS:
        if l_rev.rule.unit is not r_rev.rule.unit:
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.UNIT_MISMATCH,
                affected_scope=scope,
                affected_interval=interval,
            )
        if not (left.is_current and right.is_current):
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.REVISION_NOT_CURRENT,
                affected_scope=scope,
                affected_interval=interval,
            )
        domain = domain_for(l_rev.rule.unit)
        left_constraint = constraint_for(l_rev.rule)
        right_constraint = constraint_for(r_rev.rule)
        merged = intersect(left_constraint, right_constraint, domain)
        if merged is None:
            return _base_result(
                left,
                right,
                finding_type=FindingType.CONTRADICTION,
                severity=Severity.HIGH,
                explanation=ExplanationCode.REQUIREMENT_SETS_DISJOINT,
                affected_scope=scope,
                affected_interval=interval,
                authority_basis=", ".join(sorted({l_rev.authority.value, r_rev.authority.value})),
                detail={
                    "left_rule": describe(left_constraint, l_rev.rule.unit),
                    "right_rule": describe(right_constraint, r_rev.rule.unit),
                },
                alert=True,
            )
        same = (
            left_constraint.lo == right_constraint.lo
            and left_constraint.hi == right_constraint.hi
            and left_constraint.lo_inclusive == right_constraint.lo_inclusive
            and left_constraint.hi_inclusive == right_constraint.hi_inclusive
        )
        witness = witness_value(merged, domain)
        return _base_result(
            left,
            right,
            finding_type=FindingType.COMPATIBLE_DIFFERENCE,
            severity=Severity.INFO,
            explanation=(
                ExplanationCode.REQUIREMENTS_IDENTICAL if same else ExplanationCode.REQUIREMENTS_OVERLAP
            ),
            affected_scope=scope,
            affected_interval=interval,
            detail={
                "left_rule": describe(left_constraint, l_rev.rule.unit),
                "right_rule": describe(right_constraint, r_rev.rule.unit),
                "satisfying_value": str(witness) if witness is not None else "any",
            },
        )

    # ------------------------------------------------- requirement vs advice value
    if (lk in REQUIREMENT_KINDS and rk in ADVICE_KINDS) or (
        rk in REQUIREMENT_KINDS and lk in ADVICE_KINDS
    ):
        requirement = left if lk in REQUIREMENT_KINDS else right
        advice = right if requirement is left else left
        domain = domain_for(requirement.revision.rule.unit)
        if domain_for(advice.revision.rule.unit) is not domain:
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.UNIT_MISMATCH,
                affected_scope=scope,
                affected_interval=interval,
            )
        if not advice.is_current:
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.REVISION_NOT_CURRENT,
                affected_scope=scope,
                affected_interval=interval,
            )
        if not requirement.is_current:
            # A retired requirement is never re-litigated: judging current advice
            # against a clause that no longer governs would be meaningless even
            # when the values happen to overlap.  Links to retired rules are
            # evidence *inside* a comparison against the current requirement.
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.REVISION_NOT_CURRENT,
                affected_scope=scope,
                affected_interval=interval,
            )
        constraint = constraint_for(requirement.revision.rule)
        advised_value: Decimal = advice.revision.rule.decimal_value()
        unit = requirement.revision.rule.unit
        detail = {
            "required": describe(constraint, unit),
            "advised_value": str(advised_value),
        }
        if contains(constraint, advised_value, domain):
            return _base_result(
                left,
                right,
                finding_type=FindingType.COMPATIBLE_DIFFERENCE,
                severity=Severity.INFO,
                explanation=ExplanationCode.ADVICE_ADEQUATE,
                affected_scope=scope,
                affected_interval=interval,
                detail=detail,
            )
        links = find_staleness_links(
            advice=advice.revision,
            requirement=requirement.revision,
            affected_scope=scope,
            affected_interval=interval,
            candidates=staleness_candidates,
        )
        affected_amounts = (
            format_amount_interval(scope.amount_minor) if hasattr(scope, "amount_minor") else None
        )
        if affected_amounts:
            detail["affected_amount_range"] = affected_amounts
        if links:
            detail["staleness_evidence"] = (
                "advised value matches a superseded requirement in the same policy family"
            )
            return _base_result(
                left,
                right,
                finding_type=FindingType.STALE_GUIDANCE,
                severity=Severity.HIGH,
                explanation=ExplanationCode.ADVICE_VIOLATES_REQUIREMENT_STALE,
                affected_scope=scope,
                affected_interval=interval,
                authority_basis=requirement.revision.authority.value,
                staleness_links=links,
                detail=detail,
                alert=True,
            )
        return _base_result(
            left,
            right,
            finding_type=FindingType.INCORRECT_GUIDANCE,
            severity=Severity.HIGH,
            explanation=ExplanationCode.ADVICE_VIOLATES_REQUIREMENT,
            affected_scope=scope,
            affected_interval=interval,
            authority_basis=requirement.revision.authority.value,
            detail=detail,
            alert=True,
        )

    # ------------------------------------------- requirement vs planned operating
    if (lk in REQUIREMENT_KINDS and rk in OPERATING_KINDS) or (
        rk in REQUIREMENT_KINDS and lk in OPERATING_KINDS
    ):
        requirement = left if lk in REQUIREMENT_KINDS else right
        operating = right if requirement is left else left
        domain = domain_for(requirement.revision.rule.unit)
        if domain_for(operating.revision.rule.unit) is not domain:
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.UNIT_MISMATCH,
                affected_scope=scope,
                affected_interval=interval,
            )
        if not requirement.is_current or not operating.is_current:
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.REVISION_NOT_CURRENT,
                affected_scope=scope,
                affected_interval=interval,
            )
        if requirement.revision.rule.unit.value != operating.revision.rule.unit.value:
            return _base_result(
                left,
                right,
                finding_type=FindingType.NOT_COMPARABLE,
                severity=Severity.INFO,
                explanation=ExplanationCode.UNIT_MISMATCH,
                affected_scope=scope,
                affected_interval=interval,
            )
        constraint = constraint_for(requirement.revision.rule)
        planned = operating.revision.rule.decimal_value()
        unit = requirement.revision.rule.unit
        detail = {
            "planned_value": str(planned),
            "required": describe(constraint, unit),
        }
        if contains(constraint, planned, domain):
            return _base_result(
                left,
                right,
                finding_type=FindingType.COMPATIBLE_DIFFERENCE,
                severity=Severity.INFO,
                explanation=ExplanationCode.REQUIREMENTS_OVERLAP,
                affected_scope=scope,
                affected_interval=interval,
                detail=detail,
            )
        if constraint.lo is not None and planned < constraint.lo:
            return _base_result(
                left,
                right,
                finding_type=FindingType.COMPLIANCE_GAP,
                severity=Severity.HIGH,
                explanation=ExplanationCode.OPERATING_BELOW_MINIMUM,
                affected_scope=scope,
                affected_interval=interval,
                authority_basis=requirement.revision.authority.value,
                detail=detail,
                alert=True,
            )
        return _base_result(
            left,
            right,
            finding_type=FindingType.COMPLIANCE_GAP,
            severity=Severity.HIGH,
            explanation=ExplanationCode.OPERATING_ABOVE_MAXIMUM,
            affected_scope=scope,
            affected_interval=interval,
            authority_basis=requirement.revision.authority.value,
            detail=detail,
            alert=True,
        )

    # ------------------------------------------------------- unsupported modality
    return _base_result(
        left,
        right,
        finding_type=FindingType.NOT_COMPARABLE,
        severity=Severity.INFO,
        explanation=ExplanationCode.INCOMPARABLE_RULE_KINDS,
        affected_scope=scope,
        affected_interval=interval,
    )
