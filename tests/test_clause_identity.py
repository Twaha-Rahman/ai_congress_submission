"""Repeated PDF sections retain distinct passages, evidence and commitments."""
from datetime import datetime, timezone

import pymupdf
import pytest

from meridian.contracts.common import Mode
from meridian.contracts.extraction import ExtractionProposal
from meridian.contracts.manifest import SourceManifest
from meridian.extraction.provider import ProviderResult
from meridian.ingestion.pipeline import clause_id_for, clause_ids_for, ingest_prepared, prepare_pdf_source
from meridian.integrity.merkle import inclusion_path, verify_inclusion


@pytest.mark.parametrize("repeat_heading", [False, True])
def test_pdf_repeated_section_persists_every_passage_and_its_proof(dhaka, monkeypatch, repeat_heading):
    manifest = SourceManifest(
        tenant_id=dhaka.store.tenant_id, region="DHAKA", source_identity="multi_page_policy",
        version_label="v1", source_type="pdf", subject="general_policy", authority="policy",
        policy_family="security", scope={"kind": "policy", "description": "All contractors", "attributes": {}},
        publication_time="2026-01-01T00:00:00Z", effective_from="2026-01-01T00:00:00Z", effective_to=None,
        sensitivity="demo_shareable", permissions={"office_export": False, "hosted_model": False},
    )
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), "5.3 Security induction\nContractors must complete security induction before receiving an access card.")
        header = "5.3 Continued security induction" if repeat_heading else "Corporate Security Procedure\nContinuation information"
        document.new_page().insert_text((40, 40), header + "\nSecurity induction applies to all contractors.\n6 Contacts\nContact the security desk.")
        prepared = prepare_pdf_source(manifest, document.tobytes())
    repeated = [c for c in prepared.parsed.clauses if c.section == "5.3"]
    assert len(repeated) == 2 and [c.page for c in repeated] == [1, 2]
    # One evidence quote is sufficient to exercise the real source transaction;
    # all original passages must persist, even those without extracted claims.
    text = repeated[0].text
    proposal = ExtractionProposal.model_validate({"rules": [{
        "subject": "general_policy", "scope": manifest.scope.model_dump(),
        "rule": {"kind": "policy_statement", "statement": text, "action": text, "modality": "required"},
        "evidence": {"quote": text},
    }]})
    monkeypatch.setattr(dhaka.service, "extract", lambda request: ProviderResult(mode=Mode.REPLAY, provider="offline-test", proposal=proposal))
    outcome = ingest_prepared(dhaka.store, prepared, mode=Mode.REPLAY, service=dhaka.service,
                              signer=dhaka.signer, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert outcome.ok, outcome.error_detail
    rows = dhaka.store.clauses_for_source(outcome.source_id)
    assert len(rows) == len(prepared.parsed.clauses)
    assert len({c.clause_id for c in rows}) == len(rows)
    assert [c.text for c in rows] == [c.text for c in prepared.parsed.clauses]
    assert [c.clause_id for c in rows] == clause_ids_for(manifest, prepared.parsed)
    assert rows[0].clause_id == clause_id_for(manifest, 0, "5.3")
    source = dhaka.store.get_source(outcome.source_id)
    hashes = [bytes.fromhex(c.leaf_hash) for c in rows]
    for i, digest in enumerate(hashes):
        assert verify_inclusion(leaf_hash_value=digest, index=i, tree_size=len(rows),
                                siblings=inclusion_path(hashes, i), root=bytes.fromhex(source.merkle_root))
    claims = dhaka.store.claims_for_source(outcome.source_id)
    assert len(claims) == 1
    assert claims[0].payload.source_clause_id == rows[0].clause_id
    assert claims[0].payload.evidence.quote == text
    # Re-delivery stays idempotent, with the same stored IDs and source version.
    duplicate = ingest_prepared(dhaka.store, prepared, mode=Mode.REPLAY, service=dhaka.service, signer=dhaka.signer)
    assert duplicate.duplicate and duplicate.source_id == outcome.source_id
