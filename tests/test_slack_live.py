"""Real durable lifecycle and worker tests; Slack and model transports stay offline."""
import json

import httpx
import pytest

from meridian.integrations.slack import SlackConnector, ChannelConfig, SlackUnavailable, slack_time, source_slack_link
from meridian.ingestion.worker import OfficeWorker
from meridian.ingestion.pipeline import prepare_slack_source
from meridian.contracts.manifest import SourceManifest
from meridian.contracts.common import utc_now
from meridian.storage.store import OfficeStore
from meridian.storage.db import Database
from meridian.queries.general import GeneralQuestionEngine
from meridian.contracts.qa import QueryRequest
from test_general_policy import model_service


CHANNEL = ChannelConfig(channel_id="CDEMO", channel_name="team", policy_family="people",
    scope={"kind": "policy", "description": "Employees", "attributes": {}},
    sensitivity="restricted", hosted_model=True)


@pytest.fixture
def connector(dhaka, monkeypatch):
    monkeypatch.setenv("DHAKA_SLACK_APP_TOKEN", "test-app-token")
    monkeypatch.setenv("DHAKA_SLACK_BOT_TOKEN", "test-bot-token")
    def wire(req):
        method = req.url.path.rsplit("/", 1)[-1]
        result = {"ok": True}
        if method == "auth.test":
            result.update(team_id="TDEMO", team="Demo", user_id="UBOT")
        elif method == "conversations.info":
            result.update(channel={"id": "CDEMO", "name": "team", "is_member": True, "is_private": False})
        elif method == "conversations.history":
            result.update(messages=[])
        else:
            raise AssertionError(f"Unexpected Slack API: {method}")
        return httpx.Response(200, json=result)
    c = SlackConnector(dhaka.store, dhaka.settings, transport=httpx.MockTransport(wire))
    c.save_channel(CHANNEL)
    return c


def event(id="Ev1", ts="1792454400.000001", text="Employees must request leave in the HR system.", **extra):
    return {"team_id": "TDEMO", "event_id": id, "event": {
        "type": "message", "user": "UDEMO", "channel": "CDEMO", "ts": ts, "event_ts": ts, "text": text, **extra}}


def worker_for(dhaka, connector):
    service, calls = model_service(dhaka)
    worker = OfficeWorker(store=dhaka.store, settings=service.settings, signer=dhaka.signer,
                          transport=service.live._transport)
    worker.slack = connector
    return worker, calls


def publish(dhaka, c, payload):
    from pathlib import Path
    from meridian.contracts.common import Mode
    from meridian.ingestion.pipeline import ingest_prepared
    assert c.receive(payload)
    assert c.process_once(dhaka.signer)
    job = dhaka.store.list_jobs()[0]
    prepared = prepare_slack_source(SourceManifest.model_validate(job.request["manifest"]), Path(job.request["file_ref"]).read_bytes())
    service, calls = model_service(dhaka)
    result = ingest_prepared(dhaka.store, prepared, mode=Mode.LIVE, service=service,
        signer=dhaka.signer, now=utc_now(), source_dir=dhaka.settings.source_dir)
    assert result.ok, result.error_detail
    c.link_result(job, result.source_id)
    return result, job


def test_durable_capture_dedup_scope_snapshot_and_restart(dhaka, connector):
    assert connector.receive(event())
    assert not connector.receive(event())
    assert not connector.receive({**event("other"), "team_id": "TOTHER"})
    assert not connector.receive(event("wrongchannel", channel="COTHER"))
    assert not connector.receive(event("subtype", subtype="channel_join"))
    assert not connector.receive({**event(), "event_id": None})
    # Changing channel permissions after receipt does not rewrite the trusted snapshot.
    connector.save_channel(CHANNEL.model_copy(update={"hosted_model": False}))
    restarted = SlackConnector(OfficeStore(Database(dhaka.settings.db_path), tenant_id="meridian_demo", region="DHAKA"), dhaka.settings, transport=connector.transport)
    assert restarted.process_once(dhaka.signer)
    job = dhaka.store.list_jobs()[0]
    manifest = SourceManifest.model_validate(job.request["manifest"])
    assert manifest.permissions.hosted_model and manifest.authority.value == "informal"
    assert manifest.version_label == "v1"
    assert manifest.publication_time.microsecond == 1
    assert restarted.status()["counts"] == {"queued": 1}


