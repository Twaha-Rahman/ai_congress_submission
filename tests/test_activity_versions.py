"""Read-only activity, pagination, version diff accuracy and authorization boundaries."""
import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from meridian.api_common import ApiError
from meridian.contracts.common import Authority, EgressChannel, EgressOutcome, ErrorCode, Mode
from meridian.contracts.federation import EgressEvent
from meridian.ingestion.worker import OfficeWorker
from meridian.office_api.main import OfficeRuntime, create_app
from meridian.office_api.workspace_views import activity_page, compare_source_text
from meridian.security.auth import AuthorizationError, Permission, Principal, PrincipalRegistry, Role
from conftest import FIXTURES, T_KNOWN


def endpoints(office, monkeypatch):
    runtime = OfficeRuntime(settings=office.settings,
        registry=PrincipalRegistry.from_file(FIXTURES.parent / "config/principals.json"),
        trusted_keys=office.registry, signer=office.signer, store=office.store,
        worker=OfficeWorker(store=office.store, settings=office.settings, signer=office.signer))
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(office.settings)
    return lambda path, method="GET": next(route.endpoint for route in app.routes if getattr(route, "path", None) == path and method in route.methods)


def principal(*permissions):
    return Principal(principal_id="reviewer", tenant_id="meridian_demo", office="DHAKA", role=Role.REVIEWER, display_name="Reviewer", permissions=frozenset(permissions))


def test_source_version_api_does_not_infer_versions_or_bypass_access(dhaka_full, monkeypatch):
    get = endpoints(dhaka_full, monkeypatch)
    reader = principal(Permission.READ_LOCAL)
    before = dhaka_full.store.find_source_version("dhaka_lending_policy", "v2")
    after = dhaka_full.store.find_source_version("dhaka_lending_policy", "v3")
    versions = get("/v1/sources/{source_id}/versions")(before.source_id, principal=reader)["sources"]
    assert {item["source_id"] for item in versions} == {before.source_id, after.source_id}
    diff = get("/v1/sources/{source_id}/diff")
    result = diff(before.source_id, other=after.source_id, principal=reader)
    assert result["before"]["version_label"] == "v2" and result["after"]["version_label"] == "v3"
    assert result["explicit_replacement"] is True
    assert sum(result["counts"].values()) == len(result["passages"])
    assert any(row["kind"] != "unchanged" for row in result["passages"])
    assert diff(after.source_id, other=before.source_id, principal=reader)["explicit_replacement"] is False
    unrelated = dhaka_full.store.find_source_version("dhaka_records_procedure", "v1")
    for target in [before.source_id, unrelated.source_id]:
        with pytest.raises(ApiError) as caught:
            diff(before.source_id, other=target, principal=reader)
        assert caught.value.code == ErrorCode.INVALID_INPUT
    with dhaka_full.store.db.transaction() as connection:
        connection.execute("UPDATE sources SET sensitivity = 'restricted' WHERE source_id = ?", (after.source_id,))
    assert len(get("/v1/sources/{source_id}/versions")(before.source_id, principal=reader)["sources"]) == 1
    with pytest.raises(ApiError) as caught:
        diff(before.source_id, other=after.source_id, principal=reader)
    assert caught.value.code == ErrorCode.NOT_FOUND
    for outsider in [replace(reader, office="FRANKFURT"), replace(reader, tenant_id="other")]:
        with pytest.raises(AuthorizationError):
            get("/v1/sources/{source_id}/versions")(before.source_id, principal=outsider)


