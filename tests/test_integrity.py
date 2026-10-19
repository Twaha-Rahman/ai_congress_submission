"""Merkle commitments, Ed25519 signatures and end-to-end evidence bundles."""

from __future__ import annotations

from meridian.contracts.common import CheckStatus, FindingType
from meridian.contracts.qa import TargetFacts
from meridian.integrity.canonical import leaf_hash, sha256_hex
from meridian.integrity.merkle import build_tree, inclusion_path, verify_inclusion
from meridian.integrity.signing import (
    PinnedKeyRegistry,
    Signer,
    TrustedKey,
    verify_signature,
    verify_with_registry,
)
from meridian.queries.evidence import build_bundle
from meridian.integrity.bundles import verify_bundle

from conftest import OfficeHarness, T_KNOWN, T_VALID, loan_target


def test_inclusion_proofs_verify_for_every_leaf_and_tree_size() -> None:
    payloads = [f"clause-{index}".encode() for index in range(1, 12)]
    for size in range(1, len(payloads) + 1):
        hashes, root = build_tree(payloads[:size])
        assert len(hashes) == size
        for index, digest in enumerate(hashes):
            siblings = inclusion_path(hashes, index)
            assert verify_inclusion(
                leaf_hash_value=digest,
                index=index,
                tree_size=size,
                siblings=siblings,
                root=root,
            )
            assert not verify_inclusion(
                leaf_hash_value=leaf_hash(b"tampered"),
                index=index,
                tree_size=size,
                siblings=siblings,
                root=root,
            )


def test_leaf_domain_separation() -> None:
    import hashlib

    payload = b'{"text":"retain five years"}'
    assert leaf_hash(payload) == hashlib.sha256(b"\x00" + payload).digest()
    assert leaf_hash(payload) != hashlib.sha256(payload).digest()


def test_signature_verification_requires_a_pinned_key() -> None:
    signer = Signer.generate(key_id="office-key", region="DHAKA")
    payload = b'{"rule":"two approvals"}'
    signature = signer.sign(payload)

    assert verify_signature(payload, signature, signer.public_key_hex)
    assert not verify_signature(b"tampered", signature, signer.public_key_hex)

    registry = PinnedKeyRegistry([signer.trusted_key()])
    assert verify_with_registry(payload, signature, "office-key", registry) == (True, None)
    assert verify_with_registry(payload, signature, "other-key", registry)[0] is False

    unpinned = PinnedKeyRegistry(
        [TrustedKey("other-key", "DHAKA", "00" * 32)]
    )
    assert verify_with_registry(payload, signature, "office-key", unpinned)[0] is False


def _verify(harness: OfficeHarness, bundle):
    return verify_bundle(
        bundle,
        registry=harness.registry,
        tenant_id=harness.store.tenant_id,
        now=T_KNOWN,
    )


def _status(report, name: str) -> CheckStatus:
    return next(check.status for check in report.checks if check.check == name)


def test_answer_bundle_verifies_and_tampering_is_detected(dhaka_full: OfficeHarness) -> None:
    target = TargetFacts(
        subject="loan_approval",
        amount_minor=4_000_000,
        currency="USD",
        loan_type="business",
        origin_office="DHAKA",
    )
    answer = dhaka_full.query(target, valid_at=T_VALID, known_at=T_KNOWN)
    assert answer.payload.status.value == "answered"

    bundle = build_bundle(dhaka_full.store, answer, now=T_KNOWN)
    report = _verify(dhaka_full, bundle)
    failed = [check for check in report.checks if check.status is CheckStatus.FAILED]
    assert not failed, failed
    assert _status(report, "answer_text_hash") is CheckStatus.PASSED
    assert _status(report, "answer_signature") is CheckStatus.PASSED
    assert _status(report, "claim_signature") is CheckStatus.PASSED
    assert _status(report, "manifest_signature") is CheckStatus.PASSED
    assert _status(report, "clause_inclusion") is CheckStatus.PASSED
    assert _status(report, "answer_binding") is CheckStatus.PASSED

    tampered_text = bundle.model_copy(deep=True)
    tampered_text.answer.answer_text += " Tampered."
    text_report = _verify(dhaka_full, tampered_text)
    assert _status(text_report, "answer_text_hash") is CheckStatus.FAILED
    assert _status(text_report, "answer_signature") is CheckStatus.FAILED

    tampered_claim = bundle.model_copy(deep=True)
    tampered_claim.claims[0].claim.evidence.quote = "an invented quote"
    claim_report = _verify(dhaka_full, tampered_claim)
    assert _status(claim_report, "claim_signature") is CheckStatus.FAILED

    tampered_manifest = bundle.model_copy(deep=True)
    tampered_manifest.manifests[0].manifest_payload["trusted_metadata"][
        "authority"
    ] = "procedure"
    manifest_report = _verify(dhaka_full, tampered_manifest)
    assert _status(manifest_report, "manifest_signature") is CheckStatus.FAILED

    tampered_clause = bundle.model_copy(deep=True)
    tampered_clause.manifests[0].clauses[0].text = "A fabricated clause."
    clause_report = _verify(dhaka_full, tampered_clause)
    assert _status(clause_report, "clause_inclusion") is CheckStatus.FAILED


def test_stale_guidance_is_published_for_the_demo_scenario(dhaka_full: OfficeHarness) -> None:
    stale = dhaka_full.store.list_findings(finding_type="stale_guidance")
    assert len(stale) == 1
    finding = stale[0]
    assert finding.payload.finding_type is FindingType.STALE_GUIDANCE
    assert finding.payload.severity.value == "high"
    assert finding in dhaka_full.store.list_findings(alert=True)
    assert (
        finding.payload.detail["affected_amount_range"]
        == "(USD 25,000.00, USD 50,000.00]"
    )
    assert finding.payload.staleness_link_revision_ids
    assert finding.review_state.value == "open"


def test_answer_explains_stale_guidance_with_citations(dhaka_full: OfficeHarness) -> None:
    answer = dhaka_full.query(loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    assert "The guidance published" in answer.payload.answer_text
    assert "2 approvals are required" in answer.payload.answer_text
    warning_codes = {warning.code.value for warning in answer.payload.warnings}
    assert "stale_guidance_present" in warning_codes
    assert all(citation.quote for citation in answer.payload.citations)