def test_pause_retains_events_and_queued_jobs_without_blocking_pdf(dhaka, connector):
    connector.set_paused(True)
    assert connector.receive(event())
    assert connector.process_once(dhaka.signer)
    assert dhaka.store.list_jobs()[0].status == "queued"
    connector.set_paused(False)
    connector.set_paused(True)
    assert dhaka.store.claim_next_job(pause_live_slack=True) is None
    from meridian.contracts.common import Mode
    pdf = dhaka.store.create_job(kind="pdf", mode=Mode.REPLAY, request={})
    assert dhaka.store.claim_next_job(pause_live_slack=True).job_id == pdf.job_id
    connector.set_paused(False)
    assert dhaka.store.claim_next_job().kind == "slack"


def test_edit_delete_close_signed_evidence_and_exclude_current_raw_passages(dhaka, connector):
    first, job = publish(dhaka, connector, event())
    before = utc_now()
    edit = event("Ev2", ts="1792454401.000001", subtype="message_changed",
        message={"ts": "1792454400.000001", "user": "UDEMO", "text": "Employees must request leave through their manager."})
    assert connector.receive(edit)
    assert connector.process_once(dhaka.signer)
    assert not dhaka.store.source_available_at(first.source_id, utc_now())
    assert dhaka.store.source_available_at(first.source_id, before)
    assert all(r.system_to for r in dhaka.store.claims_for_source(first.source_id))
    with dhaka.store.db.reader() as conn:
        withdrawal = conn.execute("SELECT * FROM source_withdrawals").fetchone()
    from meridian.integrity.signing import verify_with_registry
    assert verify_with_registry(withdrawal["payload_json"].encode(), withdrawal["signature"], withdrawal["key_id"], dhaka.registry)[0]
    engine = GeneralQuestionEngine(store=dhaka.store, signer=dhaka.signer, settings=dhaka.settings)
    request = QueryRequest(question="How do employees request leave?", target={"subject": "general_policy"}, valid_at=utc_now())
    passages, _, _ = engine.retrieve(request, moment=utc_now(), allowed_restricted=True)
    assert not any(p.source.source_id == first.source_id for p in passages)
    old = event("EvLate", ts="1792454400.000001")
    assert connector.receive(old); connector.process_once(dhaka.signer)
    assert connector.status()["recent"][0]["status"] == "ignored"
    deletion = event("Ev3", ts="1792454402.000001", subtype="message_deleted", deleted_ts="1792454400.000001")
    assert connector.receive(deletion); connector.process_once(dhaka.signer)
    assert dhaka.store.list_jobs()[0].status == "failed"  # unprocessed obsolete edit is cancelled
    assert source_slack_link(dhaka.store, first.source_id)["message_ts"] == "1792454400.000001"


def test_threads_include_parent_and_root_edit_withdraws_dependents(dhaka, connector):
    root, _ = publish(dhaka, connector, event())
    reply = event("EvReply", ts="1792454401.000001", text="Managers must record approval in the HR system.", thread_ts="1792454400.000001")
    assert connector.receive(reply); connector.process_once(dhaka.signer)
    job = dhaka.store.list_jobs()[0]
    from pathlib import Path
    saved = json.loads(Path(job.request["file_ref"]).read_text())
    assert len(saved["events"]) == 2 and saved["events"][0]["text"] == event()["event"]["text"]
    # A changed root cancels a queued reply and schedules a refresh preserving its old access configuration.
    connector.save_channel(CHANNEL.model_copy(update={"sensitivity": "demo_shareable"}))
    edit = event("EvRootEdit", ts="1792454402.000001", subtype="message_changed",
        message={"ts": "1792454400.000001", "user": "UDEMO", "text": "Employees must request leave through their manager."})
    assert connector.receive(edit); connector.process_once(dhaka.signer)
    assert dhaka.store.get_job(job.job_id).status == "failed"
    connector.process_once(dhaka.signer)
    refreshed = dhaka.store.list_jobs()[0]
    assert refreshed.request["manifest"]["sensitivity"] == "restricted"
    assert refreshed.request["manifest"]["version_label"] == "v2"
    assert not dhaka.store.source_available_at(root.source_id, utc_now())


def test_missing_thread_context_requires_review_without_model_call(dhaka, connector):
    assert connector.receive(event(thread_ts="1792454399.000001"))
    connector.process_once(dhaka.signer)
    assert not dhaka.store.list_jobs()
    assert connector.status()["counts"] == {"needs_review": 1}


def test_private_or_shared_channels_rejected_and_workspace_cannot_change(dhaka, connector):
    for flags in [{"is_private": True}, {"is_shared": True}, {"is_ext_shared": True}, {"is_member": False}]:
        connector.transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True, "team_id": "TDEMO", "channel": {"is_member": True, **flags}}))
        with pytest.raises(SlackUnavailable): connector.save_channel(CHANNEL)
    connector.transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True, "team_id": "TOTHER"}))
    with pytest.raises(SlackUnavailable): connector.authenticate()


