"""Focused regression tests for the review's trust-boundary repairs."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from meridian.api_common import ApiError
from meridian.contracts.common import CheckStatus, Mode, RuleKind
from meridian.contracts.extraction import ExtractionProposal
from meridian.contracts.manifest import SourceManifest
from meridian.contracts.qa import QueryRequest
from meridian.extraction.validate import ValidatorClause, validate_proposal
from meridian.ingestion.pipeline import VersionPayloadMismatch, ingest_prepared, prepare_pdf_source
from meridian.integrity.bundles import verify_bundle
from meridian.queries.evidence import build_bundle
from meridian.security.auth import AuthorizationError, Permission, Principal, Role

from conftest import (
    DEMO_POLICY_V2,
    DEMO_POLICY_V3,
    DEMO_RESTRICTED,
    FIXTURES,
    T_KNOWN,
    T_POLICY_V2,
    T_POLICY_V3,
    T_VALID,
    OfficeHarness,
    loan_target,
    make_office,
    settings_for,
)


def test_bundle_manifest_wrapper_and_claim_binding_tampering_fail(
    dhaka_full: OfficeHarness,
) -> None:
    answer = dhaka_full.query(loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    bundle = build_bundle(dhaka_full.store, answer, now=T_KNOWN)

    wrapper = bundle.model_copy(deep=True)
    wrapper.manifests[0].source_sha256 = "00" * 32
    report = verify_bundle(wrapper, registry=dhaka_full.registry, tenant_id="meridian_demo")
    assert report.summary()["manifest_binding"] == CheckStatus.FAILED.value

    missing_claim = bundle.model_copy(deep=True)
    cited = {citation.claim_revision_id for citation in missing_claim.answer.citations}
    missing_claim.claims = [
        entry for entry in missing_claim.claims if entry.claim.revision_id not in cited
    ]
    report = verify_bundle(missing_claim, registry=dhaka_full.registry, tenant_id="meridian_demo")
    assert report.summary()["answer_binding"] == CheckStatus.FAILED.value

    no_proof = bundle.model_copy(deep=True)
    no_proof.claims[0].clause_proof = None
    no_proof.claims[0].clause_disclosed = False
    report = verify_bundle(no_proof, registry=dhaka_full.registry, tenant_id="meridian_demo")
    assert report.summary()["claim_binding"] == CheckStatus.FAILED.value


def test_bundle_cannot_rebind_a_proof_to_forged_disclosed_text(
    dhaka_full: OfficeHarness,
) -> None:
    answer = dhaka_full.query(loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    bundle = build_bundle(dhaka_full.store, answer, now=T_KNOWN)
    entry = bundle.manifests[0]
    clause = entry.clauses[0]
    clause.text += " forged"

    # Even a self-consistent replacement proof cannot change the root authenticated
    # by the signed manifest or the quote authenticated by the signed claim.
    proof = entry.clause_proofs[0]
    proof.tree_size = 1
    proof.leaf_index = 0
    proof.siblings = []
    proof.merkle_root = proof.leaf_hash
    report = verify_bundle(bundle, registry=dhaka_full.registry, tenant_id="meridian_demo")
    assert report.summary()["clause_inclusion"] == CheckStatus.FAILED.value
    assert report.summary()["claim_binding"] == CheckStatus.FAILED.value


def test_immutable_version_rejects_metadata_only_and_manifest_changes(
    dhaka: OfficeHarness,
) -> None:
    dhaka.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)
    manifest = SourceManifest.model_validate_json(
        (FIXTURES / DEMO_POLICY_V3[1]).read_text("utf-8")
    )
    metadata_copy = (FIXTURES / "tampered/dhaka_lending_policy_v3_metadata_only.pdf").read_bytes()
    prepared = prepare_pdf_source(manifest, metadata_copy)
    with pytest.raises(VersionPayloadMismatch, match="different original bytes"):
        ingest_prepared(
            dhaka.store, prepared, mode=Mode.REPLAY, service=dhaka.service,
            signer=dhaka.signer, now=T_KNOWN,
        )

    changed_manifests = [
        manifest.model_copy(
            update={"effective_from": datetime(2026, 2, 2, tzinfo=timezone.utc)}
        ),
        manifest.model_copy(
            update={
                "permissions": manifest.permissions.model_copy(
                    update={"hosted_model": False}
                )
            }
        ),
    ]
    for changed in changed_manifests:
        same_bytes = prepare_pdf_source(changed, (FIXTURES / DEMO_POLICY_V3[0]).read_bytes())
        with pytest.raises(VersionPayloadMismatch, match="trusted manifest metadata"):
            ingest_prepared(
                dhaka.store, same_bytes, mode=Mode.REPLAY, service=dhaka.service,
                signer=dhaka.signer, now=T_KNOWN,
            )


def test_hosted_model_denial_makes_no_http_request_or_cache_write(
    dhaka: OfficeHarness, tmp_path: Path,
) -> None:
    from dataclasses import replace
    import httpx
    from meridian.extraction.service import ModelStageService
    from conftest import DEMO_POLICY_V3

    request = dhaka.prepare(*DEMO_POLICY_V3)
    from meridian.extraction.provider import ClauseInput, ExtractionRequest
    from meridian.ingestion.pipeline import clause_id_for
    from meridian.contracts.common import PROMPT_VERSION, SCHEMA_VERSION

    extraction = ExtractionRequest(
        tenant_id=request.manifest.tenant_id,
        region=request.manifest.region.value,
        source_identity=request.manifest.source_identity,
        version_label=request.manifest.version_label,
        source_type=request.manifest.source_type,
        subject=request.manifest.subject,
        authority=request.manifest.authority.value,
        content_sha256=request.content_sha256,
        manifest_scope_summary=request.manifest.scope.model_dump_json(),
        clauses=[
            ClauseInput(
                clause_id=clause_id_for(request.manifest, i, clause.section),
                page=clause.page,
                section=clause.section,
                text=clause.text,
            )
            for i, clause in enumerate(request.parsed.clauses)
        ],
        mode=Mode.LIVE,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        request_id="req_policy_denied",
        hosted_model_allowed=False,
    )
    calls: list[httpx.Request] = []
    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(200, json={})

    settings = replace(
        dhaka.settings,
        llm_model="test/model",
        llm_api_key="test-key",
        fixtures_dir=tmp_path / "fixtures",
    )
    events: list[dict] = []
    service = ModelStageService(
        settings,
        transport=httpx.MockTransport(handler),
        write_cache=True,
        egress_sink=events.append,
    )
    result = service.extract(extraction)
    assert result.error_code.value == "egress_denied"
    assert calls == []
    cache_path = tmp_path / "fixtures" / "cache" / "dhaka"
    assert not list(cache_path.glob("**/*.json")) if cache_path.exists() else True
    assert events[0]["outcome"] == "blocked"
    assert events[0]["raw_source_bytes"] == 0

    local_settings = replace(
        settings,
        llm_base_url="http://127.0.0.1:9999/v1",
        llm_local_endpoint_approved=True,
    )
    local_calls: list[httpx.Request] = []
    local_service = ModelStageService(
        local_settings,
        transport=httpx.MockTransport(
            lambda request: (local_calls.append(request) or httpx.Response(503))
        ),
    )
    local_service.extract(extraction)
    assert len(local_calls) == 1


def test_comparison_and_claim_export_block_nonexportable_local_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meridian import office_api
    from meridian.contracts.common import Mode
    from meridian.contracts.qa import QueryRequest
    from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source
    from meridian.ingestion.worker import OfficeWorker
    from meridian.office_api.main import OfficeRuntime
    from meridian.security.auth import PrincipalRegistry
    from tests.test_federation import _record_query
    from conftest import DEMO_FRANKFURT, record_target

    office = make_office(tmp_path / "nonexport-office", region="FRANKFURT")
    manifest = SourceManifest.model_validate_json(
        (FIXTURES / DEMO_FRANKFURT[1]).read_text("utf-8")
    )
    manifest = manifest.model_copy(
        update={
            "permissions": manifest.permissions.model_copy(
                update={"office_export": False}
            )
        }
    )
    prepared = prepare_pdf_source(
        manifest, (FIXTURES / DEMO_FRANKFURT[0]).read_bytes()
    )
    outcome = ingest_prepared(
        office.store, prepared, mode=Mode.REPLAY, service=office.service,
        signer=office.signer, now=T_POLICY_V2,
    )
    assert outcome.ok
    registry = PrincipalRegistry.from_file(FIXTURES.parent / "config" / "principals.json")
    runtime = OfficeRuntime(
        settings=office.settings, registry=registry, trusted_keys=office.registry,
        signer=office.signer, store=office.store,
        worker=OfficeWorker(store=office.store, settings=office.settings, signer=office.signer),
    )
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = office_api.main.create_app(office.settings)
    route = lambda path: next(  # noqa: E731
        item.endpoint for item in app.routes if getattr(item, "path", None) == path
    )
    principal = Principal(
        principal_id="frankfurt_service", tenant_id="meridian_demo", office="FRANKFURT",
        role=Role.OFFICE_SERVICE,
        permissions=frozenset({Permission.FEDERATION_SERVE, Permission.QUERY_LOCAL}),
        display_name="service",
    )

    class RequestBody:
        def __init__(self, body):
            self.body = body
        async def json(self):
            return self.body

    import asyncio
    export_response = asyncio.run(
        route("/v1/federation/claims")(
            request=RequestBody(_record_query().model_dump(mode="json")),
            principal=principal,
        )
    )
    assert export_response["export"]["payload"]["claims"] == []
    assert "egress_denied_source_permission" in export_response["summary"]["reason_codes"]

    with pytest.raises(ApiError) as denied:
        asyncio.run(
            route("/v1/comparisons")(
                request=RequestBody(
                    QueryRequest(
                        question="retention", target=record_target(),
                        valid_at=T_VALID, known_at=T_KNOWN,
                    ).model_dump(mode="json")
                ),
                principal=principal,
            )
        )
    assert denied.value.code.value == "egress_denied"
    summary = office.store.summarize_egress()
    assert summary.blocked_exports >= 1


def test_gateway_rejects_tampered_comparison_projection(
    frankfurt: OfficeHarness, tmp_path: Path,
) -> None:
    import httpx
    from meridian.contracts.qa import QueryRequest
    from meridian.gateway_api.orchestrator import GatewayOrchestrator, OfficeUnavailable, RelayLog
    from meridian.integrity.canonical import canonical_json_bytes, sha256_hex
    from conftest import record_target

    record = frankfurt.query(record_target(), valid_at=T_VALID, known_at=T_KNOWN)
    projection = record.payload.model_copy(deep=True)
    projection.citations = [
        citation.model_copy(update={"quote": None}) for citation in projection.citations
    ]
    projection.model_metadata = {
        **projection.model_metadata,
        "export_projection": "comparison-v1",
        "local_answer_hash": record.payload_hash,
        "local_answer_signature": record.signature,
    }
    raw = canonical_json_bytes(projection)
    tampered = projection.model_copy(update={"answer_text": projection.answer_text + " forged"})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "answer": tampered.model_dump(mode="json"),
            "answer_hash": sha256_hex(raw),
            "answer_signature": frankfurt.signer.sign(raw),
            "answer_key_id": frankfurt.signer.key_id,
            "local_answer_id": record.payload.answer_id,
            "local_answer_hash": record.payload_hash,
        })

    gateway = GatewayOrchestrator(
        tenant_id="meridian_demo", office_urls={"FRANKFURT": "http://frankfurt"},
        office_tokens={}, registry=frankfurt.registry,
        relay_log=RelayLog(tmp_path / "tamper-relay.jsonl"),
        transport=httpx.MockTransport(handler),
    )
    request = QueryRequest(
        question="retention", target=record_target(), valid_at=T_VALID, known_at=T_KNOWN
    )
    with pytest.raises(OfficeUnavailable, match="hash mismatch"):
        gateway.comparison_at_office("FRANKFURT", request)


def test_office_query_rejects_other_office_and_answers_reauthorize_sources(
    dhaka: OfficeHarness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meridian import office_api
    from meridian.ingestion.worker import OfficeWorker
    from meridian.office_api.main import OfficeRuntime
    from meridian.security.auth import PrincipalRegistry

    dhaka.ingest(DEMO_RESTRICTED, now=T_POLICY_V2)
    dhaka.ingest(DEMO_POLICY_V2, now=T_POLICY_V2)
    registry = PrincipalRegistry.from_file(FIXTURES.parent / "config" / "principals.json")
    runtime = OfficeRuntime(
        settings=dhaka.settings,
        registry=registry,
        trusted_keys=dhaka.registry,
        signer=dhaka.signer,
        store=dhaka.store,
        worker=OfficeWorker(store=dhaka.store, settings=dhaka.settings, signer=dhaka.signer),
    )
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = office_api.main.create_app(dhaka.settings)

    def endpoint(path: str, method: str = "GET"):
        return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path and method in route.methods)

    def principal(office: str, permissions: set[Permission]) -> Principal:
        return Principal(
            principal_id="test", tenant_id="meridian_demo", office=office,
            role=Role.REVIEWER, permissions=frozenset(permissions), display_name="test",
        )

    cross_office = principal("FRANKFURT", {Permission.QUERY_LOCAL, Permission.READ_LOCAL})
    class Body:
        async def json(self):
            return QueryRequest(
                question="rule", target=loan_target(200_000_000),
                valid_at=T_VALID, known_at=T_KNOWN,
            ).model_dump(mode="json")
    with pytest.raises(AuthorizationError):
        import asyncio
        asyncio.run(endpoint("/v1/queries", "POST")(request=Body(), principal=cross_office))

    privileged = principal(
        "DHAKA", {Permission.QUERY_LOCAL, Permission.READ_LOCAL, Permission.READ_RESTRICTED}
    )
    import asyncio
    created = asyncio.run(endpoint("/v1/queries", "POST")(request=Body(), principal=privileged))
    answer_id = created["answer"]["answer_id"]
    reader = principal("DHAKA", {Permission.READ_LOCAL, Permission.QUERY_LOCAL})
    with pytest.raises(ApiError) as error:
        endpoint("/v1/answers/{answer_id}")(answer_id=answer_id, principal=reader)
    assert error.value.code.value == "not_found"

    restricted_source = dhaka.store.find_source_version(
        "dhaka_credit_note_restricted", "v1"
    )
    assert restricted_source is not None
    dhaka.store.insert_claim_review(
        source_id=restricted_source.source_id,
        reason_code="restricted_test",
        detail={"detail": "must remain hidden"},
    )
    public_revision_ids = [
        record.payload.revision_id
        for record in dhaka.store.claims_for_source(
            dhaka.store.find_source_version("dhaka_lending_policy", "v2").source_id
        )
    ]
    dhaka.store.insert_claim_review(
        source_id=restricted_source.source_id,
        reason_code="pending_replacement",
        subject="loan_approval",
        detail={
            "affected_revision_ids": public_revision_ids,
            "effective_from": "2026-02-01T00:00:00Z",
        },
        created_at=T_POLICY_V2,
    )
    dhaka.store.create_job(
        kind="pdf", mode=Mode.REPLAY,
        request={"manifest": {"sensitivity": "restricted"}},
    )
    assert endpoint("/v1/claims/reviews")(principal=reader)["reviews"] == []
    assert endpoint("/v1/jobs")(limit=50, principal=reader)["jobs"] == []
    assert endpoint("/v1/findings")(principal=reader)["findings"] == []
    assert endpoint("/v1/findings")(principal=privileged)["findings"]

    public_answer = asyncio.run(
        endpoint("/v1/queries", "POST")(request=Body(), principal=reader)
    )
    assert not any(
        warning["code"] == "pending_replacement"
        for warning in public_answer["answer"]["warnings"]
    )
    public_answer_id = public_answer["answer"]["answer_id"]
    lineage = endpoint("/v1/answers/{answer_id}/lineage")(
        answer_id=public_answer_id, principal=reader
    )["lineage"]
    restricted_revision_ids = {
        record.payload.revision_id
        for record in dhaka.store.claims_for_source(restricted_source.source_id)
    }
    restricted_finding_ids = {
        finding.payload.finding_id
        for finding in dhaka.store.list_findings()
        if restricted_revision_ids.intersection(finding.payload.claim_revision_ids)
    }
    assert restricted_finding_ids
    assert not any(
        node["node_id"] in {f"finding:{finding_id}" for finding_id in restricted_finding_ids}
        for node in lineage["nodes"]
    )


def test_r5_operator_and_money_bound_direction_are_not_reversed() -> None:
    # The proposal claims a minimum, but source wording is explicitly a maximum.
    from conftest import FIXTURES
    from tests.test_validation import _proposal, _validate, CLAUSE
    max_text = "A business loan in USD up to USD 25,000 needs no more than two approvals."
    clause = ValidatorClause(
        clause_id=CLAUSE.clause_id, page=1, section="4.1", text=max_text, leaf_hash=CLAUSE.leaf_hash
    )
    proposed = _proposal(
        quote=max_text,
        value=2,
        kind=RuleKind.REQUIRED_MINIMUM,
        scope={
            "kind": "loan", "loan_type": "business", "currency": "USD",
            "origin_office": "DHAKA",
            "amount_minor": {
                "lower": 0, "lower_inclusive": True,
                "upper": 2_500_000, "upper_inclusive": True,
            },
        },
    )
    result = validate_proposal(
        proposed, manifest=SourceManifest.model_validate_json(
            (FIXTURES / "manifests/dhaka_lending_policy_v3.json").read_text()
        ), clauses=[clause], manifest_root="cd" * 32,
    )
    assert not result.accepted
    assert {item.reason_code for item in result.reviews} & {
        "operator_direction_mismatch",
        "amount_direction_mismatch",
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_r6_retention_conflict_aggregates_every_applicable_requirement(
    tmp_path: Path, reverse: bool,
) -> None:
    from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source

    eval_root = FIXTURES / "evaluation"
    office = make_office(tmp_path / f"retention-{reverse}", fixtures_dir=eval_root)
    sources = [
        ("eval_records_min_seven_v1", "min_seven"),
        ("eval_records_ceiling_five_v1", "ceiling_five"),
        ("eval_records_procedure_five_v1", "procedure_five"),
    ]
    if reverse:
        sources.reverse()
    for stem, _label in sources:
        manifest_path = eval_root / "manifests" / f"{stem}.json"
        manifest = SourceManifest.model_validate_json(manifest_path.read_text("utf-8"))
        pdf_path = next((eval_root / "documents").rglob(f"{stem}.pdf"))
        prepared = prepare_pdf_source(manifest, pdf_path.read_bytes())
        outcome = ingest_prepared(
            office.store, prepared, mode=Mode.REPLAY, service=office.service,
            signer=office.signer, now=T_POLICY_V2,
        )
        assert outcome.ok, (outcome.error_code, outcome.error_detail)

    from conftest import record_target
    answer = office.query(record_target(), valid_at=T_VALID, known_at=T_KNOWN)
    assert answer.payload.status.value == "needs_review"
    assert "mutually unsatisfiable" in answer.payload.answer_text
    assert len({citation.claim_revision_id for citation in answer.payload.citations}) == 3


@pytest.mark.parametrize("accepted_count", [0, 1])
def test_incomplete_replacement_keeps_old_policy_and_marks_query_pending(
    tmp_path: Path, accepted_count: int,
) -> None:
    fixture_copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fixture_copy)
    replay_path = fixture_copy / "replay/dhaka/dhaka_lending_policy__v3.json"
    payload = json.loads(replay_path.read_text("utf-8"))
    payload["proposal"]["rules"] = payload["proposal"]["rules"][:accepted_count]
    replay_path.write_text(json.dumps(payload), encoding="utf-8")

    office = make_office(tmp_path / f"office-{accepted_count}", fixtures_dir=fixture_copy)
    office.ingest(DEMO_POLICY_V2, now=T_POLICY_V2)
    result = office.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)
    assert result.review_reasons == ["pending_replacement"]

    v2 = office.store.find_source_version("dhaka_lending_policy", "v2")
    assert v2 is not None
    assert all(record.system_to is None for record in office.store.claims_for_source(v2.source_id))
    historical = office.query(
        loan_target(4_000_000),
        valid_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        known_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert historical.payload.status.value == "answered"
    assert not any(w.code.value == "pending_replacement" for w in historical.payload.warnings)
    query = office.query(loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    assert query.payload.status.value == "needs_review"
    assert any(warning.code.value == "pending_replacement" for warning in query.payload.warnings)

    pending = office.store.pending_replacements(known_at=T_KNOWN)
    assert pending
    resolved_at = T_KNOWN + timedelta(seconds=1)
    assert office.store.resolve_claim_review(pending[0]["review_id"], resolved_at=resolved_at)
    # A historical cutoff before resolution still sees the pending state; a later
    # cutoff does not, without mutating the earlier snapshot's result.
    still_pending = office.query(loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    resolved = office.query(loan_target(4_000_000), valid_at=T_VALID, known_at=resolved_at)
    assert still_pending.payload.status.value == "needs_review"
    assert resolved.payload.status.value == "answered"


def test_r7_historical_and_other_context_exports_do_not_replace_current_snapshot(
    dhaka_full: OfficeHarness, frankfurt: OfficeHarness,
) -> None:
    from datetime import timedelta
    from meridian.contracts.common import OfficeRegion
    from meridian.contracts.federation import FederationExport
    from meridian.federation.exchange import (
        StaleRemoteSnapshot,
        build_export,
        import_export as persist_export,
        remote_claim_views,
        select_remote_snapshots,
        snapshot_id_for,
        target_fingerprint,
        verify_export,
    )

    from tests.test_federation import _record_query
    first = build_export(dhaka_full.store, query=_record_query(), signer=dhaka_full.signer, now=T_KNOWN)
    verified, errors = verify_export(first, registry=dhaka_full.registry, tenant_id="meridian_demo")
    assert not errors and verified is not None
    persist_export(frankfurt.store, export=first, payload=verified, received_at=T_KNOWN)
    old_id = snapshot_id_for(verified, first.payload_hash)

    historical_query = _record_query().model_copy(
        update={"request_id": "req_historical_empty", "known_at": T_POLICY_V2}
    )
    historical = build_export(
        dhaka_full.store, query=historical_query, signer=dhaka_full.signer,
        now=T_KNOWN + timedelta(seconds=1),
    )
    assert historical.payload.claims == []
    # The historical empty response arrives after the current response. It must not
    # replace current source knowledge merely because its recipient receipt is newer.
    persist_export(
        frankfurt.store, export=historical, payload=historical.payload,
        received_at=T_KNOWN + timedelta(seconds=2),
    )

    different_target_query = _record_query().model_copy(
        update={
            "request_id": "req_other_target",
            "target": _record_query().target.model_copy(
                update={"processing_office": OfficeRegion.DHAKA}
            ),
            "target_fingerprint": None,
        }
    )
    different_target = build_export(
        dhaka_full.store, query=different_target_query, signer=dhaka_full.signer,
        now=T_KNOWN + timedelta(seconds=3),
    )
    assert different_target.payload.claims == []
    persist_export(
        frankfurt.store, export=different_target, payload=different_target.payload,
        received_at=T_KNOWN + timedelta(seconds=4),
    )

    historical_valid_query = _record_query().model_copy(
        update={
            "request_id": "req_historical_valid",
            "valid_at": T_POLICY_V2,
        }
    )
    historical_valid = build_export(
        dhaka_full.store, query=historical_valid_query, signer=dhaka_full.signer,
        now=T_KNOWN + timedelta(seconds=5),
    )
    persist_export(
        frankfurt.store, export=historical_valid, payload=historical_valid.payload,
        received_at=T_KNOWN + timedelta(seconds=6),
    )

    from meridian.integrity.canonical import canonical_json_bytes, sha256_hex
    current_query = _record_query()
    latest = remote_claim_views(
        frankfurt.store,
        subject="record_retention",
        known_at=T_KNOWN + timedelta(seconds=5),
        target_fingerprint_value=target_fingerprint(current_query.target),
        valid_at=current_query.valid_at,
        source_known_at=current_query.known_at,
    )
    assert len(latest) == 1
    assert latest[0].revision.revision_id == verified.claims[0].claim_revision_id
    selected_old = select_remote_snapshots(
        frankfurt.store,
        subject="record_retention",
        known_at=T_KNOWN + timedelta(seconds=5),
        snapshot_ids=[old_id],
        target_fingerprint_value=target_fingerprint(current_query.target),
        valid_at=current_query.valid_at,
        source_known_at=current_query.known_at,
    )
    assert [row["snapshot_id"] for row in selected_old] == [old_id]
    historical_valid_id = snapshot_id_for(
        historical_valid.payload, historical_valid.payload_hash
    )
    selected_historical_valid = select_remote_snapshots(
        frankfurt.store,
        subject="record_retention",
        known_at=T_KNOWN + timedelta(seconds=7),
        snapshot_ids=[historical_valid_id],
        target_fingerprint_value=target_fingerprint(current_query.target),
        valid_at=T_POLICY_V2,
        source_known_at=current_query.known_at,
    )
    assert [row["snapshot_id"] for row in selected_historical_valid] == [
        historical_valid_id
    ]

    from concurrent.futures import ThreadPoolExecutor

    def select_current():
        return select_remote_snapshots(
            frankfurt.store,
            subject="record_retention",
            known_at=T_KNOWN + timedelta(seconds=7),
            target_fingerprint_value=target_fingerprint(current_query.target),
            valid_at=current_query.valid_at,
            source_known_at=current_query.known_at,
        )

    def select_historical():
        return select_remote_snapshots(
            frankfurt.store,
            subject="record_retention",
            known_at=T_KNOWN + timedelta(seconds=7),
            target_fingerprint_value=target_fingerprint(current_query.target),
            valid_at=T_POLICY_V2,
            source_known_at=current_query.known_at,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        current_future = pool.submit(select_current)
        historical_future = pool.submit(select_historical)
        assert current_future.result()[0]["snapshot_id"] == old_id
        assert historical_future.result()[0]["snapshot_id"] == historical_valid_id


def test_r3_import_rejection_prevents_comparison_and_success_binds_snapshot(
    dhaka_seeded: OfficeHarness, frankfurt: OfficeHarness, tmp_path: Path,
) -> None:
    import httpx
    from meridian.contracts.qa import QueryRequest
    from meridian.federation.exchange import build_export
    from meridian.gateway_api.orchestrator import (
        FederationImportRejected,
        GatewayOrchestrator,
        RelayLog,
    )
    from tests.test_federation import _record_query
    from conftest import record_target
    from meridian.integrity.canonical import canonical_json_bytes, sha256_hex

    export = build_export(
        dhaka_seeded.store, query=_record_query(), signer=dhaka_seeded.signer, now=T_KNOWN
    )
    query = QueryRequest(
        question="retention", target=record_target(), valid_at=T_VALID, known_at=T_KNOWN
    )
    calls: list[tuple[str, dict]] = []
    def rejected(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        return httpx.Response(200, json={"accepted": False, "errors": ["binding failed"]})

    gateway = GatewayOrchestrator(
        tenant_id="meridian_demo", office_urls={"FRANKFURT": "http://frankfurt"},
        office_tokens={}, registry=dhaka_seeded.registry,
        relay_log=RelayLog(tmp_path / "relay.jsonl"), transport=httpx.MockTransport(rejected),
    )
    with pytest.raises(FederationImportRejected):
        gateway.import_then_compare("FRANKFURT", export, query)
    assert [path for path, _ in calls] == ["/v1/federation/imports"]

    from datetime import timedelta
    receipt = T_KNOWN + timedelta(seconds=5)
    def accepted(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("/imports"):
            return httpx.Response(200, json={
                "accepted": True, "snapshot_ids": ["rsnap_current"],
                "received_at": receipt.isoformat().replace("+00:00", "Z"),
            })
        assert body["remote_snapshot_ids"] == []
        assert datetime.fromisoformat(body["known_at"].replace("Z", "+00:00")) == T_KNOWN
        assert body["remote_snapshot_required"] is True
        assert datetime.fromisoformat(
            body["remote_source_known_at"].replace("Z", "+00:00")
        ) == export.payload.known_at
        local_record = frankfurt.query(record_target(), valid_at=T_VALID, known_at=T_KNOWN)
        projection = local_record.payload.model_copy(deep=True)
        projection.citations = [
            citation.model_copy(update={"quote": None})
            for citation in projection.citations
        ]
        projection.model_metadata = {
            **projection.model_metadata,
            "export_projection": "comparison-v1",
            "local_answer_hash": local_record.payload_hash,
            "local_answer_signature": local_record.signature,
        }
        projection_bytes = canonical_json_bytes(projection)
        return httpx.Response(200, json={
            "answer": projection.model_dump(mode="json"),
            "answer_hash": sha256_hex(projection_bytes),
            "answer_signature": frankfurt.signer.sign(projection_bytes),
            "answer_key_id": frankfurt.signer.key_id,
            "local_answer_id": local_record.payload.answer_id,
            "local_answer_hash": local_record.payload_hash,
        })

    calls.clear()
    gateway = GatewayOrchestrator(
        tenant_id="meridian_demo", office_urls={"FRANKFURT": "http://frankfurt"},
        office_tokens={}, registry=frankfurt.registry,
        relay_log=RelayLog(tmp_path / "relay-success.jsonl"), transport=httpx.MockTransport(accepted),
    )
    imported, _comparison, bound_query = gateway.import_then_compare("FRANKFURT", export, query)
    assert imported["accepted"]
    assert bound_query.remote_snapshot_ids == []
    assert bound_query.known_at == T_KNOWN
    assert bound_query.remote_snapshot_required
    assert [path for path, _ in calls] == ["/v1/federation/imports", "/v1/comparisons"]


def test_f5_explicit_cutoff_does_not_admit_policy_learned_after_receipt(
    tmp_path: Path,
) -> None:
    from meridian.contracts.common import Mode
    from meridian.extraction.service import ModelStageService
    from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source
    from conftest import DEMO_FRANKFURT, record_target

    fixture_copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fixture_copy)
    replay = fixture_copy / "replay/frankfurt/frankfurt_records_policy__v1.json"
    replay_payload = json.loads(replay.read_text("utf-8"))
    (replay.parent / "frankfurt_records_policy__v2.json").write_text(
        json.dumps({**replay_payload, "version_label": "v2"}), encoding="utf-8"
    )
    office = make_office(
        tmp_path / "temporal-frankfurt", region="FRANKFURT", fixtures_dir=fixture_copy
    )
    service = ModelStageService(office.settings)
    manifest = SourceManifest.model_validate_json(
        (FIXTURES / DEMO_FRANKFURT[1]).read_text("utf-8")
    )
    raw = (FIXTURES / DEMO_FRANKFURT[0]).read_bytes()
    first = prepare_pdf_source(manifest, raw)
    assert ingest_prepared(
        office.store, first, mode=Mode.REPLAY, service=service,
        signer=office.signer, now=T_POLICY_V2,
    ).ok

    receipt = T_KNOWN + timedelta(seconds=5)
    future_manifest = manifest.model_copy(update={"version_label": "v2"})
    future = prepare_pdf_source(future_manifest, raw)
    assert ingest_prepared(
        office.store, future, mode=Mode.REPLAY, service=service,
        signer=office.signer, now=receipt,
    ).ok

    before = office.query(record_target(), valid_at=T_VALID, known_at=T_KNOWN)
    after = office.query(record_target(), valid_at=T_VALID, known_at=receipt + timedelta(seconds=1))
    assert {c.source_version_label for c in before.payload.citations} == {"v1"}
    assert {c.source_version_label for c in after.payload.citations} == {"v1", "v2"}
