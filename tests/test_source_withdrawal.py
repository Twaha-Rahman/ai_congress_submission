"""Admin withdrawal preserves signed history and cannot race publication back in."""

import asyncio

import httpx
import pytest

from conftest import FIXTURES, T_KNOWN, T_VALID, loan_target
from meridian.contracts.common import JobStatus, Mode, utc_now
from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source, store_original
from meridian.ingestion.withdrawal import preview_withdrawal, withdraw_source
from meridian.ingestion.worker import OfficeWorker
from meridian.integrity.canonical import sha256_hex
from meridian.integrity.signing import verify_with_registry
from meridian.office_api.main import OfficeRuntime, create_app
from meridian.security.auth import PrincipalRegistry
from meridian.temporal.snapshots import select_snapshot


@pytest.fixture
def workspace(dhaka_full, monkeypatch):
    office = dhaka_full
    principals = []
    for role in ["admin", "reviewer", "reader", "uploader", "other_office"]:
        name = f"WITHDRAW_TEST_{role.upper()}"
        monkeypatch.setenv(name, f"test-{role}")
        principals.append(dict(principal_id=f"user:{role}", tenant_id="meridian_demo",
            office="FRANKFURT" if role == "other_office" else "DHAKA",
            role="admin" if role == "other_office" else role,
            permissions=["read_local", "read_restricted", "review", "ingest", "audit_read"], token_env=name))
    runtime = OfficeRuntime(settings=office.settings, registry=PrincipalRegistry(principals), trusted_keys=office.registry,
        signer=office.signer, store=office.store, worker=OfficeWorker(store=office.store, settings=office.settings, signer=office.signer))
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(office.settings)

    def request(path, *, method="GET", body=None, role="admin"):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://office") as client:
                return await client.request(method, path, json=body, headers={"Authorization": f"Bearer test-{role}"} if role else {})
        return asyncio.run(run())
    return office, request


def confirm(request, source_id, *, scope="version", reason="Policy retired by the administrator"):
    preview = request(f"/v1/sources/{source_id}/withdrawal?scope={scope}")
    assert preview.status_code == 200, preview.text
    result = request(f"/v1/sources/{source_id}/withdrawal", method="POST",
        body={"scope": scope, "reason": reason, "expected_snapshot": preview.json()["snapshot"]})
    assert result.status_code == 200, result.text
    return result.json(), preview.json()


def test_only_admin_can_preview_or_withdraw_and_invalid_requests_do_not_mutate(workspace):
    office, request = workspace
    source = office.store.find_source_version("dhaka_lending_policy", "v3")
    path = f"/v1/sources/{source.source_id}/withdrawal"
    for role in [None, "reviewer", "reader", "uploader", "other_office"]:
        expected = 401 if role is None else 403
        assert request(path, role=role).status_code == expected
        assert request(path, method="POST", body={}, role=role).status_code == expected
    preview = request(path).json()
    base = {"scope": "version", "reason": "Withdrawal test", "expected_snapshot": preview["snapshot"]}
    for changes in [{"reason": " "}, {"reason": "a"*1001}, {"scope": []}, {"actor": "forged"}, {"expected_snapshot": None}]:
        assert request(path, method="POST", body={**base, **changes}).status_code == 422
    assert request(path+"?scope=invalid").status_code == 422
    assert request("/v1/sources/missing/withdrawal").status_code == 404
    assert office.store.get_source(source.source_id).status != "withdrawn"