def test_channel_becoming_private_withdraws_evidence(dhaka, connector):
    first, _ = publish(dhaka, connector, event())
    assert connector.receive(event("EvNew", ts="1792454401.000001"))
    connector.transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True, "channel": {"is_member": True, "is_private": True}}))
    connector.process_once(dhaka.signer)
    assert not dhaka.store.source_available_at(first.source_id, utc_now())
    assert connector.status()["channels"] == []


def test_timestamp_identity_is_exact():
    assert slack_time("1792454400.123456").microsecond == 123456
    for bad in ["nan", "123.1234567", "-10.000001", None]:
        with pytest.raises(ValueError): slack_time(bad)


def test_worker_publishes_and_links_real_slack_job(dhaka, connector):
    worker, calls = worker_for(dhaka, connector)
    assert connector.receive(event())
    assert worker.process_once()
    job = dhaka.store.list_jobs()[0]
    assert job.status == "needs_review" and job.review_reason == "policy_reference_missing"
    assert job.source_id and source_slack_link(dhaka.store, job.source_id)
    assert len(calls) == 1
    assert connector.status()["counts"] == {"needs_review": 1}
    assert not connector.receive(event())
    assert not worker.process_once()


def test_socket_ack_only_after_durable_capture_and_no_slack_writes(dhaka, connector):
    messages = [{"type": "events_api", "envelope_id": "envelope-1", "payload": event()}]
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): connector._stop.set()
        def recv(self, **kwargs):
            if messages: return json.dumps(messages.pop(0))
            connector._stop.set(); raise TimeoutError()
        def send(self, text):
            # A brand-new reader can see the committed event before ack.
            restarted = SlackConnector(OfficeStore(Database(dhaka.settings.db_path), tenant_id="meridian_demo", region="DHAKA"), dhaka.settings)
            assert restarted.status()["counts"] == {"pending": 1}
            assert json.loads(text)["envelope_id"] == "envelope-1"
    original = connector.call
    connector.call = lambda method, **data: {"ok": True, "url": "wss://wss-primary.slack.com/test"} if method == "apps.connections.open" else original(method, **data)
    connector.socket_factory = lambda *args, **kwargs: Socket()
    connector.run()
    assert not dhaka.store.list_jobs()  # the receiver never runs extraction


def test_access_revocation_is_durable_and_processed_even_while_paused(dhaka, connector):
    first, _ = publish(dhaka, connector, event())
    connector.set_paused(True)
    connector.revoke_channel("CDEMO", "App left channel.")
    assert connector.process_once(dhaka.signer)
    assert not dhaka.store.source_available_at(first.source_id, utc_now())
    assert not connector.receive(event("EvAfter", ts="1792454401.000001"))


def test_slack_endpoints_require_office_uploader_and_do_not_return_secrets(dhaka, connector, monkeypatch):
    from meridian.office_api.main import OfficeRuntime, create_app
    from meridian.security.auth import PrincipalRegistry, Principal, Permission, Role
    from meridian.api_common import ApiError
    worker, _ = worker_for(dhaka, connector)
    runtime = OfficeRuntime(settings=dhaka.settings, registry=PrincipalRegistry([]), trusted_keys=dhaka.registry,
        signer=dhaka.signer, store=dhaka.store, worker=worker, slack=connector)
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _: runtime)
    app = create_app(dhaka.settings)
    def endpoint(method):
        return next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/v1/integrations/slack" and method in r.methods)
    def principal(office, ingest):
        return Principal("test", "meridian_demo", office, Role.UPLOADER if ingest else Role.READER,
            frozenset({Permission.INGEST, Permission.READ_LOCAL} if ingest else {Permission.READ_LOCAL}), "Test")
    for actor in [principal("DHAKA", False), principal("FRANKFURT", True)]:
        with pytest.raises(Exception): endpoint("GET")(principal=actor)
        with pytest.raises(Exception): endpoint("POST")({"action": "pause"}, principal=actor)
    admin = principal("DHAKA", True)
    response = endpoint("POST")({"action": "pause"}, principal=admin)
    assert response["paused"]
    assert "test-app-token" not in json.dumps(response) and "test-bot-token" not in json.dumps(response)
    with pytest.raises(ApiError): endpoint("POST")({"action": "save_channel", "channel": {**CHANNEL.model_dump(), "authority": "policy"}}, principal=admin)


