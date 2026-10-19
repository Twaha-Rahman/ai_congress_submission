"""Discrete interval math, allowed sets and requirement/advice classification."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import TypeAdapter

from meridian.contracts.claims import ClaimRevision
from meridian.contracts.common import (
    AmountInterval,
    Authority,
    ClosureKind,
    ExplanationCode,
    FindingType,
    Rule,
    RuleKind,
    Scope,
    Subject,
    UnitKind,
)
from meridian.contracts.extraction import ExtractionProvenance, VerifiedEvidence
from meridian.rules.compare import ClaimView, compare_claims
from meridian.rules.intervals import (
    amount_intersection,
    format_amount_interval,
    scope_intersection,
)
from meridian.rules.values import (
    Domain,
    constraint_for,
    domain_for,
    intersect,
)

UTC = timezone.utc
JAN = datetime(2026, 1, 1, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)


def _loan_scope(lower: int | None, upper: int | None, *, lower_incl=True, upper_incl=False):
    return {
        "kind": "loan",
        "loan_type": "business",
        "currency": "USD",
        "origin_office": "DHAKA",
        "amount_minor": {
            "lower": lower,
            "lower_inclusive": lower_incl,
            "upper": upper,
            "upper_inclusive": upper_incl,
        },
    }


def _record_scope(*, origin: str = "DHAKA", processing: str = "FRANKFURT"):
    return {
        "kind": "record",
        "record_class": "loan_records",
        "origin_office": origin,
        "processing_office": processing,
        "product": "MTF_CROSS_OFFICE",
        "starting_event": "loan_closure",
    }


def _revision(
    *,
    revision_id: str,
    kind: RuleKind,
    value: int | str,
    unit: UnitKind = UnitKind.APPROVALS,
    scope: dict | None = None,
    authority: Authority = Authority.POLICY,
    system_from: datetime = JAN,
    valid_from: datetime | None = JAN,
    valid_to: datetime | None = None,
    policy_family: str = "dha_retail_lending",
) -> ClaimRevision:
    return ClaimRevision(
        tenant_id="meridian_demo",
        region="DHAKA",
        claim_id=f"claim_{revision_id}",
        revision_id=revision_id,
        subject=(
            Subject.LOAN_APPROVAL
            if unit is UnitKind.APPROVALS
            else Subject.RECORD_RETENTION
        ),
        scope=scope or _loan_scope(0, None),
        rule=Rule(kind=kind, unit=unit, value=value),
        authority=authority,
        policy_family=policy_family,
        source_id=f"src_{revision_id}",
        source_identity=f"source_{revision_id}",
        source_version_label="v1",
        source_clause_id=f"source_{revision_id}:v1:1",
        valid_from=valid_from,
        valid_to=valid_to,
        system_from=system_from,
        evidence=VerifiedEvidence(
            clause_id=f"source_{revision_id}:v1:1",
            page=1,
            section=None,
            quote="synthetic evidence",
            start_char=0,
            end_char=19,
            leaf_hash="00" * 32,
            manifest_root="11" * 32,
        ),
        extraction=ExtractionProvenance(
            mode="replay",
            provider="test",
            model=None,
            validator_version="test",
        ),
    )


def test_amount_intersection_detects_included_singleton() -> None:
    left = _loan_scope(0, 2_500_000, upper_incl=True)["amount_minor"]
    right = _loan_scope(2_500_000, None, lower_incl=False)["amount_minor"]

    assert amount_intersection(AmountInterval(**left), AmountInterval(**right)) is None

    singleton = AmountInterval(
        lower=2_500_000, lower_inclusive=True, upper=2_500_000, upper_inclusive=True
    )
    touch = AmountInterval(
        lower=0, lower_inclusive=True, upper=2_500_000, upper_inclusive=True
    )
    merged = amount_intersection(touch, singleton)
    assert merged is not None
    assert merged.lower == merged.upper == 2_500_000


def test_amount_intersection_formats_the_demo_range() -> None:
    interval = AmountInterval(
        lower=2_500_000, lower_inclusive=False, upper=5_000_000, upper_inclusive=True
    )
    assert format_amount_interval(interval) == "(USD 25,000.00, USD 50,000.00]"


def test_scope_intersection_requires_matching_office_and_currency() -> None:
    adapter = TypeAdapter(Scope)
    base = adapter.validate_python(_loan_scope(0, None))
    other_office = adapter.validate_python(
        {**_loan_scope(0, None), "origin_office": "FRANKFURT"}
    )
    assert scope_intersection(base, other_office) is None

    record = adapter.validate_python(_record_scope())
    record_other = adapter.validate_python(_record_scope(processing="DHAKA"))
    assert scope_intersection(record, record_other) is None


def test_allowed_set_intersection_uses_integer_domain() -> None:
    minimum_two = constraint_for(
        Rule(kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.APPROVALS, value=2)
    )
    maximum_one = constraint_for(
        Rule(kind=RuleKind.MAXIMUM_ALLOWED, unit=UnitKind.APPROVALS, value=1)
    )
    assert (
        intersect(minimum_two, maximum_one, domain_for(UnitKind.APPROVALS)) is None
    )

    minimum_three = constraint_for(
        Rule(kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.APPROVALS, value=3)
    )
    merged = intersect(minimum_two, minimum_three, Domain.INTEGER)
    assert merged is not None
    assert merged.lo == 3 and merged.lo_inclusive


def test_two_requirements_are_compared_by_allowed_sets_not_raw_numbers() -> None:
    minimum_two = ClaimView(
        _revision(revision_id="rev_a", kind=RuleKind.REQUIRED_MINIMUM, value=2)
    )
    maximum_one = ClaimView(
        _revision(revision_id="rev_b", kind=RuleKind.MAXIMUM_ALLOWED, value=1)
    )
    contradiction = compare_claims(minimum_two, maximum_one)
    assert contradiction.finding_type is FindingType.CONTRADICTION
    assert contradiction.explanation_code is ExplanationCode.REQUIREMENT_SETS_DISJOINT
    assert contradiction.alert

    minimum_three = ClaimView(
        _revision(revision_id="rev_c", kind=RuleKind.REQUIRED_MINIMUM, value=3)
    )
    compatible = compare_claims(minimum_two, minimum_three)
    assert compatible.finding_type is FindingType.COMPATIBLE_DIFFERENCE
    assert compatible.explanation_code is ExplanationCode.REQUIREMENTS_OVERLAP


def test_current_advice_below_requirement_is_incorrect_guidance() -> None:
    requirement = ClaimView(
        _revision(
            revision_id="rev_requirement",
            kind=RuleKind.REQUIRED_MINIMUM,
            value=2,
            scope=_loan_scope(2_500_000, None, lower_incl=False),
        )
    )
    advice = ClaimView(
        _revision(
            revision_id="rev_advice",
            kind=RuleKind.ADVISED_SUFFICIENT,
            value=1,
            scope=_loan_scope(None, 5_000_000, upper_incl=True),
            authority=Authority.INFORMAL,
        )
    )
    result = compare_claims(requirement, advice)
    assert result.finding_type is FindingType.INCORRECT_GUIDANCE
    assert result.explanation_code is ExplanationCode.ADVICE_VIOLATES_REQUIREMENT
    assert result.detail["affected_amount_range"] == "(USD 25,000.00, USD 50,000.00]"


def test_superseded_requirement_that_contained_the_advice_proves_staleness() -> None:
    requirement = ClaimView(
        _revision(
            revision_id="rev_current",
            kind=RuleKind.REQUIRED_MINIMUM,
            value=2,
            scope=_loan_scope(2_500_000, None, lower_incl=False),
        )
    )
    advice = ClaimView(
        _revision(
            revision_id="rev_advice",
            kind=RuleKind.ADVISED_SUFFICIENT,
            value=1,
            scope=_loan_scope(None, 5_000_000, upper_incl=True),
            authority=Authority.INFORMAL,
        )
    )
    old_requirement = ClaimView(
        _revision(
            revision_id="rev_old",
            kind=RuleKind.REQUIRED_MINIMUM,
            value=1,
            scope=_loan_scope(0, 5_000_000, upper_incl=True),
            valid_from=JAN,
            valid_to=FEB,
        ),
        system_to=FEB,
        closure_kind=ClosureKind.SUPERSESSION,
    )
    result = compare_claims(
        requirement, advice, staleness_candidates=[requirement, advice, old_requirement]
    )
    assert result.finding_type is FindingType.STALE_GUIDANCE
    assert result.explanation_code is ExplanationCode.ADVICE_VIOLATES_REQUIREMENT_STALE
    assert result.staleness_link_revision_ids == ["rev_old"]
    assert result.detail["affected_amount_range"] == "(USD 25,000.00, USD 50,000.00]"


def test_closed_advice_is_not_re_litigated() -> None:
    requirement = ClaimView(
        _revision(revision_id="rev_req", kind=RuleKind.REQUIRED_MINIMUM, value=2)
    )
    advice = ClaimView(
        _revision(
            revision_id="rev_closed_advice",
            kind=RuleKind.ADVISED_SUFFICIENT,
            value=1,
            authority=Authority.INFORMAL,
        ),
        system_to=FEB,
        closure_kind=ClosureKind.SUPERSESSION,
    )
    result = compare_claims(requirement, advice)
    assert result.finding_type is FindingType.NOT_COMPARABLE
    assert result.explanation_code is ExplanationCode.REVISION_NOT_CURRENT


def test_operating_below_requirement_is_a_compliance_gap() -> None:
    requirement = ClaimView(
        _revision(
            revision_id="rev_policy",
            kind=RuleKind.REQUIRED_MINIMUM,
            value="7",
            unit=UnitKind.YEARS,
            scope=_record_scope(),
        )
    )
    procedure = ClaimView(
        _revision(
            revision_id="rev_proc",
            kind=RuleKind.OPERATING_EXACT,
            value="5",
            unit=UnitKind.YEARS,
            scope=_record_scope(),
            authority=Authority.PROCEDURE,
        )
    )
    result = compare_claims(requirement, procedure)
    assert result.finding_type is FindingType.COMPLIANCE_GAP
    assert result.explanation_code is ExplanationCode.OPERATING_BELOW_MINIMUM
    assert result.detail["planned_value"] == "5"
