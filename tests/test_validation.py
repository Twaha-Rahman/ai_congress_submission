"""Evidence-grounded proposal validation: hallucination, conditions and negation."""

from __future__ import annotations

from meridian.contracts.common import RuleKind, Subject
from meridian.contracts.extraction import ExtractionProposal, ProposedRule
from meridian.contracts.manifest import SourceManifest
from meridian.extraction.validate import ValidatorClause, validate_proposal

from conftest import FIXTURES

QUOTE = (
    "A business loan in USD with an amount greater than USD 25,000 requires "
    "at least two approvals from the credit committee."
)
CLAUSE = ValidatorClause(
    clause_id="dhaka_lending_policy:v3:4.1",
    page=1,
    section="4.1",
    text=QUOTE,
    leaf_hash="ab" * 32,
)
MANIFEST_ROOT = "cd" * 32
MANIFEST = SourceManifest.model_validate_json(
    (FIXTURES / "manifests/dhaka_lending_policy_v3.json").read_text("utf-8")
)


def _proposal(
    *,
    quote: str = QUOTE,
    value: int = 2,
    kind: RuleKind = RuleKind.REQUIRED_MINIMUM,
    scope: dict | None = None,
    ambiguous: bool = False,
    ambiguous_reason: str | None = None,
) -> ExtractionProposal:
    return ExtractionProposal(
        rules=[
            ProposedRule(
                subject=Subject.LOAN_APPROVAL,
                scope=scope
                or {
                    "kind": "loan",
                    "loan_type": "business",
                    "currency": "USD",
                    "origin_office": "DHAKA",
                    "amount_minor": {
                        "lower": 2_500_000,
                        "lower_inclusive": False,
                        "upper": None,
                        "upper_inclusive": False,
                    },
                },
                rule={"kind": kind, "unit": "approvals", "value": value},
                evidence={"page": 1, "quote": quote},
                ambiguous=ambiguous,
                ambiguous_reason=ambiguous_reason,
            )
        ]
    )


def _validate(proposal: ExtractionProposal, clauses: list[ValidatorClause] | None = None):
    return validate_proposal(
        proposal,
        manifest=MANIFEST,
        clauses=clauses or [CLAUSE],
        manifest_root=MANIFEST_ROOT,
    )


def test_exact_quote_is_accepted_and_offsets_are_resolved() -> None:
    outcome = _validate(_proposal())
    assert not outcome.reviews and not outcome.rejections
    assert len(outcome.accepted) == 1
    verified = outcome.accepted[0]
    assert verified.evidence.clause_id == CLAUSE.clause_id
    assert verified.evidence.start_char == 0
    assert verified.evidence.end_char == len(QUOTE)
    assert verified.evidence.leaf_hash == CLAUSE.leaf_hash
    assert verified.evidence.manifest_root == MANIFEST_ROOT


def test_hallucinated_quote_is_rejected_not_accepted() -> None:
    outcome = _validate(
        _proposal(quote="The bank may approve any amount with a single signature.")
    )
    assert not outcome.accepted
    assert [item.reason_code for item in outcome.rejections] == [
        "hallucinated_evidence"
    ]


def test_value_must_appear_in_the_evidence_quote() -> None:
    outcome = _validate(_proposal(value=3))
    assert not outcome.accepted
    assert "value_not_supported_by_evidence" in {
        item.reason_code for item in outcome.reviews
    }


def test_source_amount_floor_cannot_be_dropped_from_proposed_scope() -> None:
    unbounded_scope = {
        "kind": "loan",
        "loan_type": "business",
        "currency": "USD",
        "origin_office": "DHAKA",
        "amount_minor": {
            "lower": 0,
            "lower_inclusive": True,
            "upper": None,
            "upper_inclusive": False,
        },
    }
    outcome = _validate(_proposal(scope=unbounded_scope))
    assert not outcome.accepted
    assert "source_scope_not_preserved" in {item.reason_code for item in outcome.reviews}