def test_thread_context_cannot_broaden_parent_reader_or_egress_permissions(dhaka, connector):
    connector.save_channel(CHANNEL.model_copy(update={"hosted_model": False, "office_export": False}))
    assert connector.receive(event()); connector.process_once(dhaka.signer)
    connector.save_channel(CHANNEL.model_copy(update={"sensitivity": "demo_shareable", "hosted_model": True, "office_export": True}))
    assert connector.receive(event("EvReply", ts="1792454401.000001", text="Managers must approve requests.", thread_ts="1792454400.000001"))
    connector.process_once(dhaka.signer)
    m = dhaka.store.list_jobs()[0].request["manifest"]
    assert m["sensitivity"] == "restricted" and not m["permissions"]["hosted_model"] and not m["permissions"]["office_export"]


def test_duplicate_office_app_tokens_cannot_split_and_lose_events(dhaka, monkeypatch):
    for region in ["DHAKA", "FRANKFURT"]:
        monkeypatch.setenv(f"{region}_SLACK_APP_TOKEN", "same-test-app")
        monkeypatch.setenv(f"{region}_SLACK_BOT_TOKEN", "test-bot")
    c = SlackConnector(dhaka.store, dhaka.settings)
    assert not c.configured and c.state == "not_configured"
    assert "separate Slack app" in c.status()["error"]


def test_empty_edit_still_withdraws_current_evidence(dhaka, connector):
    first, _ = publish(dhaka, connector, event())
    assert connector.receive(event("EvEmptyEdit", ts="1792454401.000001", subtype="message_changed",
        message={"ts": "1792454400.000001", "user": "UDEMO", "text": ""}))
    connector.process_once(dhaka.signer)
    assert not dhaka.store.source_available_at(first.source_id, utc_now())


def test_failed_durable_capture_is_never_acknowledged(dhaka, connector, monkeypatch):
    sent = []
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): connector._stop.set()
        def recv(self, **kwargs): return json.dumps({"type": "events_api", "envelope_id": "E1", "payload": event()})
        def send(self, text): sent.append(text)
    def broken(payload):
        import sqlite3
        raise sqlite3.OperationalError("test-only secret must not be exposed")
    monkeypatch.setattr(connector, "receive", broken)
    original = connector.call
    connector.call = lambda method, **data: {"ok": True, "url": "wss://wss-primary.slack.com/test"} if method == "apps.connections.open" else original(method, **data)
    connector.socket_factory = lambda *args, **kwargs: Socket()
    connector.run()
    assert not sent
    assert "secret" not in (connector.error or "")


def test_deletion_retires_existing_finding_as_a_signed_historical_snapshot(dhaka, connector):
    from test_general_policy import ingest, manifest, POLICY, MESSAGE
    service, _ = model_service(dhaka)
    assert ingest(dhaka, POLICY, manifest(), service=service).ok
    worker, calls = worker_for(dhaka, connector)
    assert connector.receive(event(text=MESSAGE))
    assert worker.process_once()
    findings = dhaka.store.list_findings()
    assert findings
    assert connector.receive(event("EvDelete", ts="1792454402.000001", subtype="message_deleted", deleted_ts="1792454400.000001"))
    connector.process_once(dhaka.signer)
    for old in findings:
        current = dhaka.store.get_finding(old.payload.finding_id)
        assert current.payload.detail["assessment"] == "historical"
        assert current.payload.finding_id not in {r.payload.finding_id for r in dhaka.store.list_findings(alert=True)}
        assert current.snapshot_id != old.snapshot_id