def test_diff_preserves_complete_text_in_both_directions_and_metadata(dhaka_seeded):
    source = dhaka_seeded.store.find_source_version("dhaka_lending_policy", "v2")
    def clause(text, n):
        return SimpleNamespace(clause_id=f"clause{n}", text=text, page=1, section="Policy")
    old = [clause("Untouched intro.", 1), clause("Employees may retain records for 5 years.", 2), clause("Removed paragraph.", 3), clause("Stable ending.", 4)]
    new = [clause("Untouched intro.", 5), clause("Employees must retain records for 7 years.", 6), clause("Stable ending.", 7), clause("New paragraph.", 8)]
    store = SimpleNamespace(clauses_for_source=lambda key: old if key == source.source_id else new)
    target = replace(source, source_id="other", version_label="arbitrary-label", supersedes=None, source_sha256="different", content_sha256="different", manifest=source.manifest.model_copy(update={"authority": Authority.INFORMAL}))
    result = compare_source_text(store, source, target)
    assert result["explicit_replacement"] is False
    assert result["counts"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 2}
    assert [row["before"]["text"] for row in result["passages"] if row["before"]] == [row.text for row in old]
    assert [row["after"]["text"] for row in result["passages"] if row["after"]] == [row.text for row in new]
    changed = next(row for row in result["passages"] if row["kind"] == "changed")
    assert "".join(chunk["text"] for chunk in changed["chunks"] if chunk["kind"] != "added") == changed["before"]["text"]
    assert "".join(chunk["text"] for chunk in changed["chunks"] if chunk["kind"] != "removed") == changed["after"]["text"]
    assert {row["field"] for row in result["metadata"]} == {"authority"}
    identical = compare_source_text(SimpleNamespace(clauses_for_source=lambda _: old), source, replace(source, source_id="other"))
    assert identical["same_file"] and identical["same_text"] and identical["counts"]["unchanged"] == 4


def test_activity_pagination_filters_scopes_and_omits_requests(dhaka_full, monkeypatch):
    office = dhaka_full
    get = endpoints(office, monkeypatch)
    reviewer = principal(Permission.AUDIT_READ, Permission.READ_LOCAL, Permission.READ_RESTRICTED, Permission.REVIEW)
    reader = principal(Permission.READ_LOCAL)
    job = office.store.create_job(kind="pdf", mode=Mode.REPLAY, request={"file_ref": "/private/secret-path.pdf", "manifest": {"source_identity": "Activity test", "sensitivity": "restricted"}, "request_id": "correlation"})
    with office.store.db.transaction() as connection:
        for n, outcome in enumerate([EgressOutcome.BLOCKED, EgressOutcome.DELIVERED, EgressOutcome.TIMEOUT]):
            office.store.record_egress(connection, EgressEvent(event_id=f"event{n}", tenant_id=office.store.tenant_id, region="DHAKA", channel=EgressChannel.HOSTED_MODEL,
                destination="https://name:password@example.com/api?token=secret#fragment", request_id="correlation", payload_type="extraction_request", payload_bytes=100, raw_source_bytes=50, payload_sha256="a"*64,
                outcome=outcome, created_at=T_KNOWN))
    finding = get("/v1/findings")(principal=reviewer)["findings"][0]
    class Request:
        async def json(self):
            return {"action": "acknowledge", "reason": "Checking activity history", "expected_snapshot_id": finding["snapshot_id"]}
    asyncio.run(get("/v1/findings/{finding_id}/reviews", "POST")(finding["finding_id"], Request(), principal=reviewer))
    defaults = dict(limit=2, cursor="", category="all", outcome="all", q="", since=None, until=None, principal=reviewer)
    page = get("/v1/activity")
    seen = []
    while True:
        result = page(**defaults)
        seen.extend(result["events"])
        if not result["next_cursor"]:
            break
        defaults["cursor"] = result["next_cursor"]
    ids = [event["id"] for event in seen]
    assert len(ids) == len(set(ids))
    assert {event["category"] for event in seen} == {"source", "processing", "review", "transfer"}
    text = json.dumps(seen)
    assert "password" not in text and "token=secret" not in text and "secret-path" not in text and "request_json" not in text
    assert next(item for item in seen if item["id"] == "transfer:event0")["description"] == "https://example.com/api"
    filtered = page(**{**defaults, "cursor": "", "category": "transfer", "outcome": "blocked", "q": "correlation"})
    assert [item["id"] for item in filtered["events"]] == ["transfer:event0"]
    assert filtered["summary"]["blocked_exports"] == 1 and filtered["summary"]["failed_transfers"] == 1
    bounded = page(**{**defaults, "cursor":"", "since":T_KNOWN + timedelta(seconds=1), "until":T_KNOWN + timedelta(seconds=2)})
    assert bounded["events"] == []
    # AUDIT_READ alone never grants restricted source/job visibility.
    minimal = replace(reader, permissions=frozenset({Permission.READ_LOCAL,Permission.AUDIT_READ}))
    hidden = page(**{**defaults, "limit":100, "cursor":"", "principal":minimal})
    assert f"processing:{job.job_id}" not in [item["id"] for item in hidden["events"]]
    detail = get("/v1/activity/{event_id}")
    with pytest.raises(ApiError) as caught:
        detail(f"processing:{job.job_id}",principal=minimal)
    assert caught.value.code == ErrorCode.NOT_FOUND
    assert detail("transfer:event1",principal=reviewer)["event"]["outcome"] == "delivered"
    for outsider in [reader,replace(reviewer,office="FRANKFURT"),replace(reviewer,tenant_id="other")]:
        with pytest.raises(AuthorizationError):
            page(**{**defaults,"principal":outsider})
    with pytest.raises(ApiError):
        page(**{**defaults,"cursor":"malformed!"})
    with pytest.raises(ApiError):
        page(**{**defaults,"cursor":"","since":T_KNOWN,"until":T_KNOWN-timedelta(days=1)})


