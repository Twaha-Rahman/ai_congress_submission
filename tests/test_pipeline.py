"""Transactional ingestion guarantees and the complete replay pipeline."""

from __future__ import annotations

import pytest

from meridian.contracts.common import CheckStatus, Mode
from meridian.contracts.manifest import SourceManifest
from meridian.ingestion.pipeline import (
    VersionPayloadMismatch,
    ingest_prepared,
    prepare_pdf_source,
)
from meridian.integrity.bundles import verify_bundle
from meridian.queries.evidence import build_bundle

from conftest import (
    DEMO_POLICY_V3,
    FIXTURES,
    OfficeHarness,
    T_KNOWN,
    T_POLICY_V3,
    T_SLACK,
    T_VALID,
    loan_target,
)


def test_duplicate_delivery_creates_no_new_version_or_findings(
    dhaka: OfficeHarness,
) -> None:
    first = dhaka.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)
    counts = dhaka.store.counts()
    second = dhaka.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)

    assert first.created and not first.duplicate
    assert second.duplicate and not second.created
    assert second.source_id == first.source_id
    assert dhaka.store.counts() == counts


def test_changed_bytes_under_an_existing_version_are_rejected(
    dhaka: OfficeHarness,
) -> None:
    dhaka.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)
    manifest = SourceManifest.model_validate_json(
        (FIXTURES / DEMO_POLICY_V3[1]).read_text("utf-8")
    )
    tampered = (FIXTURES / "tampered/dhaka_lending_policy_v3_modified_text.pdf").read_bytes()
    prepared = prepare_pdf_source(manifest, tampered)

    with pytest.raises(VersionPayloadMismatch):
        ingest_prepared(
            dhaka.store,
            prepared,
            mode=Mode.REPLAY,
            service=dhaka.service,
            signer=dhaka.signer,
            now=T_SLACK,
        )


def test_complete_pipeline_publishes_finding_and_verifiable_answer(
    dhaka_full: OfficeHarness,
) -> None:
    findings = dhaka_full.store.list_findings(alert=True)
    assert any(
        finding.payload.finding_type.value == "stale_guidance"
        for finding in findings
    )

    answer = dhaka_full.query(
        loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN
    )
    assert answer.payload.status.value == "answered"
    assert answer.payload.citations
    assert answer.payload.warnings

    bundle = build_bundle(dhaka_full.store, answer, now=T_KNOWN)
    report = verify_bundle(
        bundle,
        registry=dhaka_full.registry,
        tenant_id=dhaka_full.store.tenant_id,
        now=T_KNOWN,
    )
    failed = [check for check in report.checks if check.status is CheckStatus.FAILED]
    assert failed == []
    assert report.checks
