"""Saved federation receipts do not replay orchestration or relax access."""
import asyncio
from dataclasses import replace

import pytest

from meridian.api_common import ApiError
from meridian.config import GatewaySettings
from meridian.gateway_api.main import create_app
from meridian.gateway_api.orchestrator import OfficeResult
from meridian.security.auth import AuthorizationError, Permission, Principal, Role

from conftest import ROOT


def test_saved_receipt_survives_restart_and_requires_federation_access(tmp_path, monkeypatch):
    settings = replace(GatewaySettings.from_env(), config_dir=ROOT / "config", runtime_dir=tmp_path,
                       trusted_keys_path=tmp_path / "no-keys.json")
    app = create_app(settings)
    orchestrator = app.state.orchestrator
    principal = Principal("gw", settings.tenant_id, "GATEWAY", Role.GATEWAY_SERVICE,
                          frozenset({Permission.FEDERATION_ORCHESTRATE}), "Gateway")
    monkeypatch.setattr(orchestrator, "fetch_export", lambda region, **_: OfficeResult(region, "delivered", export=object(), verified=True, claims=1))
    monkeypatch.setattr(orchestrator, "federated_answer", lambda *args: {"status": "answered", "offices": [], "statements": [], "not_checked": ["clause_inclusion"]})
    class Body:
        async def json(self):
            return {"question": "Approvals?", "target": {"subject": "loan_approval", "amount_minor": 100,
                    "currency": "USD", "loan_type": "business", "origin_office": "DHAKA"}}
    post = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/v1/queries")
    result = asyncio.run(post(Body(), principal))
    assert result["query"]["question"] == "Approvals?"
    restarted = create_app(settings)
    get = next(route.endpoint for route in restarted.routes if getattr(route, "path", "") == "/v1/queries/{request_id}")
    assert get(result["request_id"], principal) == result
    for bad_id in ["gw_00000000000000000000", "../../relay", "gw_abc"]:
        with pytest.raises(ApiError) as error:
            get(bad_id, principal)
        assert error.value.status_code == 404
    reader = replace(principal, permissions=frozenset({Permission.READ_LOCAL}))
    with pytest.raises(AuthorizationError):
        get(result["request_id"], reader)
    with pytest.raises(AuthorizationError):
        get(result["request_id"], replace(principal, tenant_id="other"))
