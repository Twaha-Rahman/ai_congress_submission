"""Contract strictness, deterministic encoding and number normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from meridian.contracts.common import (
    AmountInterval,
    Rule,
    RuleKind,
    Subject,
    TimeInterval,
    UnitKind,
    canonical_datetime,
    ensure_utc,
    find_number_tokens,
    normalize_decimal_string,
    parse_number_token,
)
from meridian.contracts.extraction import EvidenceSpan, ProposedRule
from meridian.contracts.qa import TargetFacts
from meridian.integrity.canonical import CanonicalEncodingError, canonical_json_bytes


def test_unknown_model_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(
            quote="A business loan requires two approvals.",
            authority="policy",  # a model must never be able to set trusted metadata
        )


def test_subject_and_unit_must_match_contract() -> None:
    from meridian.contracts.extraction import ExtractionProposal

    with pytest.raises(ValidationError):
        ExtractionProposal(
            rules=[
                ProposedRule(
                    subject=Subject.RECORD_RETENTION,
                    scope={
                        "kind": "record",
                        "record_class": "loan_records",
                        "origin_office": "DHAKA",
                        "processing_office": "FRANKFURT",
                        "product": "MTF_CROSS_OFFICE",
                        "starting_event": "loan_closure",
                    },
                    rule={"kind": "required_minimum", "unit": "approvals", "value": 2},
                    evidence={"quote": "Retain for at least seven years."},
                )
            ]
        )


def test_approval_values_are_integers_only() -> None:
    with pytest.raises(ValidationError):
        Rule(kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.APPROVALS, value="2")
    with pytest.raises(ValidationError):
        Rule(kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.APPROVALS, value=0)
    with pytest.raises(ValidationError):
        Rule(kind=RuleKind.OPERATING_EXACT, unit=UnitKind.APPROVALS, value=2)


def test_retention_values_must_already_be_normalized() -> None:
    assert Rule(
        kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.YEARS, value="7"
    ).decimal_value() == Decimal("7")
    assert Rule(
        kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.YEARS, value="2.5"
    ).decimal_value() == Decimal("2.5")
    with pytest.raises(ValidationError):
        Rule(kind=RuleKind.REQUIRED_MINIMUM, unit=UnitKind.YEARS, value="5.0")
    with pytest.raises(ValidationError):
        Rule(kind=RuleKind.ADVISED_SUFFICIENT, unit=UnitKind.YEARS, value="5")


def test_number_surface_forms_normalize_to_the_same_value() -> None:
    for token in ("50k", "50,000", "50000"):
        assert parse_number_token(token) == Decimal("50000")
    assert parse_number_token("five") == Decimal("5")
    assert parse_number_token("2.5") == Decimal("2.5")
    assert parse_number_token("1.5k") == Decimal("1500")
    assert parse_number_token("many") is None

    tokens = find_number_tokens("Up to USD 50k or 50,000 minor units, five approvals")
    assert [value for _token, value, _start, _end in tokens] == [
        Decimal("50000"),
        Decimal("50000"),
        Decimal("5"),
    ]


def test_decimal_strings_are_normalized_without_exponents() -> None:
    assert normalize_decimal_string("05") == "5"
    assert normalize_decimal_string("5.0") == "5"
    assert normalize_decimal_string("0.500") == "0.5"
    assert normalize_decimal_string(Decimal("2.50")) == "2.5"
    with pytest.raises(ValueError):
        normalize_decimal_string("NaN")


def test_amount_interval_boundary_membership() -> None:
    interval = AmountInterval(
        lower=2_500_000, lower_inclusive=False, upper=5_000_000, upper_inclusive=True
    )
    assert not interval.contains(2_500_000)
    assert interval.contains(2_500_001)
    assert interval.contains(5_000_000)
    assert not interval.contains(5_000_001)

    with pytest.raises(ValidationError):
        AmountInterval(lower=100, upper=100)  # empty by default upper exclusivity

    singleton = AmountInterval(
        lower=100, lower_inclusive=True, upper=100, upper_inclusive=True
    )
    assert singleton.contains(100)


def test_time_intervals_are_half_open_and_require_utc() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    interval = TimeInterval(start=start, end=end)
    assert interval.contains(start)
    assert not interval.contains(end)
    assert interval.overlaps(
        TimeInterval(start=datetime(2026, 1, 31, tzinfo=timezone.utc), end=None)
    )
    with pytest.raises(ValidationError):
        TimeInterval(start=datetime(2026, 1, 1), end=end)
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))


def test_canonical_encoding_is_sorted_and_rejects_floats() -> None:
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert (
        canonical_json_bytes(
            {"at": datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)}
        )
        == b'{"at":"2026-01-01T12:00:00.123456Z"}'
    )
    with pytest.raises(CanonicalEncodingError):
        canonical_json_bytes({"temperature": 0.5})
    with pytest.raises(CanonicalEncodingError):
        canonical_json_bytes({1: "non-string key"})


def test_canonical_datetime_omits_zero_microseconds() -> None:
    assert (
        canonical_datetime(datetime(2026, 1, 1, tzinfo=timezone.utc))
        == "2026-01-01T00:00:00Z"
    )


def test_target_facts_reject_incomplete_loan_queries() -> None:
    with pytest.raises(ValidationError):
        TargetFacts(subject="loan_approval", amount_minor=100)
    with pytest.raises(ValidationError):
        TargetFacts(
            subject="loan_approval",
            amount_minor=0,
            currency="USD",
            loan_type="business",
            origin_office="DHAKA",
        )