def test_withdrawal_retires_findings_preserves_review_signatures_originals_and_historical_queries(workspace):
    office, request = workspace
    source = office.store.find_source_version("dhaka_lending_policy", "v3")
    original = store_original(office.settings.source_dir, (FIXTURES / "documents/dhaka/dhaka_lending_policy_v3.pdf").read_bytes(), "pdf", "DHAKA")
    original_bytes = original.read_bytes()
    before = office.query(loan_target(3_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    findings = office.store.list_findings(source_ids=[source.source_id], limit=None)
    target = next(item for item in findings if item.payload.detail.get("assessment") != "historical")
    reviewed = request(f"/v1/findings/{target.payload.finding_id}/reviews", method="POST", body={"action": "acknowledge", "reason": "Checked before withdrawal", "expected_snapshot_id": target.snapshot_id}, role="reviewer")
    assert reviewed.status_code == 201
    reviews = request(f"/v1/findings/{target.payload.finding_id}").json()["reviews"]
    result, preview = confirm(request, source.source_id)
    assert result["withdrawn_source_ids"] == [source.source_id]
    assert preview["finding_count"] > 0
    after = request(f"/v1/findings/{target.payload.finding_id}").json()
    assert after["reviews"] == reviews
    assert after["finding"]["review_state"] == "acknowledged"
    assert after["finding"]["payload"]["detail"]["assessment"] == "historical"
    assert original.read_bytes() == original_bytes
    assert request(f"/v1/sources/{source.source_id}/content").status_code == 200
    assert request(f"/v1/sources/{source.source_id}/lineage").status_code == 200
    detail = request(f"/v1/sources/{source.source_id}").json()["source"]
    assert detail["withdrawal"]["actor"] == "user:admin"
    assert detail["status"] == "withdrawn"
    history = office.query(loan_target(3_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    assert history.payload.answer_text == before.payload.answer_text
    current = select_snapshot(office.store.claim_views(limit=None), valid_at=T_VALID, known_at=utc_now())
    assert not any(view.revision.source_id == source.source_id for view in current)
    older = office.store.find_source_version("dhaka_lending_policy", "v2")
    assert not any(view.revision.source_id == older.source_id for view in current)
    queued = request("/v1/findings?review_state=open").json()["findings"]
    assert not any(e["source_id"] == source.source_id for item in queued for e in item["evidence"])
    assert request(f"/v1/findings/{target.payload.finding_id}/reviews", method="POST", body={"action": "resolve", "reason": "Late review"}, role="reviewer").status_code == 409
    with office.store.db.reader() as connection:
        row = connection.execute("SELECT * FROM source_withdrawals WHERE source_id=?", (source.source_id,)).fetchone()
        raw = row["payload_json"].encode()
        assert row["payload_hash"] == sha256_hex(raw)
        assert verify_with_registry(raw, row["signature"], row["key_id"], office.registry)[0]
        assert connection.execute("SELECT payload_hash FROM finding_snapshots WHERE snapshot_id=?", (target.snapshot_id,)).fetchone()[0] == target.snapshot_hash


def test_all_versions_are_scoped_and_stale_impact_is_rejected(workspace):
    office, request = workspace
    old = office.store.find_source_version("dhaka_lending_policy", "v2")
    newer = office.store.find_source_version("dhaka_lending_policy", "v3")
    unrelated = office.store.find_source_version("dhaka_records_procedure", "v1")
    preview = request(f"/v1/sources/{old.source_id}/withdrawal?scope=all_versions").json()
    confirm(request, newer.source_id)
    payload = {"scope": "all_versions", "reason": "Retire every version", "expected_snapshot": preview["snapshot"]}
    assert request(f"/v1/sources/{old.source_id}/withdrawal", method="POST", body=payload).status_code == 409
    result, fresh = confirm(request, old.source_id, scope="all_versions")
    assert fresh["version_count"] == 1
    assert {row["source_id"] for row in fresh["versions"]} == {old.source_id, newer.source_id}
    assert result["withdrawn_source_ids"] == [old.source_id]
    assert office.store.get_source(unrelated.source_id).status != "withdrawn"
    assert request(f"/v1/sources/{old.source_id}/withdrawal", method="POST", body={"scope":"all_versions", "reason":"Again", "expected_snapshot":fresh["snapshot"]}).status_code == 409


def test_withdrawal_stops_jobs_and_late_worker_finalization_cannot_undo_it(workspace):
    office, request = workspace
    source = office.store.find_source_version("dhaka_lending_policy", "v3")
    job = office.store.create_job(kind="policy_comparison", mode=Mode.REPLAY, request={"source_id": source.source_id, "manifest": source.manifest.model_dump(mode="json")})
    claimed = office.store.claim_next_job()
    assert claimed.job_id == job.job_id
    office.store.update_job(job.job_id, progress={"current_stage":"comparison", "stages":[{"key":"comparison", "status":"running"}]})
    result, preview = confirm(request, source.source_id)
    assert preview["job_count"] == 1
    office.store.update_job(job.job_id, status=JobStatus.SUCCEEDED, source_id=source.source_id, finished=True)
    saved = office.store.get_job(job.job_id)
    assert saved.status == "failed" and saved.error_code == "source_withdrawn"
    assert saved.progress["current_stage"] is None
    assert saved.progress["stages"][0]["status"] == "interrupted"
    assert request(f"/v1/sources/{source.source_id}/comparisons", method="POST").status_code == 409
    worker = OfficeWorker(store=office.store, settings=office.settings, signer=office.signer)
    outcome = worker.process_job(claimed)
    assert outcome.error_code == "source_withdrawn"
    assert office.store.get_job(job.job_id).status == "failed"
    prepared = prepare_pdf_source(source.manifest, (FIXTURES / "documents/dhaka/dhaka_lending_policy_v3.pdf").read_bytes())
    duplicate = ingest_prepared(office.store, prepared, mode=Mode.REPLAY, service=object(), signer=office.signer)
    assert duplicate.error_code == "source_withdrawn"


def test_general_questions_exclude_withdrawn_passages_but_keep_saved_and_historical_answers(dhaka):
    from test_general_questions import seed, engine, question
    source_id = seed(dhaka)
    qa, calls = engine(dhaka)
    previous = qa.answer(question(source_ids=[source_id]))
    saved = dhaka.store.get_answer(previous.payload.answer_id)
    preview = preview_withdrawal(dhaka.store, source_id, "version")
    assert preview["answer_count"] == 1
    withdraw_source(dhaka.store, source_id, scope="version", reason="Retired guidance",
        expected_snapshot=preview["snapshot"], actor="user:admin", signer=dhaka.signer)
    assert dhaka.store.get_answer(previous.payload.answer_id) == saved
    current = question().model_copy(update={"known_at": utc_now()})
    passages, _, _ = qa.retrieve(current, moment=current.known_at, allowed_restricted=True)
    assert passages == []
    old, _, _ = qa.retrieve(question(source_ids=[source_id]), moment=previous.payload.known_at, allowed_restricted=True)
    assert old and {passage.source.source_id for passage in old} == {source_id}


def test_a_canceled_upload_cannot_publish_after_its_model_work_finishes(dhaka):
    from test_general_policy import manifest, model_service, ingest, prepared, POLICY
    service, _ = model_service(dhaka)
    original = ingest(dhaka, POLICY, manifest(), service=service)
    next_manifest = manifest(version_label="v2")
    job = dhaka.store.create_job(kind="pdf", mode=Mode.LIVE, request={"manifest": next_manifest.model_dump(mode="json")})
    dhaka.store.claim_next_job()
    callback = service.report_progress
    def publication(stage, **details):
        callback(stage, **details)
        if stage == "publication":
            preview = preview_withdrawal(dhaka.store, original.source_id, "all_versions")
            assert preview["job_count"] == 1
            withdraw_source(dhaka.store, original.source_id, scope="all_versions", reason="Retire during processing",
                expected_snapshot=preview["snapshot"], actor="user:admin", signer=dhaka.signer)
    service.report_progress = publication
    outcome = ingest_prepared(dhaka.store, prepared(POLICY, next_manifest), mode=Mode.LIVE,
        service=service, signer=dhaka.signer, job_id=job.job_id)
    assert outcome.error_code == "source_withdrawn"
    assert dhaka.store.find_source_version(next_manifest.source_identity, "v2") is None
    assert dhaka.store.get_job(job.job_id).error_code == "source_withdrawn"


def test_late_comparison_results_cannot_create_active_findings_for_withdrawn_evidence(dhaka):
    from test_general_policy import manifest, model_service, ingest, prepared, POLICY, MESSAGE
    service, _ = model_service(dhaka)
    original = ingest(dhaka, POLICY, manifest(), service=service)
    callback = service.report_progress
    def publication(stage, **details):
        callback(stage, **details)
        if stage == "publication":
            preview = preview_withdrawal(dhaka.store, original.source_id, "version")
            withdraw_source(dhaka.store, original.source_id, scope="version", reason="Retire before comparison publication",
                expected_snapshot=preview["snapshot"], actor="user:admin", signer=dhaka.signer)
    service.report_progress = publication
    outcome = ingest_prepared(dhaka.store, prepared(MESSAGE, manifest("advice", source_type="slack")), mode=Mode.LIVE, service=service, signer=dhaka.signer)
    assert outcome.ok
    assert all(record.payload.detail.get("assessment") == "historical" for record in dhaka.store.list_findings(source_ids=[original.source_id], limit=None))


def test_review_changes_require_a_new_withdrawal_confirmation(workspace):
    office, request = workspace
    source = office.store.find_source_version("dhaka_lending_policy", "v3")
    path = f"/v1/sources/{source.source_id}/withdrawal"
    preview = request(path).json()
    finding = next(record for record in office.store.list_findings(source_ids=[source.source_id], limit=None)
                   if record.payload.detail.get("assessment") != "historical")
    review = request(f"/v1/findings/{finding.payload.finding_id}/reviews", method="POST", role="reviewer",
                     body={"action":"resolve", "reason":"Reviewed while administrator was checking impact"})
    assert review.status_code == 201
    response = request(path, method="POST", body={"scope":"version", "reason":"Retired", "expected_snapshot":preview["snapshot"]})
    assert response.status_code == 409
    assert office.store.get_source(source.source_id).status != "withdrawn"
    assert request(path).json()["open_finding_count"] == preview["open_finding_count"] - 1