def test_activity_http_validation_and_office_token_boundaries(dhaka_full, monkeypatch):
    import httpx
    office = dhaka_full
    endpoints(office, monkeypatch)
    monkeypatch.setenv("DEMO_TOKEN_DHAKA_REVIEWER", "activity-test-reviewer")
    monkeypatch.setenv("DEMO_TOKEN_DHAKA_READER", "activity-test-reader")
    monkeypatch.setenv("DEMO_TOKEN_FRANKFURT_REVIEWER", "activity-wrong-office")
    app = create_app(office.settings)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            headers={"Authorization":"Bearer activity-test-reviewer"}
            for path in ["/v1/activity?limit=0", "/v1/activity?limit=101", "/v1/activity?since=not-a-date", "/v1/activity?since=2026-10-21T09:00:00", "/v1/activity?since=2026-10-22T09:00:00Z&until=2026-10-21T09:00:00Z"]:
                assert (await client.get(path,headers=headers)).status_code==422
            assert (await client.get("/v1/activity?limit=1",headers=headers)).status_code==200
            assert (await client.get("/v1/activity",headers={"Authorization":"Bearer activity-test-reader"})).status_code==403
            assert (await client.get("/v1/activity",headers={"Authorization":"Bearer activity-wrong-office"})).status_code==403
            assert (await client.get("/v1/activity")).status_code==401
            assert (await client.post("/v1/activity",headers=headers)).status_code==405
    asyncio.run(run())


def test_activity_preserves_subsecond_order_and_records_source_withdrawal(dhaka_full, monkeypatch):
    from meridian.integrity.canonical import canonical_json_bytes, sha256_hex
    office=dhaka_full
    get=endpoints(office,monkeypatch)
    reviewer=principal(Permission.AUDIT_READ,Permission.READ_LOCAL,Permission.READ_RESTRICTED)
    source=office.store.find_source_version("dhaka_lending_policy","v2")
    payload={"source_id":source.source_id,"tenant_id":office.store.tenant_id,"region":"DHAKA","reason":"message_deleted","withdrawn_at":T_KNOWN.isoformat()}
    raw=canonical_json_bytes(payload)
    with office.store.db.transaction() as connection:
        connection.execute("INSERT INTO source_withdrawals VALUES (?,?,?,?,?,?,?,?)",(source.source_id,office.store.tenant_id,office.store.region,T_KNOWN.isoformat(),raw.decode(),sha256_hex(raw),office.signer.sign(raw),office.signer.key_id))
        for n in [0,2,1]:
            office.store.record_egress(connection,EgressEvent(event_id=f"precision_{n}",tenant_id=office.store.tenant_id,region="DHAKA",channel=EgressChannel.OFFICE_TO_OFFICE,destination="FRANKFURT",request_id="test",payload_type="federation_export",payload_bytes=0,raw_source_bytes=0,payload_sha256="a"*64,outcome=EgressOutcome.DELIVERED,created_at=T_KNOWN+timedelta(microseconds=n)))
    page=get("/v1/activity")
    params=dict(limit=1,cursor="",category="transfer",outcome="all",q="",since=T_KNOWN,until=T_KNOWN+timedelta(seconds=1),principal=reviewer)
    found=[]
    while True:
        result=page(**params);found.extend(item["id"] for item in result["events"])
        if not result["next_cursor"]:break
        params["cursor"]=result["next_cursor"]
    assert found==["transfer:precision_2","transfer:precision_1","transfer:precision_0"]
    withdrawn=page(**{**params,"cursor":"","category":"withdrawal","since":None,"until":None})
    assert withdrawn["events"][0]["target_id"]==source.source_id
    assert withdrawn["events"][0]["details"]["reason"]=="message_deleted"
