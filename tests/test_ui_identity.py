"""Signed browser-account identities preserve office-side authorization."""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from meridian.security.auth import AuthenticationError, AuthorizationError, Permission, PrincipalRegistry, Role


@pytest.fixture
def identity(tmp_path, monkeypatch):
    key = os.urandom(32)
    key_path = tmp_path / "key"
    key_path.write_bytes(key)
    monkeypatch.setenv("UI_AUTH_KEY_PATH", str(key_path))

    def token(**overrides):
        claims = dict(v=1, sub=str(uuid4()), username="alice", role="reader", offices=["dhaka"], restricted=False, office="DHAKA", tenant="meridian_demo", iat=int(time.time()), exp=int(time.time()) + 45)
        claims.update(overrides)
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        signed = f"ui1.{payload}"
        signature = base64.urlsafe_b64encode(hmac.digest(key, signed.encode(), hashlib.sha256)).decode().rstrip("=")
        return f"{signed}.{signature}"

    return PrincipalRegistry([]), token, key_path


@pytest.mark.parametrize("role,ingest,review,audit", [("admin", True, True, True), ("reviewer", True, True, True), ("uploader", True, False, False), ("reader", False, False, False)])
def test_permissions_are_derived_from_signed_account_role(identity, role, ingest, review, audit):
    registry, token, _ = identity
    principal = registry.authenticate(token(role=role))
    assert principal.principal_id == "user:alice"
    assert principal.role == Role(role)
    assert principal.has(Permission.INGEST) is ingest
    assert principal.has(Permission.REVIEW) is review
    assert principal.has(Permission.AUDIT_READ) is audit
    assert principal.has(Permission.READ_LOCAL)
    assert principal.has(Permission.QUERY_LOCAL)
    assert principal.has(Permission.READ_RESTRICTED) is (role == "admin")
    assert not principal.has(Permission.FEDERATION_SERVE)
    assert not principal.has(Permission.INTERNAL_EGRESS_READ)
    assert registry.can_read_source(principal, region="DHAKA", restricted=False)
    assert not registry.can_read_source(principal, region="FRANKFURT", restricted=False)
    with pytest.raises(AuthorizationError):
        registry.require_tenant(principal, "other-tenant")


@pytest.mark.parametrize("claims", [dict(role="office_service"), dict(role="gateway_service"), dict(office="FRANKFURT"), dict(offices=[]), dict(offices=["dhaka", "dhaka"]), dict(offices=["other"]), dict(restricted="true"), dict(exp=0), dict(exp=int(time.time())+600), dict(iat=int(time.time())+100), dict(sub="alice"), dict(sub=5), dict(username="bad name"), dict(permissions=["review"]), dict(tenant=""), dict(office="GATEWAY"), dict(office="GATEWAY",role="reviewer"), dict(office="GATEWAY", role="reviewer", offices=["dhaka", "frankfurt"])])
def test_invalid_or_excessive_identity_is_rejected(identity, claims):
    registry, token, _ = identity
    with pytest.raises(AuthenticationError):
        registry.authenticate(token(**claims))


def test_signature_expiry_and_missing_key_fail_closed(identity):
    registry, token, path = identity
    value = token()
    with pytest.raises(AuthenticationError):
        registry.authenticate(value[:-1] + ("A" if value[-1] != "A" else "B"))
    path.unlink()
    with pytest.raises(AuthenticationError):
        registry.authenticate(value)


def test_restricted_access_and_gateway_are_explicit(identity):
    registry, token, _ = identity
    assert registry.authenticate(token(restricted=True)).has(Permission.READ_RESTRICTED)
    principal = registry.authenticate(token(role="reviewer", restricted=True, offices=["dhaka", "frankfurt"], office="GATEWAY"))
    assert principal.permissions == frozenset({Permission.FEDERATION_ORCHESTRATE, Permission.AUDIT_READ})


def test_node_issued_account_token_is_verified_by_python(identity, tmp_path):
    registry, _, key_path = identity
    root = Path(__file__).resolve().parents[1]
    script = """
import {createAuthStore} from './frontend/server/auth.mjs';
const store=createAuthStore();
const login=await store.login('admin','admin');
process.stdout.write(store.delegationToken(login.user,'DHAKA','meridian_demo'));
store.close();
"""
    # Isolated account DB/key; no real office data or credentials are touched.
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=root, env={**os.environ, "UI_AUTH_DB_PATH": str(tmp_path / "accounts.sqlite"), "UI_AUTH_KEY_PATH": str(key_path)}, capture_output=True, text=True, check=True)
    principal = registry.authenticate(result.stdout)
    assert principal.principal_id == "user:admin"
    assert principal.role == Role.ADMIN
    assert principal.has(Permission.REVIEW)


def test_real_office_http_enforces_account_scope_and_records_review_actor(identity, dhaka_full, monkeypatch):
    import asyncio
    import httpx
    from meridian.ingestion.worker import OfficeWorker
    from meridian.office_api.main import OfficeRuntime, create_app

    registry, token, _ = identity
    office = dhaka_full
    runtime = OfficeRuntime(settings=office.settings, registry=registry, trusted_keys=office.registry, signer=office.signer, store=office.store, worker=OfficeWorker(store=office.store, settings=office.settings, signer=office.signer))
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(office.settings)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://office") as client:
            def headers(**claims):
                return {"Authorization": f"Bearer {token(**claims)}"}

            assert (await client.get("/v1/sources")).status_code == 401
            sources = (await client.get("/v1/sources", headers=headers())).json()["sources"]
            restricted = office.store.find_source_version("dhaka_credit_note_restricted", "v1")
            assert restricted.source_id not in {source["source_id"] for source in sources}
            assert (await client.get(f"/v1/sources/{restricted.source_id}", headers=headers())).status_code == 404
            assert (await client.get(f"/v1/sources/{restricted.source_id}", headers=headers(restricted=True))).status_code == 200
            assert (await client.get("/v1/sources", headers=headers(office="FRANKFURT", offices=["frankfurt"]))).status_code == 403
            assert (await client.get("/v1/sources", headers=headers(tenant="other"))).status_code == 403
            assert (await client.get("/v1/activity", headers=headers())).status_code == 403
            findings = (await client.get("/v1/findings", headers=headers(role="reviewer", restricted=True))).json()["findings"]
            finding = findings[0]
            path = f"/v1/findings/{finding['finding_id']}/reviews"
            body = {"action": "acknowledge", "reason": "Account attribution test", "expected_snapshot_id": finding["snapshot_id"], "actor": "user:admin"}
            for role in ["reader", "uploader"]:
                assert (await client.post(path, json=body, headers=headers(role=role))).status_code == 403
            reviewed = await client.post(path, json=body, headers=headers(role="reviewer", restricted=True))
            assert reviewed.status_code == 201
            assert reviewed.json()["actor"] == "user:alice"

    asyncio.run(run())
