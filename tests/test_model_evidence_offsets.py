"""Model-supplied offsets cannot block or bypass source-grounded quote resolution."""
from dataclasses import replace
import json

import httpx
import pytest
from pydantic import ValidationError

from meridian.contracts.common import Mode, Subject
from meridian.contracts.extraction import EvidenceSpan
from meridian.contracts.manifest import SourceManifest
from meridian.extraction.openrouter import OpenRouterExtractionProvider
from meridian.extraction.provider import ClauseInput, ExtractionRequest
from meridian.extraction.validate import ValidatorClause, validate_proposal

QUOTE = "Employees must submit travel claims within 30 days."
PREFIX = "Travel policy:\n"
TEXT = PREFIX + QUOTE + "\nContact the travel desk."
SCOPE = {"kind": "policy", "description": "All employees", "attributes": {}}
MANIFEST = SourceManifest(
    tenant_id="test", region="DHAKA", source_identity="policy", version_label="v1",
    source_type="pdf", subject="general_policy", authority="policy", policy_family="travel",
    scope=SCOPE, effective_from="2026-01-01T00:00:00Z", effective_to=None,
    publication_time="2026-01-01T00:00:00Z", sensitivity="demo_shareable",
    permissions={"office_export": False, "hosted_model": True},
)
REQUEST = ExtractionRequest(
    tenant_id="test", region="DHAKA", source_identity="policy", version_label="v1",
    source_type=MANIFEST.source_type, subject=Subject.GENERAL_POLICY, authority="policy",
    content_sha256="0" * 64, manifest_scope_summary=json.dumps(SCOPE),
    clauses=[ClauseInput("policy:v1:3.1", 1, "3.1", TEXT)], mode=Mode.LIVE,
    prompt_version="general-extract-v1", schema_version="1", request_id="offline-offset-test",
)
CLAUSE = ValidatorClause("policy:v1:3.1", 1, "3.1", TEXT, "ab" * 32)


def extract(evidence, *, count=1):
    data = {"rules": [{
        "subject": "general_policy", "scope": SCOPE,
        "rule": {"kind": "policy_statement", "statement": evidence.get("quote", QUOTE),
                 "action": evidence.get("quote", QUOTE), "modality": "required"},
        "evidence": evidence,
    } for _ in range(count)]}
    provider = OpenRouterExtractionProvider(base_url="https://openrouter.test", model="offline-test", api_key="test",
        max_attempts=1, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(data)}}],
        })))
    return provider.extract(REQUEST)


def validate(result):
    assert result.ok, result.error_detail
    return validate_proposal(result.proposal, manifest=MANIFEST, clauses=[CLAUSE], manifest_root="cd" * 32)


@pytest.mark.parametrize("offsets", [(0, 0), (9, 3), (-1, 0), (1, None)])
def test_26_model_offset_placeholders_are_replaced_with_exact_source_positions(offsets):
    result = extract({"page": 1, "section": "3.1", "quote": QUOTE,
                      "start_char": offsets[0], "end_char": offsets[1]}, count=26)
    outcome = validate(result)
    assert len(outcome.accepted) == 26 and not outcome.reviews and not outcome.rejections
    for verified in outcome.accepted:
        assert verified.evidence.start_char == len(PREFIX)
        assert verified.evidence.end_char == len(PREFIX) + len(QUOTE)
        assert TEXT[verified.evidence.start_char:verified.evidence.end_char] == QUOTE
        assert verified.evidence.leaf_hash == CLAUSE.leaf_hash
    assert all(r.evidence.start_char is None and r.evidence.end_char is None for r in result.proposal.rules)


def test_ignoring_model_offsets_does_not_accept_a_fabricated_quote():
    outcome = validate(extract({"page": 1, "section": "3.1", "quote": "Employees may bypass all policy checks.",
                                "start_char": 0, "end_char": 0}))
    assert not outcome.accepted
    assert [r.reason_code for r in outcome.rejections] == ["hallucinated_evidence"]


def test_location_hints_still_need_to_match_the_source():
    outcome = validate(extract({"page": 2, "section": "3.1", "quote": QUOTE,
                                "start_char": 0, "end_char": 0}))
    assert not outcome.accepted
    assert [r.reason_code for r in outcome.reviews] == ["evidence_locator_mismatch"]


def test_hosted_schema_does_not_ask_either_extraction_path_for_offsets():
    provider = OpenRouterExtractionProvider(base_url="https://openrouter.test", model="offline-test", api_key="test")
    for subject in (Subject.GENERAL_POLICY, Subject.LOAN_APPROVAL):
        schema = provider.build_body(replace(REQUEST, subject=subject))["response_format"]["json_schema"]["schema"]
        evidence = schema["$defs"]["EvidenceQuote"]
        assert set(evidence["properties"]) == {"quote", "page", "section"}
        assert "EvidenceSpan" not in schema["$defs"]
    # The domain contract retains its strict invariant; only untrusted hosted
    # hints are discarded before creating one of these objects.
    with pytest.raises(ValidationError, match="end_char"):
        EvidenceSpan(quote=QUOTE, start_char=0, end_char=0)


def test_unknown_evidence_fields_are_still_schema_errors():
    result = extract({"quote": QUOTE, "start_char": 0, "end_char": 0, "verified": True})
    assert not result.ok and result.error_code.value == "schema_violation"