def test_withdrawal_also_excludes_unclaimed_thread_passages(dhaka, connector):
    from pathlib import Path
    from meridian.contracts.common import Mode
    from meridian.ingestion.pipeline import ingest_prepared
    from test_general_policy import proposal
    root, _ = publish(dhaka, connector, event())
    assert connector.receive(event("EvReply", ts="1792454401.000001", text="Managers record decisions in the HR system.", thread_ts="1792454400.000001"))
    connector.process_once(dhaka.signer)
    job = dhaka.store.list_jobs()[0]
    prepared = prepare_slack_source(SourceManifest.model_validate(job.request["manifest"]), Path(job.request["file_ref"]).read_bytes())
    # The model extracts only the root. The reply remains a retrievable raw passage.
    output = proposal(event()["event"]["text"], CHANNEL.scope.model_dump()).model_dump(mode="json")
    service, _ = model_service(dhaka, extraction_change=lambda result: result.update(output))
    result = ingest_prepared(dhaka.store, prepared, mode=Mode.LIVE, service=service,
        signer=dhaka.signer, now=utc_now(), source_dir=dhaka.settings.source_dir)
    assert result.ok
    connector.link_result(job, result.source_id)
    assert len(dhaka.store.clauses_for_source(result.source_id)) == 2
    assert len(dhaka.store.claims_for_source(result.source_id)) == 1
    engine = GeneralQuestionEngine(store=dhaka.store, signer=dhaka.signer, settings=dhaka.settings)
    request = QueryRequest(question="How do managers record decisions?", target={"subject": "general_policy"}, valid_at=utc_now())
    assert any("Managers record" in p.text for p in engine.retrieve(request, moment=utc_now(), allowed_restricted=True)[0])
    assert connector.receive(event("EvDeleted", ts="1792454402.000001", subtype="message_deleted", deleted_ts="1792454400.000001"))
    connector.process_once(dhaka.signer)
    assert not engine.retrieve(request, moment=utc_now(), allowed_restricted=True)[0]


def test_slack_api_over_http_enforces_identity_and_validates_settings(dhaka, connector, monkeypatch):
    import asyncio
    from meridian.office_api.main import OfficeRuntime, create_app
    from meridian.security.auth import PrincipalRegistry
    monkeypatch.setenv("DEMO_TOKEN_DHAKA_UPLOADER", "slack-test-uploader")
    monkeypatch.setenv("DEMO_TOKEN_DHAKA_READER", "slack-test-reader")
    worker, _ = worker_for(dhaka, connector)
    runtime = OfficeRuntime(settings=dhaka.settings, registry=PrincipalRegistry.from_file(dhaka.settings.principals_path),
        trusted_keys=dhaka.registry, signer=dhaka.signer, store=dhaka.store, worker=worker, slack=connector)
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _: runtime)
    app = create_app(dhaka.settings)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/v1/integrations/slack")).status_code == 401
            assert (await client.get("/v1/integrations/slack", headers={"Authorization": "Bearer slack-test-reader"})).status_code == 403
            headers = {"Authorization": "Bearer slack-test-uploader"}
            status = await client.get("/v1/integrations/slack", headers=headers)
            assert status.status_code == 200 and "test-bot-token" not in status.text
            paused = await client.post("/v1/integrations/slack", headers=headers, json={"action": "pause"})
            assert paused.status_code == 200 and paused.json()["paused"]
            invalid = await client.post("/v1/integrations/slack", headers=headers, json={"action": "save_channel", "channel": {**CHANNEL.model_dump(), "region": "FRANKFURT"}})
            assert invalid.status_code == 422
            updated = await client.post("/v1/integrations/slack", headers=headers, json={"action": "save_channel", "channel": CHANNEL.model_dump()})
            assert updated.status_code == 200 and updated.json()["channels"][0]["channel_name"] == "team"
    asyncio.run(check())


def test_queued_jobs_recheck_channel_access_before_model_egress(dhaka, connector):
    worker, calls = worker_for(dhaka, connector)
    assert connector.receive(event()); connector.process_once(dhaka.signer)
    connector.transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True, "channel": {"is_member": True, "is_private": True}}))
    assert worker.process_once()
    assert not calls
    assert dhaka.store.list_jobs()[0].error_code == "forbidden"


def test_access_lookup_outage_does_not_consume_model_retry_attempts(dhaka, connector):
    worker, calls = worker_for(dhaka, connector)
    assert connector.receive(event()); connector.process_once(dhaka.signer)
    connector.transport = httpx.MockTransport(lambda req: httpx.Response(503))
    assert worker.process_once()
    job = dhaka.store.list_jobs()[0]
    assert job.status == "queued" and job.attempts == 0 and not calls
    assert not worker.process_once()  # backoff, no busy loop


def test_crash_between_publication_and_linking_cannot_leave_old_text_current(dhaka, connector):
    first, _ = publish(dhaka, connector, event())
    with dhaka.store.db.transaction() as conn:
        # Simulate the recoverable gap after source commit and before job finalization.
        conn.execute("DELETE FROM slack_source_links WHERE source_id=?", (first.source_id,))
    assert connector.receive(event("EvEditAfterCrash", ts="1792454401.000001", subtype="message_changed",
        message={"ts": "1792454400.000001", "user": "UDEMO", "text": "Employees must request leave through their manager."}))
    connector.process_once(dhaka.signer)
    assert not dhaka.store.source_available_at(first.source_id, utc_now())
    assert all(r.system_to for r in dhaka.store.claims_for_source(first.source_id))
