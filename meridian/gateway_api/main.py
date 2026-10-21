"""Gateway HTTP API: metadata-only federation orchestration.

The gateway has no office database and no raw source volumes.  It fetches signed,
allowlisted claim exports from the two offices, verifies them against pinned public
keys, merges them in memory, and exposes redacted egress audit views.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from ..api_common import (
    ApiError,
    bearer_dependency,
    install_error_handlers,
    load_registry,
)
from ..config import GatewaySettings, load_dotenv
from ..contracts.common import (
    BUILD_VERSION,
    ErrorCode,
    canonical_datetime,
    utc_now,
)
from ..contracts.qa import QueryRequest
from ..integrity.signing import PinnedKeyRegistry
from ..security.auth import Permission
from .orchestrator import (
    FederationImportRejected,
    GatewayOrchestrator,
    OfficeUnavailable,
    RelayLog,
)


def _office_tokens(settings: GatewaySettings) -> dict[str, str | None]:
    return {
        "DHAKA": os.environ.get("DEMO_TOKEN_DHAKA_SERVICE") or None,
        "FRANKFURT": os.environ.get("DEMO_TOKEN_FRANKFURT_SERVICE") or None,
    }


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    load_dotenv()
    resolved = settings or GatewaySettings.from_env()
    registry = load_registry(resolved.config_dir)
    trusted = (
        PinnedKeyRegistry.from_json_file(resolved.trusted_keys_path)
        if Path(resolved.trusted_keys_path).exists()
        else PinnedKeyRegistry([])
    )
    relay = RelayLog(resolved.relay_log_path)
    relay.path.parent.mkdir(parents=True, exist_ok=True)
    orchestrator = GatewayOrchestrator(
        tenant_id=resolved.tenant_id,
        office_urls={
            "DHAKA": resolved.dhaka_base_url,
            "FRANKFURT": resolved.frankfurt_base_url,
        },
        office_tokens=_office_tokens(resolved),
        registry=trusted,
        relay_log=relay,
        timeout_seconds=resolved.request_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield

    app = FastAPI(
        title="Meridian Gateway API", version=BUILD_VERSION, lifespan=lifespan
    )
    install_error_handlers(app)
    app.state.orchestrator = orchestrator
    app.state.settings = resolved

    authenticate = bearer_dependency(registry)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "gateway",
            "build_version": BUILD_VERSION,
            "tenant_id": resolved.tenant_id,
            "offices": orchestrator.known_offices(),
            "database_present": "false",
            "raw_source_volumes": "none",
        }

    @app.get("/ready")
    def ready() -> JSONResponse:
        checks = {
            "principals_configured": bool(registry.configured_principal_ids()),
            "trusted_keys_pinned": bool(trusted.key_ids()),
            "office_service_tokens_configured": all(
                token is not None for token in orchestrator.office_tokens.values()
            ),
            "relay_log_dir": relay.path.parent.exists(),
        }
        return JSONResponse(
            status_code=200 if all(checks.values()) else 503,
            content={
                "ready": all(checks.values()),
                "service": "gateway",
                "checks": checks,
                "configured_principals": registry.configured_principal_ids(),
            },
        )

    @app.post("/v1/queries", status_code=201)
    async def gateway_query(request: Request, principal=Depends(authenticate)) -> dict[str, Any]:
        registry.require_permission(principal, Permission.FEDERATION_ORCHESTRATE)
        registry.require_tenant(principal, resolved.tenant_id)
        body = await request.json()
        try:
            query_request = QueryRequest.model_validate(body)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(ErrorCode.INVALID_INPUT, f"query is not valid: {exc}")
        request_id = f"gw_{utc_now().strftime('%Y%m%dT%H%M%S%f')}"

        # Demo 3 path: the requesting (processing) office owns the governing policy;
        # fetch the origin office's signed claim export, import it at the requester,
        # then ask the requester's local comparator to produce the final answer.
        from ..contracts.common import Subject

        if query_request.target.subject is Subject.GENERAL_POLICY:
            raise ApiError(ErrorCode.UNSUPPORTED_SEMANTICS, "General source questions are office-local. Submit this question to an office API.")

        if (
            query_request.target.subject is Subject.RECORD_RETENTION
            and query_request.target.origin_office is not None
            and query_request.target.processing_office is not None
        ):
            origin = query_request.target.origin_office.value.upper()
            requester = query_request.target.processing_office.value.upper()
            results = []
            try:
                origin_result = orchestrator.fetch_export(
                    origin, request_id=request_id, query=query_request
                )
                results.append(origin_result)
            except OfficeUnavailable as exc:
                from .orchestrator import OfficeResult

                origin_result = OfficeResult(
                    region=exc.region, status="unavailable", detail=exc.detail
                )
                results.append(origin_result)
            if not origin_result.verified or origin_result.export is None:
                answer = orchestrator.federated_answer(request_id, query_request, results)
                raise ApiError(
                    ErrorCode.OFFICE_UNAVAILABLE
                    if origin_result.status == "unavailable"
                    else ErrorCode.MISSING_POLICY,
                    f"origin office {origin} did not export a verified approved claim",
                    detail={"offices": answer["offices"]},
                )
            try:
                imported, comparison, _comparison_request = (
                    orchestrator.import_then_compare(
                        requester, origin_result.export, query_request
                    )
                )
            except FederationImportRejected as exc:
                raise ApiError(
                    ErrorCode.MISSING_POLICY,
                    f"requesting office {requester} rejected the verified export import",
                    detail={"import": exc.response, "errors": exc.detail},
                ) from exc
            except OfficeUnavailable as exc:
                raise ApiError(
                    ErrorCode.OFFICE_UNAVAILABLE,
                    f"requesting office {requester} could not complete the comparison: {exc.detail}",
                    detail={"unavailable": [exc.region]},
                ) from exc
            return {
                "question": query_request.question,
                "request_id": request_id,
                "federated_answer": {
                    "status": comparison["answer"]["status"],
                    "comparator_region": requester,
                    "comparison": comparison,
                    "origin_export": {
                        "origin_region": origin,
                        "claims": origin_result.claims,
                        "withheld_restricted": origin_result.withheld,
                        "reason_codes": origin_result.reason_codes,
                        "payload_bytes": origin_result.payload_bytes,
                        "payload_sha256": origin_result.payload_sha256,
                    },
                    "import": imported,
                    "offices": [
                        {
                            "region": result.region,
                            "status": result.status,
                            "claims": result.claims,
                            "withheld_restricted": result.withheld,
                            "reason_codes": result.reason_codes,
                            "payload_bytes": result.payload_bytes,
                            "payload_sha256": result.payload_sha256,
                            "detail": result.detail,
                        }
                        for result in results
                    ],
                    "not_checked": ["clause_inclusion"],
                    "no_raw_source_text_transferred": True,
                    "generated_at": canonical_datetime(utc_now()),
                },
                "gateway_note": (
                    "the gateway relayed a signed structured export and the requesting "
                    "office compared it with its own policy; passage text was stripped "
                    "from the comparator transport view"
                ),
            }

        results = []
        unavailable: list[str] = []
        for region in orchestrator.known_offices():
            try:
                results.append(
                    orchestrator.fetch_export(region, request_id=request_id, query=query_request)
                )
            except OfficeUnavailable as exc:
                unavailable.append(exc.region)
                from .orchestrator import OfficeResult

                results.append(
                    OfficeResult(region=exc.region, status="unavailable", detail=exc.detail)
                )

        answer = orchestrator.federated_answer(request_id, query_request, results)
        if not any(result.export is not None for result in results):
            if unavailable:
                raise ApiError(
                    ErrorCode.OFFICE_UNAVAILABLE,
                    "no office could serve the federated subquery",
                    detail={"unavailable": unavailable},
                )
            raise ApiError(
                ErrorCode.MISSING_POLICY,
                "no office exported claims for the supplied target facts",
                detail={"offices": answer["offices"]},
            )
        return {
            "question": query_request.question,
            "request_id": request_id,
            "federated_answer": answer,
            "gateway_note": (
                "the gateway merged signed structured claims only; no raw source text "
                "crossed the office boundary and clause inclusion stays not_checked"
            ),
        }

    @app.get("/v1/audit/egress")
    def gateway_egress(request: Request, principal=Depends(authenticate)) -> dict[str, Any]:
        registry.require_permission(principal, Permission.AUDIT_READ)
        entries = relay.entries()
        return {
            "relay_events": entries,
            "counts": {
                "total": len(entries),
                "delivered": sum(1 for item in entries if item.get("outcome") == "delivered"),
                "blocked": sum(1 for item in entries if item.get("outcome") == "denied"),
                "signature_failed": sum(
                    1 for item in entries if item.get("outcome") == "signature_failed"
                ),
                "unavailable": sum(1 for item in entries if item.get("outcome") == "unavailable"),
                "payload_bytes": sum(int(item.get("payload_bytes") or 0) for item in entries),
            },
            "raw_source_text_transferred": 0,
            "generated_at": canonical_datetime(utc_now()),
        }

    return app


__all__ = ["create_app"]


if __name__ == "__main__":  # pragma: no cover - process entry point
    import uvicorn

    from ..config import load_dotenv

    import os

    load_dotenv()
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
        workers=1,
    )
