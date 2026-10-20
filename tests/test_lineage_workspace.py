"""Authorization and real stored provenance exposed to the verification workspace."""
from dataclasses import replace

import pytest

from meridian.api_common import ApiError
from meridian.contracts.common import ErrorCode
from meridian.ingestion.worker import OfficeWorker
from meridian.office_api.main import OfficeRuntime, create_app
from meridian.security.auth import Permission, Principal, PrincipalRegistry, Role
from conftest import FIXTURES


def test_source_and_finding_lineage_preserve_provenance_and_access(dhaka_full, monkeypatch):
    office = dhaka_full
    runtime = OfficeRuntime(settings=office.settings,
        registry=PrincipalRegistry.from_file(FIXTURES.parent / "config/principals.json"),
        trusted_keys=office.registry, signer=office.signer, store=office.store,
        worker=OfficeWorker(store=office.store, settings=office.settings, signer=office.signer))
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(office.settings)
    def endpoint(path):
        return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)
    reader = Principal(principal_id="reader", tenant_id="meridian_demo", office="DHAKA",
        role=Role.READER, display_name="Reader", permissions=frozenset({Permission.READ_LOCAL}))
    reviewer = replace(reader, permissions=frozenset({Permission.READ_LOCAL, Permission.READ_RESTRICTED}))
    sources = office.store.list_sources()
    public = next(s for s in sources if not s.restricted)
    restricted = next(s for s in sources if s.restricted)
    # A stale/incorrect graph flag cannot bypass the underlying source permission.
    with office.store.db.transaction() as connection:
        connection.execute("UPDATE nodes SET restricted = 0")
    get_source = endpoint("/v1/sources/{source_id}/lineage")
    graph = get_source(public.source_id, principal=reader)["lineage"]
    assert graph["root_id"] == f"source:{public.source_id}"
    assert any(n["node_type"] == "claim_revision" and n["attributes"].get("quote") for n in graph["nodes"])
    assert all(n["attributes"].get("source_id") != restricted.source_id for n in graph["nodes"])
    assert not any(restricted.source_id in n["node_id"] for n in graph["nodes"])
    ids = {n["node_id"] for n in graph["nodes"]}
    assert all(e["from_node_id"] in ids and e["to_node_id"] in ids for e in graph["edges"])
    with pytest.raises(ApiError) as hidden:
        get_source(restricted.source_id, principal=reader)
    assert hidden.value.code == ErrorCode.NOT_FOUND
    assert get_source(restricted.source_id, principal=reviewer)["lineage"]["nodes"]
    list_findings = endpoint("/v1/findings")
    finding = next(f for f in list_findings(principal=reviewer)["findings"] if f["finding_type"] == "stale_guidance")
    get_finding = endpoint("/v1/findings/{finding_id}/lineage")
    graph = get_finding(finding["finding_id"], principal=reader)["lineage"]
    assert graph["root_id"] == f"finding:{finding['finding_id']}"
    assert {"finding", "claim_revision", "version"} <= {n["node_type"] for n in graph["nodes"]}
    for path, key in [(get_source, "missing-source"), (get_finding, "missing-finding")]:
        with pytest.raises(ApiError) as missing:
            path(key, principal=reader)
        assert missing.value.code == ErrorCode.NOT_FOUND
