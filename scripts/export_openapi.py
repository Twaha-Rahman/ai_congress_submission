"""Export deterministic OpenAPI documents for both HTTP services.

    .venv/bin/python scripts/export_openapi.py

The office app is built against temporary paths so exporting schemas never touches
demo databases, keys or source volumes.  Only the gateway document is unconditional;
office sections are still emitted with no secrets because FastAPI documents the route
contracts, not runtime configuration.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import GatewaySettings, OfficeSettings, load_dotenv  # noqa: E402
from meridian.contracts.federation import (  # noqa: E402
    FederationExport,
    FederationSubquery,
)
from meridian.contracts.manifest import SourceManifest  # noqa: E402
from meridian.contracts.qa import QueryRequest  # noqa: E402
from meridian.contracts.verification import EvidenceBundle  # noqa: E402
from meridian.gateway_api.main import create_app as create_gateway_app  # noqa: E402
from meridian.office_api.main import create_app as create_office_app  # noqa: E402

OUTPUT = ROOT / "docs" / "openapi"

QUERY_EXAMPLE = {
    "question": "How many approvals are required for a USD 30,000 business loan originated in Dhaka?",
    "target": {
        "subject": "loan_approval",
        "loan_type": "business",
        "currency": "USD",
        "origin_office": "DHAKA",
        "amount_minor": 3_000_000,
    },
    "valid_at": "2026-03-03T12:00:00Z",
    "known_at": "2026-03-10T12:00:00Z",
    "mode": "replay",
}

FEDERATION_EXAMPLE = {
    "request_id": "example-federation-1",
    "subject": "record_retention",
    "target": {
        "kind": "record",
        "subject": "record_retention",
        "record_class": "loan_records",
        "origin_office": "DHAKA",
        "processing_office": "FRANKFURT",
        "product": "MTF_CROSS_OFFICE",
        "starting_event": "loan_closure",
    },
    "valid_at": "2026-03-03T12:00:00Z",
    "known_at": "2026-03-10T12:00:00Z",
    "egress_policy": "structured_claims_only",
}

REVIEW_EXAMPLE = {
    "action": "acknowledge",
    "reason": "Reviewed against the signed policy clause.",
    "referenced_revision_ids": ["rev_example"],
}


def _merge_model(document: dict, model: Any) -> str:
    """Add a Pydantic model (and nested definitions) to ``components.schemas``."""

    schema = TypeAdapter(model).json_schema(
        ref_template="#/components/schemas/{model}"
    )
    definitions = schema.pop("$defs", {})
    components = document.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in definitions.items():
        components.setdefault(name, definition)
    components[model.__name__] = schema
    return model.__name__


def _json_body(schema: dict, *, example: dict | None = None) -> dict:
    media: dict[str, Any] = {"schema": schema}
    if example is not None:
        media["example"] = example
    return {"required": True, "content": {"application/json": media}}


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _enrich(document: dict) -> None:
    """Document auth, manually parsed request bodies and representative examples.

    Several handlers parse ``Request.json()`` themselves so that they can return the
    project's stable error schema instead of FastAPI's default 422 body.  FastAPI
    therefore cannot infer those bodies; this post-processing step documents the same
    Pydantic contracts and examples without changing runtime behavior.
    """

    query = _merge_model(document, QueryRequest)
    subquery = _merge_model(document, FederationSubquery)
    export = _merge_model(document, FederationExport)
    bundle = _merge_model(document, EvidenceBundle)
    manifest = _merge_model(document, SourceManifest)

    schemas = document["components"]["schemas"]
    schemas["SlackIngestion"] = {
        "type": "object",
        "required": ["manifest"],
        "properties": {
            "manifest": _ref(manifest),
            "event": {"type": "object", "additionalProperties": True},
            "events": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
            "mode": {"type": "string", "enum": ["live", "cached", "replay"]},
        },
        "oneOf": [{"required": ["event"]}, {"required": ["events"]}],
        "additionalProperties": True,
    }
    schemas["ReviewRequest"] = {
        "type": "object",
        "required": ["action", "reason"],
        "properties": {
            "action": {"type": "string", "enum": ["acknowledge", "resolve", "dismiss"]},
            "reason": {"type": "string", "minLength": 1},
            "referenced_revision_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }
    schemas["FederationImportRequest"] = {
        "type": "object",
        "required": ["export"],
        "properties": {"export": _ref(export)},
        "additionalProperties": False,
    }

    paths = document.get("paths", {})
    bodies: dict[str, tuple[dict, dict | None]] = {
        "/v1/ingestions/slack": (_ref("SlackIngestion"), None),
        "/v1/findings/{finding_id}/reviews": (
            _ref("ReviewRequest"),
            REVIEW_EXAMPLE,
        ),
        "/v1/queries": (_ref(query), {"question": "Who reviews open orders, and how often?", "source_ids": []}
            if "/v1/ingestions/pdf" in paths else QUERY_EXAMPLE),
        "/v1/verifications/bundle": (_ref(bundle), None),
        "/v1/comparisons": (_ref(query), QUERY_EXAMPLE),
        "/v1/federation/claims": (_ref(subquery), FEDERATION_EXAMPLE),
        "/v1/federation/imports": (_ref("FederationImportRequest"), None),
    }
    for path, (schema, example) in bodies.items():
        operation = paths.get(path, {}).get("post")
        if operation is not None:
            operation["requestBody"] = _json_body(schema, example=example)

    document.setdefault("components", {})["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "opaque demo token supplied through environment variables",
            "description": (
                "Protected routes require `Authorization: Bearer <token>`. Tokens are "
                "read from the configured environment and never embedded in this document."
            ),
        }
    }
    for path, operations in paths.items():
        if path in {"/health", "/ready"}:
            continue
        for operation in operations.values():
            operation.setdefault("security", [{"BearerAuth": []}])

    info = document.setdefault("info", {})
    info["description"] = (
        "Meridian backend API. Protected routes use an opaque bearer token mapped to a "
        "server-side principal; tenant and office are derived from that principal, never "
        "from request fields. Exactly one of `event` or `events` is supplied to the Slack "
        "ingestion route. Nullable values are shown as `anyOf` with `null` in the schemas."
    )


def _write(name: str, document: dict) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{name}.json"
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    routes = sorted(
        path for path in document.get("paths", {}) for path in document["paths"][path]
    )
    print(f"{name:<10} {len(routes):>2} operations -> {path.relative_to(ROOT)}")
    return path


def main() -> int:
    load_dotenv()
    with tempfile.TemporaryDirectory(prefix="meridian-openapi-") as temporary:
        base = Path(temporary)
        office_settings = replace(
            OfficeSettings.from_env("DHAKA"),
            db_path=base / "dhaka" / "meridian.db",
            source_dir=base / "dhaka" / "sources",
            key_dir=base / "keys" / "dhaka",
            trusted_keys_path=base / "trusted_keys.json",
        )
        office = create_office_app(office_settings)
        office_document = office.openapi()
        _enrich(office_document)
        _write("office", office_document)

    gateway = create_gateway_app(GatewaySettings.from_env())
    gateway_document = gateway.openapi()
    _enrich(gateway_document)
    _write("gateway", gateway_document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