def test_source_amount_ceiling_cannot_be_dropped_from_proposed_scope() -> None:
    text = (
        "A business loan in USD with an amount of USD 25,000 or less requires "
        "at least two approvals from the credit committee."
    )
    scope = {
        "kind": "loan",
        "loan_type": "business",
        "currency": "USD",
        "origin_office": "DHAKA",
        "amount_minor": {
            "lower": 0,
            "lower_inclusive": True,
            "upper": None,
            "upper_inclusive": False,
        },
    }
    clause = ValidatorClause(
        clause_id=CLAUSE.clause_id,
        page=1,
        section="4.1",
        text=text,
        leaf_hash=CLAUSE.leaf_hash,
    )
    outcome = _validate(_proposal(quote=text, scope=scope), [clause])
    assert not outcome.accepted
    assert "source_scope_not_preserved" in {item.reason_code for item in outcome.reviews}


def test_scope_must_be_covered_by_the_trusted_manifest() -> None:
    frankfurt_scope = {
        "kind": "loan",
        "loan_type": "business",
        "currency": "USD",
        "origin_office": "FRANKFURT",
        "amount_minor": {
            "lower": 2_500_000,
            "lower_inclusive": False,
            "upper": None,
            "upper_inclusive": False,
        },
    }
    outcome = _validate(_proposal(scope=frankfurt_scope))
    assert not outcome.accepted
    assert "scope_outside_manifest" in {
        item.reason_code for item in outcome.reviews
    }


def test_condition_markers_are_preserved_for_review_not_dropped() -> None:
    conditional_text = QUOTE.replace(
        "from the credit committee.",
        "from the credit committee, unless the risk committee grants an exception.",
    )
    clause = ValidatorClause(
        clause_id=CLAUSE.clause_id,
        page=1,
        section="4.1",
        text=conditional_text,
        leaf_hash=CLAUSE.leaf_hash,
    )
    outcome = _validate(_proposal(quote=conditional_text), [clause])
    assert not outcome.accepted
    reasons = {item.reason_code for item in outcome.reviews}
    assert "unsupported_condition" in reasons
    review = next(item for item in outcome.reviews if item.reason_code == "unsupported_condition")
    assert "unless" in review.detail


def test_negation_outside_supported_modality_needs_review() -> None:
    negative_text = (
        "A business loan in USD with an amount greater than USD 25,000 is not "
        "required to have two approvals from the credit committee."
    )
    clause = ValidatorClause(
        clause_id=CLAUSE.clause_id,
        page=1,
        section="4.1",
        text=negative_text,
        leaf_hash=CLAUSE.leaf_hash,
    )
    outcome = _validate(_proposal(quote=negative_text), [clause])
    assert not outcome.accepted
    assert "unsupported_negation" in {
        item.reason_code for item in outcome.reviews
    }


def test_negative_modality_phrase_is_accepted_as_part_of_the_rule() -> None:
    negative_minimum = (
        "A business loan in USD with an amount greater than USD 25,000 needs "
        "no fewer than two approvals from the credit committee."
    )
    clause = ValidatorClause(
        clause_id=CLAUSE.clause_id,
        page=1,
        section="4.1",
        text=negative_minimum,
        leaf_hash=CLAUSE.leaf_hash,
    )
    outcome = _validate(_proposal(quote=negative_minimum), [clause])
    assert not outcome.reviews and not outcome.rejections
    assert outcome.accepted[0].notes == [
        "negation is part of the supported modality phrase"
    ]


def test_deliberately_ambiguous_proposal_is_not_auto_accepted() -> None:
    outcome = _validate(
        _proposal(ambiguous=True, ambiguous_reason="two possible approval counts")
    )
    assert not outcome.accepted
    assert [item.reason_code for item in outcome.reviews] == ["ambiguous_proposal"]


def test_quote_must_be_unique_within_the_document() -> None:
    duplicate = ValidatorClause(
        clause_id="dhaka_lending_policy:v3:9.9",
        page=1,
        section="9.9",
        text=QUOTE,
        leaf_hash="ef" * 32,
    )
    outcome = _validate(_proposal(), [CLAUSE, duplicate])
    assert not outcome.accepted
    assert [item.reason_code for item in outcome.reviews] == ["ambiguous_evidence"]
