"""Signed office-to-office exports, import isolation and cross-office comparison."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from meridian.contracts.common import ClaimOrigin, Sensitivity, Subject
from meridian.contracts.federation import (
    FederationExport,
    FederationSubquery,
    LoanTarget,
    RecordTarget,
)
from meridian.federation.exchange import (
    RemoteClaimConflict,
    build_export,
    import_export,
    remote_claim_views,
    target_fingerprint,
    verify_export,
)
from meridian.integrity.canonical import canonical_json_bytes, sha256_hex
from meridian.queries.engine import QueryEngine

from conftest import (
    OfficeHarness,
    T_KNOWN,
    T_VALID,
    record_target,
)

UTC = timezone.utc
JAN_10 = datetime(2026, 1, 10, tzinfo=UTC)
JAN_15 = datetime(2026, 1, 15, tzinfo=UTC)


def _loan_query() -> FederationSubquery:
    return FederationSubquery(
        request_id="req_test_loan",
        subject=Subject.LOAN_APPROVAL,
        target=LoanTarget(
            loan_type="business",
            currency="USD",
            origin_office="DHAKA",
            amount_minor=200_000_000,
        ),
        valid_at=T_VALID,
        known_at=T_KNOWN,
    )


def _record_query() -> FederationSubquery:
    return FederationSubquery(
        request_id="req_test_records",
        subject=Subject.RECORD_RETENTION,
        target=RecordTarget(
            record_class="loan_records",
            origin_office="DHAKA",
            processing_office="FRANKFURT",
            product="MTF_CROSS_OFFICE",
            starting_event="loan_closure",
        ),
        valid_at=T_VALID,
        known_at=T_KNOWN,
    )


def test_export_contains_only_structured_claims_and_verifies(
    dhaka_seeded: OfficeHarness,
) -> None:
    export = build_export(
        dhaka_seeded.store, query=_loan_query(), signer=dhaka_seeded.signer, now=T_KNOWN
    )
    payload, errors = verify_export(
        export,
        registry=dhaka_seeded.registry,
        tenant_id="meridian_demo",
        expected_origin="DHAKA",
    )
    assert errors == []
    assert payload is not None
    assert payload.origin_region.value == "DHAKA"
    assert payload.not_checked == ["clause_inclusion"]
    assert len(payload.claims) == 1

    # The restricted source is withheld and reported, not silently omitted.
    assert payload.withheld_restricted == 1
    assert "egress_denied_restricted_source" in payload.reason_codes

    claim = payload.claims[0]
    assert claim.rule.value == 2
    assert claim.source_kind == "pdf"
    serialized = canonical_json_bytes(payload)
    assert b"credit committee" not in serialized
    assert b"dhaka_credit_note_restricted" not in serialized


def test_tampered_export_fails_signature_verification(
    dhaka_seeded: OfficeHarness,
) -> None:
    export = build_export(
        dhaka_seeded.store, query=_loan_query(), signer=dhaka_seeded.signer, now=T_KNOWN
    )
    bad_payload = export.payload.model_copy(deep=True)
    bad_payload.claims[0].rule.value = 3
    bad_hash = sha256_hex(canonical_json_bytes(bad_payload))
    tampered = export.model_copy(update={"payload": bad_payload, "payload_hash": bad_hash})

    payload, errors = verify_export(
        tampered, registry=dhaka_seeded.registry, tenant_id="meridian_demo"
    )
    assert payload is None
    assert any("signature" in error for error in errors)


def test_restricted_only_export_is_blocked(dhaka_restricted_only: OfficeHarness) -> None:
    query = FederationSubquery(
        request_id="req_restricted_only",
        subject=Subject.LOAN_APPROVAL,
        target=LoanTarget(
            loan_type="business",
            currency="USD",
            origin_office="DHAKA",
            amount_minor=200_000_000,
        ),
        valid_at=JAN_15,
        known_at=JAN_10,
    )
    export = build_export(
        dhaka_restricted_only.store,
        query=query,
        signer=dhaka_restricted_only.signer,
        now=JAN_10,
    )
    assert export.payload.claims == []
    assert export.payload.withheld_restricted == 1
    assert export.payload.reason_codes == ["egress_denied_restricted_source"]


def test_import_is_namespaced_idempotent_and_conflict_aware(
    dhaka_seeded: OfficeHarness, frankfurt: OfficeHarness
) -> None:
    export = build_export(
        dhaka_seeded.store, query=_record_query(), signer=dhaka_seeded.signer, now=T_KNOWN
    )
    payload, errors = verify_export(
        export,
        registry=dhaka_seeded.registry,
        tenant_id="meridian_demo",
        expected_origin="DHAKA",
    )
    assert errors == [] and payload is not None

    assert import_export(frankfurt.store, export=export, payload=payload, received_at=T_KNOWN) == 1
    assert import_export(frankfurt.store, export=export, payload=payload, received_at=T_KNOWN) == 0

    query = _record_query()
    remote = remote_claim_views(
        frankfurt.store,
        subject="record_retention",
        target_fingerprint_value=target_fingerprint(query.target),
        valid_at=query.valid_at,
        source_known_at=query.known_at,
    )
    assert len(remote) == 1
    view = remote[0]
    assert view.revision.origin is ClaimOrigin.REMOTE
    assert view.revision.evidence.quote == ""
    assert view.revision.evidence.leaf_hash == "not_disclosed"
    assert view.revision.extraction.notes
    assert view.revision.source_identity.startswith("remote:")

    # A different signed payload for the same immutable revision must not overwrite it.
    conflicting_payload = payload.model_copy(deep=True)
    conflicting_payload.claims[0].claim_payload_hash = "00" * 32
    body = canonical_json_bytes(conflicting_payload)
    conflicting = FederationExport(
        payload=conflicting_payload,
        payload_hash=sha256_hex(body),
        signature=dhaka_seeded.signer.sign(body),
        key_id=dhaka_seeded.signer.key_id,
    )
    verified, conflict_errors = verify_export(
        conflicting, registry=dhaka_seeded.registry, tenant_id="meridian_demo"
    )
    assert conflict_errors == [] and verified is not None

    with pytest.raises(RemoteClaimConflict):
        import_export(
            frankfurt.store, export=conflicting, payload=verified, received_at=T_KNOWN
        )


def test_frankfurt_compares_imported_procedure_against_local_policy(
    dhaka_seeded: OfficeHarness, frankfurt: OfficeHarness
) -> None:
    export = build_export(
        dhaka_seeded.store, query=_record_query(), signer=dhaka_seeded.signer, now=T_KNOWN
    )
    payload, errors = verify_export(
        export, registry=dhaka_seeded.registry, tenant_id="meridian_demo"
    )
    assert errors == [] and payload is not None
    import_export(frankfurt.store, export=export, payload=payload, received_at=T_KNOWN)

    engine = QueryEngine(store=frankfurt.store, signer=frankfurt.signer)
    from meridian.contracts.qa import QueryRequest

    answer = engine.answer(
        QueryRequest(
            question="How long must cross-office loan records be retained?",
            target=record_target(),
            valid_at=T_VALID,
            known_at=T_KNOWN,
        ),
        known_at=T_KNOWN,
    )
    assert answer.payload.status.value == "answered"
    assert "retains records for exactly 5 years" in answer.payload.answer_text
    assert "does not meet the requirement of at least 7 years" in answer.payload.answer_text
    assert any(citation.remote for citation in answer.payload.citations)
    remote_citations = [c for c in answer.payload.citations if c.remote]
    assert remote_citations and all(c.quote is None for c in remote_citations)
    assert any(
        warning.code.value == "review_required" for warning in answer.payload.warnings
    )
