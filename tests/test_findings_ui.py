"""Finding-detail support for the UI: durable review history and stale-review guards."""

from __future__ import annotations

import asyncio

import pytest

from meridian.api_common import ApiError
from meridian.contracts.common import ErrorCode
from meridian.ingestion.worker import OfficeWorker
from meridian.office_api.main import OfficeRuntime, create_app
from meridian.security.auth import Permission, Principal, PrincipalRegistry, Role

from conftest import FIXTURES, OfficeHarness


def test_review_history_persists_and_remains_subject_to_finding_access(
    dhaka_full: OfficeHarness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    office = dhaka_full
    runtime = OfficeRuntime(
        settings=office.settings,
        registry=PrincipalRegistry.from_file(FIXTURES.parent / "config/principals.json"),
        trusted_keys=office.registry, signer=office.signer, store=office.store,
        worker=OfficeWorker(store=office.store, settings=office.settings, signer=office.signer),
    )
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(office.settings)

    def endpoint(path, method="GET"):
        return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path and method in route.methods)

    reviewer = Principal(
        principal_id="test_reviewer", tenant_id="meridian_demo", office="DHAKA",
        role=Role.REVIEWER, display_name="Reviewer",
        permissions=frozenset({Permission.READ_LOCAL, Permission.READ_RESTRICTED, Permission.REVIEW}),
    )
    reader = Principal(
        principal_id="test_reader", tenant_id="meridian_demo", office="DHAKA",
        role=Role.READER, display_name="Reader", permissions=frozenset({Permission.READ_LOCAL}),
    )
    findings = endpoint("/v1/findings")(principal=reviewer)["findings"]
    finding = next(f for f in findings if f["finding_type"] == "stale_guidance")
    get = endpoint("/v1/findings/{finding_id}")
    post = endpoint("/v1/findings/{finding_id}/reviews", "POST")
    assert get(finding["finding_id"], principal=reviewer)["reviews"] == []

    class Body:
        def __init__(self, snapshot):
            self.snapshot = snapshot

        async def json(self):
            return {"action": "acknowledge", "reason": "Contact policy owner to correct the Slack guidance.", "expected_snapshot_id": self.snapshot}

    with pytest.raises(ApiError) as conflict:
        asyncio.run(post(finding["finding_id"], request=Body("older-snapshot"), principal=reviewer))
    assert conflict.value.code == ErrorCode.CONFLICT
    assert get(finding["finding_id"], principal=reviewer)["reviews"] == []

    result = asyncio.run(post(finding["finding_id"], request=Body(finding["snapshot_id"]), principal=reviewer))
    assert result["new_state"] == "acknowledged"
    reloaded = get(finding["finding_id"], principal=reader)
    assert reloaded["finding"]["review_state"] == "acknowledged"
    assert reloaded["reviews"][0]["reason"] == "Contact policy owner to correct the Slack guidance."
    assert reloaded["reviews"][0]["snapshot_id"] == finding["snapshot_id"]

    restricted_source = office.store.find_source_version("dhaka_credit_note_restricted", "v1")
    restricted_finding = next(f for f in findings if any(e["source_id"] == restricted_source.source_id for e in f["evidence"]))
    asyncio.run(post(restricted_finding["finding_id"], request=Body(restricted_finding["snapshot_id"]), principal=reviewer))
    with pytest.raises(ApiError) as hidden:
        get(restricted_finding["finding_id"], principal=reader)
    assert hidden.value.code == ErrorCode.NOT_FOUND
