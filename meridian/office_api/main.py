"""Office HTTP API: ingestion, queries, evidence, reviews and federation.

The app authenticates bearer tokens against the static demo identity map, derives
tenant/office from the server-side principal, and records audited egress for every
offbound payload.  Integrity failures are structured verification reports, not
generic 500s.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..api_common import (
    ApiError,
    bearer_dependency,
    install_error_handlers,
    load_registry,
    require,
)
from ..config import OfficeSettings, load_dotenv
from ..contracts.common import (
    BUILD_VERSION,
    EgressChannel,
    EgressOutcome,
    ErrorCode,
    Mode,
    ReviewAction,
    ReviewState,
    Subject,
    canonical_datetime,
    utc_now,
)
from ..contracts.federation import EgressEvent, FederationExport, FederationSubquery
from ..contracts.findings import ReviewEvent
from ..contracts.manifest import SourceManifest
from ..contracts.qa import QueryRequest
from ..contracts.verification import EvidenceBundle
from ..federation.exchange import (
    ExportDenied,
    RemoteClaimConflict,
    StaleRemoteSnapshot,
    UnknownRemoteSnapshot,
    build_export,
    import_export,
    snapshot_id_for,
    target_fingerprint,
    verify_export,
)
from ..ingestion.worker import OfficeWorker
from ..integrity.bundles import verify_bundle
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..integrity.signing import PinnedKeyRegistry, Signer
from ..queries.engine import QueryEngine
from ..queries.evidence import build_bundle, verify_source_copy
from ..queries.lineage import lineage_for_node
from ..rules.intervals import scope_matches_target
from ..security.auth import Permission, PrincipalRegistry
from ..storage.db import SCHEMA_VERSION, Database
from ..storage.store import JobRow, OfficeStore, SourceRow, new_id
from ..temporal.snapshots import select_snapshot


@dataclass
class OfficeRuntime:
    settings: OfficeSettings
    registry: PrincipalRegistry
    trusted_keys: PinnedKeyRegistry
    signer: Signer
    store: OfficeStore
    worker: OfficeWorker


def build_runtime(settings: OfficeSettings | None = None) -> OfficeRuntime:
    load_dotenv()
    resolved = settings or OfficeSettings.from_env()
    registry = load_registry(resolved.config_dir)
    trusted = (
        PinnedKeyRegistry.from_json_file(resolved.trusted_keys_path)
        if Path(resolved.trusted_keys_path).exists()
        else PinnedKeyRegistry([])
    )
    signer = Signer.load_or_create(
        key_id=resolved.key_id, region=resolved.region, key_dir=resolved.key_dir
    )
    # A fresh container or a reset removes the demo directories. Create the immutable
    # source root and staging area at startup so readiness reflects a usable office.
    resolved.source_dir.mkdir(parents=True, exist_ok=True)
    (resolved.source_dir / "_staging").mkdir(parents=True, exist_ok=True)
    store = OfficeStore(
        Database(resolved.db_path), tenant_id=resolved.tenant_id, region=resolved.region
    )
    worker = OfficeWorker(store=store, settings=resolved, signer=signer)
    return OfficeRuntime(
        settings=resolved,
        registry=registry,
        trusted_keys=trusted,
        signer=signer,
        store=store,
        worker=worker,
    )


def _source_dict(source: SourceRow, *, include_manifest: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_id": source.source_id,
        "source_identity": source.source_identity,
        "version_label": source.version_label,
        "source_type": source.source_type,
        "subject": source.subject,
        "policy_family": source.policy_family,
        "authority": source.authority,
        "sensitivity": source.sensitivity,
        "office_export": source.office_export,
        "hosted_model": source.hosted_model,
        "content_sha256": source.content_sha256,
        "source_sha256": source.source_sha256,
        "merkle_root": source.merkle_root,
        "tree_size": source.tree_size,
        "parser_version": source.parser_version,
        "status": source.status,
        "ingested_at": canonical_datetime(source.ingested_at),
        "publication_time": canonical_datetime(source.publication_time)
        if source.publication_time
        else None,
        "effective_from": canonical_datetime(source.effective_from) if source.effective_from else None,
        "effective_to": canonical_datetime(source.effective_to) if source.effective_to else None,
        "supersedes": source.supersedes,
    }
    if include_manifest:
        payload["manifest"] = source.manifest.model_dump(mode="json")
    return payload


def _parse_iso(value: Any) -> datetime | None:
    """Parse an optional ISO-8601 expectation supplied with an import request."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _job_dict(job: JobRow) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "mode": job.mode,
        "stage_modes": job.stage_modes,
        "progress": job.progress,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error_code": job.error_code,
        "review_reason": job.review_reason,
        "source_id": job.source_id,
        "created_at": canonical_datetime(job.created_at),
        "started_at": canonical_datetime(job.started_at) if job.started_at else None,
        "finished_at": canonical_datetime(job.finished_at) if job.finished_at else None,
        "updated_at": canonical_datetime(job.updated_at),
        "source_identity": (job.request.get("manifest") or {}).get("source_identity"),
        "version_label": (job.request.get("manifest") or {}).get("version_label"),
    }


def _resolve_mode(settings: OfficeSettings, requested: str | None) -> Mode:
    value = (requested or settings.default_mode or "replay").strip().lower()
    try:
        return Mode(value)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.INVALID_INPUT,
            f"unsupported mode {value!r}; expected one of live, cached, replay",
        ) from exc


def _stage_upload(settings: OfficeSettings, raw: bytes, extension: str) -> Path:
    staging = settings.source_dir / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / f"{uuid.uuid4().hex}.{extension}"
    path.write_bytes(raw)
    return path


def create_app(settings: OfficeSettings | None = None) -> FastAPI:
    runtime = build_runtime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.worker.start()
        try:
            yield
        finally:
            runtime.worker.stop()

    app = FastAPI(
        title=f"Meridian Office API ({runtime.settings.region})",
        version=BUILD_VERSION,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.state.runtime = runtime

    authenticate = bearer_dependency(runtime.registry)
    registry = runtime.registry
    store = runtime.store
    office = runtime.settings.region

    def _require_office_scope(principal, permission: Permission) -> None:
        """Central tenant/office/permission gate for every office endpoint."""

        require(registry, principal, permission)
        registry.require_tenant(principal, store.tenant_id)
        registry.require_office(principal, office)

    def _source_readable(principal, source: SourceRow | None) -> bool:
        if source is None or source.region.upper() != office.upper():
            return False
        return registry.can_read_source(
            principal, region=source.region, restricted=source.restricted
        )

    def _answer_readable(principal, record) -> bool:
        """Re-authorize every local source referenced by a stored answer.

        A signed answer created for a privileged caller is not disclosable to a
        caller who cannot read one of the sources it cites; the stored bytes are
        never modified.
        """

        try:
            source_ids = record.payload.local_source_ids()
        except (ValueError, TypeError):
            return False
        for source_id in source_ids:
            source = store.get_source(source_id)
            if not _source_readable(principal, source):
                return False
        return True

    def _finding_readable(principal, record) -> bool:
        for revision_id in record.payload.claim_revision_ids:
            claim = store.get_claim(revision_id)
            if claim is None:
                return False
            source = store.get_source(claim.payload.source_id)
            if not _source_readable(principal, source):
                return False
        return True

    def _job_readable(principal, job) -> bool:
        if job.source_id:
            return _source_readable(principal, store.get_source(job.source_id))
        manifest = (job.request or {}).get("manifest") or {}
        if manifest.get("sensitivity") == "restricted":
            return principal.has(Permission.READ_RESTRICTED)
        return True

    def _claim_review_readable(principal, review: dict) -> bool:
        return _source_readable(principal, store.get_source(review.get("source_id", "")))

    # ------------------------------------------------------------------ health
    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "office",
            "build_version": BUILD_VERSION,
            "schema_version": SCHEMA_VERSION,
            **runtime.settings.as_public_dict(),
        }

    @app.get("/ready")
    def ready() -> JSONResponse:
        checks: dict[str, bool] = {
            "database_present": Path(runtime.settings.db_path).exists(),
            "database_integrity_ok": runtime.store.db.integrity_check() == "ok",
            "signing_key_available": bool(runtime.signer.public_key_hex),
            "principals_configured": bool(runtime.registry.configured_principal_ids()),
            "source_dir_present": Path(runtime.settings.source_dir).exists(),
            "worker_alive": runtime.worker._thread is not None and runtime.worker._thread.is_alive(),
        }
        body = {
            "ready": all(checks.values()),
            "service": "office",
            "region": office,
            "checks": checks,
            "configured_principals": runtime.registry.configured_principal_ids(),
            "model_configured": runtime.settings.has_model_credentials,
            "default_mode": runtime.settings.default_mode,
        }
        return JSONResponse(status_code=200 if body["ready"] else 503, content=body)

    # -------------------------------------------------------------- ingestion
    @app.post("/v1/ingestions/pdf", status_code=202)
    async def ingest_pdf(
        file: UploadFile = File(...),
        manifest: str = Form(...),
        mode: str | None = Form(default=None),
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.INGEST)
        try:
            manifest_model = SourceManifest.model_validate_json(manifest)
        except Exception as exc:  # noqa: BLE001 - surface as structured input error
            raise ApiError(ErrorCode.INVALID_INPUT, f"manifest is not a valid SourceManifest: {exc}")
        if manifest_model.region.value != office:
            raise ApiError(
                ErrorCode.INVALID_INPUT,
                "manifest region does not match this office",
                detail={"manifest_region": manifest_model.region.value, "office": office},
            )
        raw = await file.read()
        if not raw:
            raise ApiError(ErrorCode.INVALID_INPUT, "uploaded file is empty")
        staged = _stage_upload(runtime.settings, raw, "pdf")
        job = store.create_job(
            kind="pdf",
            mode=_resolve_mode(runtime.settings, mode),
            request={
                "manifest": manifest_model.model_dump(mode="json"),
                "file_ref": str(staged),
                "request_id": new_id("req"),
                "uploaded_by": principal.principal_id,
            },
        )
        return {
            "job": _job_dict(job),
            "duplicate_upload_detected": False,
            "staged_bytes": len(raw),
        }

    @app.post("/v1/ingestions/slack", status_code=202)
    async def ingest_slack(
        request: Request,
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.INGEST)
        body = await request.json()
        if not isinstance(body, dict) or "manifest" not in body or "event" not in body and "events" not in body:
            raise ApiError(
                ErrorCode.INVALID_INPUT,
                "body must contain 'manifest' and a saved Slack 'event' or 'events' payload",
            )
        try:
            manifest_model = SourceManifest.model_validate(body["manifest"])
        except Exception as exc:  # noqa: BLE001
            raise ApiError(ErrorCode.INVALID_INPUT, f"manifest is not a valid SourceManifest: {exc}")
        if manifest_model.region.value != office:
            raise ApiError(ErrorCode.INVALID_INPUT, "manifest region does not match this office")
        slack_payload = {key: value for key, value in body.items() if key not in {"manifest", "mode"}}
        raw = canonical_json_bytes(slack_payload)
        staged = _stage_upload(runtime.settings, raw, "json")
        job = store.create_job(
            kind="slack",
            mode=_resolve_mode(runtime.settings, body.get("mode")),
            request={
                "manifest": manifest_model.model_dump(mode="json"),
                "file_ref": str(staged),
                "request_id": new_id("req"),
                "uploaded_by": principal.principal_id,
            },
        )
        return {"job": _job_dict(job), "staged_bytes": len(raw)}

    # -------------------------------------------------------------------- jobs
    @app.get("/v1/jobs")
    def list_jobs(
        limit: int = Query(default=50, le=200),
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        visible = [
            _job_dict(job) for job in store.list_jobs(limit=limit) if _job_readable(principal, job)
        ]
        return {"jobs": visible, "count": len(visible)}

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        job = store.get_job(job_id)
        if job is None or not _job_readable(principal, job):
            raise ApiError(ErrorCode.NOT_FOUND, "no such job")
        return {"job": _job_dict(job)}

    # ----------------------------------------------------------------- sources
    @app.get("/v1/sources")
    def list_sources(principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        visible = [
            _source_dict(source, include_manifest=False)
            for source in store.list_sources()
            if _source_readable(principal, source)
        ]
        return {"sources": visible, "count": len(visible)}

    @app.get("/v1/sources/{source_id}")
    def get_source(source_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        source = store.get_source(source_id)
        if not _source_readable(principal, source):
            raise ApiError(ErrorCode.NOT_FOUND, "no such source")
        return {
            "source": _source_dict(source),
            "clauses": [{"clause_id": clause.clause_id, "page": clause.page,
                         "section": clause.section}
                        for clause in store.clauses_for_source(source_id)],
        }

    @app.get("/v1/sources/{source_id}/lineage")
    def source_lineage(source_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        if not _source_readable(principal, store.get_source(source_id)):
            raise ApiError(ErrorCode.NOT_FOUND, "no such source")
        graph = lineage_for_node(store, f"source:{source_id}",
                                 allowed_restricted=principal.has(Permission.READ_RESTRICTED))
        return {"lineage": graph.model_dump(mode="json")}

    @app.post("/v1/sources/{source_id}/comparisons", status_code=202)
    def recheck_source(source_id: str, mode: str | None = None,
                       principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.INGEST)
        source = store.get_source(source_id)
        if not _source_readable(principal, source):
            raise ApiError(ErrorCode.NOT_FOUND, "no such source")
        if source.subject != Subject.GENERAL_POLICY.value:
            raise ApiError(ErrorCode.INVALID_INPUT, "comparison retry requires a general-policy source")
        job = store.create_job(kind="policy_comparison", mode=_resolve_mode(runtime.settings, mode),
            request={"source_id": source_id, "manifest": source.manifest.model_dump(mode="json")})
        return {"job": _job_dict(job)}

    @app.get("/v1/sources/{source_id}/content")
    def get_source_content(source_id: str, principal=Depends(authenticate)):
        _require_office_scope(principal, Permission.READ_LOCAL)
        source = store.get_source(source_id)
        if not _source_readable(principal, source):
            raise ApiError(ErrorCode.NOT_FOUND, "no such source")
        content_dir = runtime.settings.source_dir / source.region.lower()
        matches = sorted(content_dir.glob(f"{source.source_sha256}.*"))
        if not matches:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                "stored original bytes are not present for this source",
            )
        return FileResponse(
            path=matches[0],
            media_type="application/pdf" if source.source_type == "pdf" else "application/json",
            filename=f"{source.source_identity}__{source.version_label}{matches[0].suffix}",
        )

    # -------------------------------------------------------- claims/findings
    @app.get("/v1/claims")
    def list_claims(
        subject: str | None = None,
        include_review: bool = False,
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        claims: list[dict[str, Any]] = []
        for record in store.claim_rows(subject=subject, include_review=include_review):
            source = store.get_source(record.payload.source_id)
            if not _source_readable(principal, source):
                continue
            claims.append(
                {
                    "revision_id": record.payload.revision_id,
                    "claim_id": record.payload.claim_id,
                    "subject": record.payload.subject.value,
                    "rule": record.payload.rule.model_dump(mode="json"),
                    "scope": record.payload.scope.model_dump(mode="json"),
                    "authority": record.payload.authority.value,
                    "policy_family": record.payload.policy_family,
                    "status": record.payload.status.value,
                    "origin": record.origin.value,
                    "source_id": record.payload.source_id,
                    "source_identity": record.payload.source_identity,
                    "source_version_label": record.payload.source_version_label,
                    "valid_from": canonical_datetime(record.payload.valid_from)
                    if record.payload.valid_from
                    else None,
                    "valid_to": canonical_datetime(record.payload.valid_to)
                    if record.payload.valid_to
                    else None,
                    "system_from": canonical_datetime(record.payload.system_from),
                    "system_to": canonical_datetime(record.system_to) if record.system_to else None,
                    "payload_hash": record.payload_hash,
                    "signature": record.signature,
                    "key_id": record.key_id,
                    "extraction_mode": record.payload.extraction.mode,
                    "review_state": record.review_state,
                }
            )
        return {"claims": claims, "count": len(claims)}

    @app.get("/v1/claims/reviews")
    def list_claim_reviews(principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        visible = [
            review
            for review in store.list_claim_reviews()
            if _claim_review_readable(principal, review)
        ]
        return {"reviews": visible, "count": len(visible)}

    @app.get("/v1/findings")
    def list_findings(
        finding_type: str | None = None,
        alert: bool | None = None,
        review_state: str | None = None,
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        findings = []
        for record in store.list_findings(
            finding_type=finding_type, alert=alert, review_state=review_state
        ):
            # Inaccessible findings are absent, not redacted metadata: a reader without
            # read_restricted must not learn that a restricted finding exists.
            if not _finding_readable(principal, record):
                continue
            payload = record.payload
            findings.append(
                {
                    "finding_id": payload.finding_id,
                    "finding_key": payload.finding_key,
                    "finding_type": payload.finding_type.value,
                    "severity": payload.severity.value,
                    "subject": payload.subject.value,
                    "alert": payload.severity.value in {"high", "critical"},
                    "explanation_code": payload.explanation_code.value,
                    "affected_scope": payload.affected_scope.model_dump(mode="json"),
                    "affected_valid_interval": payload.affected_valid_interval.model_dump(mode="json"),
                    "authority_basis": payload.authority_basis,
                    "claim_revision_ids": payload.claim_revision_ids,
                    "detail": payload.detail,
                    "evidence": [item.model_dump(mode="json") for item in payload.evidence],
                    "review_state": record.review_state.value,
                    "snapshot_id": record.snapshot_id,
                    "snapshot_hash": record.snapshot_hash,
                    "signature": record.signature,
                    "key_id": record.key_id,
                    "created_at": canonical_datetime(payload.created_at),
                }
            )
        return {"findings": findings, "count": len(findings)}

    @app.get("/v1/findings/{finding_id}")
    def get_finding(finding_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        record = store.get_finding(finding_id)
        if record is None or not _finding_readable(principal, record):
            raise ApiError(ErrorCode.NOT_FOUND, "no such finding")
        payload = record.payload
        return {
            "finding": {
                "payload": payload.model_dump(mode="json"),
                "snapshot_id": record.snapshot_id,
                "snapshot_hash": record.snapshot_hash,
                "signature": record.signature,
                "key_id": record.key_id,
                "review_state": record.review_state.value,
                "superseded_by_snapshot_id": record.superseded_by_snapshot_id,
            },
            "reviews": [
                event.model_dump(mode="json")
                for event in store.review_events(finding_id)
            ],
        }

    @app.get("/v1/findings/{finding_id}/lineage")
    def finding_lineage(finding_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        record = store.get_finding(finding_id)
        if record is None or not _finding_readable(principal, record):
            raise ApiError(ErrorCode.NOT_FOUND, "no such finding")
        graph = lineage_for_node(store, f"finding:{finding_id}",
                                 allowed_restricted=principal.has(Permission.READ_RESTRICTED))
        return {"lineage": graph.model_dump(mode="json")}

    @app.post("/v1/findings/{finding_id}/reviews", status_code=201)
    async def review_finding(
        finding_id: str,
        request: Request,
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.REVIEW)
        record = store.get_finding(finding_id)
        if record is None or not _finding_readable(principal, record):
            raise ApiError(ErrorCode.NOT_FOUND, "no such finding")
        body = await request.json()
        if not isinstance(body, dict):
            raise ApiError(ErrorCode.INVALID_INPUT, "body must be a JSON object")
        expected_snapshot = body.get("expected_snapshot_id")
        if expected_snapshot is not None and expected_snapshot != record.snapshot_id:
            raise ApiError(
                ErrorCode.CONFLICT,
                "the finding changed; refresh it before recording your review",
            )
        try:
            action = ReviewAction(str(body.get("action", "")).strip().lower())
        except ValueError as exc:
            raise ApiError(
                ErrorCode.INVALID_INPUT, "action must be one of acknowledge, resolve, dismiss"
            ) from exc
        reason = str(body.get("reason", "")).strip()
        if not reason:
            raise ApiError(ErrorCode.INVALID_INPUT, "reason is required")
        new_state = {
            ReviewAction.ACKNOWLEDGE: ReviewState.ACKNOWLEDGED,
            ReviewAction.RESOLVE: ReviewState.RESOLVED,
            ReviewAction.DISMISS: ReviewState.DISMISSED,
        }[action]
        event = ReviewEvent(
            tenant_id=store.tenant_id,
            region=office,  # type: ignore[arg-type]
            event_id=new_id("rev"),
            finding_id=finding_id,
            snapshot_id=record.snapshot_id,
            actor=principal.principal_id,
            action=action,
            reason=reason,
            prior_state=record.review_state,
            new_state=new_state,
            referenced_revision_ids=list(body.get("referenced_revision_ids", [])),
            created_at=utc_now(),
        )
        payload_bytes = canonical_json_bytes(event)
        with store.db.transaction() as connection:
            current = store.get_finding(finding_id, connection=connection)
            if (
                current is None
                or current.snapshot_id != record.snapshot_id
                or current.review_state != record.review_state
            ):
                raise ApiError(
                    ErrorCode.CONFLICT,
                    "the finding changed; refresh it before recording your review",
                )
            store.append_review_event(
                connection,
                event,
                signature=runtime.signer.sign(payload_bytes),
                key_id=runtime.signer.key_id,
            )
        return {
            "event_id": event.event_id,
            "finding_id": finding_id,
            "action": action.value,
            "prior_state": record.review_state.value,
            "new_state": new_state.value,
            "actor": principal.principal_id,
        }

    # ------------------------------------------------------------------ queries
    @app.post("/v1/queries", status_code=201)
    async def query(request: Request, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.QUERY_LOCAL)
        body = await request.json()
        try:
            query_request = QueryRequest.model_validate(body)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(ErrorCode.INVALID_INPUT, f"query is not valid: {exc}")
        if query_request.target.subject is Subject.GENERAL_POLICY:
            from starlette.concurrency import run_in_threadpool
            from ..queries.general import GeneralQuestionEngine

            engine = GeneralQuestionEngine(store=store, signer=runtime.signer, settings=runtime.settings)
            record = await run_in_threadpool(engine.answer, query_request,
                allowed_restricted=principal.has(Permission.READ_RESTRICTED))
        else:
            engine = QueryEngine(store=store, signer=runtime.signer, extra_modes={"phrasing": Mode.REPLAY.value})
            record = engine.answer(query_request, allowed_restricted=principal.has(Permission.READ_RESTRICTED))
        graph = lineage_for_node(
            store,
            f"answer:{record.payload.answer_id}",
            allowed_restricted=principal.has(Permission.READ_RESTRICTED),
        )
        return {
            "answer": record.payload.model_dump(mode="json"),
            "answer_hash": record.payload_hash,
            "answer_signature": record.signature,
            "answer_key_id": record.key_id,
            "lineage": graph.model_dump(mode="json"),
        }

    @app.get("/v1/answers")
    def recent_answers(limit: int = Query(50, ge=1, le=100), principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        answers = []
        with closing(store.iter_answers()) as records:
            for record in records:
                if not _answer_readable(principal, record):
                    continue
                payload = record.payload
                answers.append({
                    "answer_id": payload.answer_id, "question": payload.question,
                    "status": payload.status.value,
                    "created_at": canonical_datetime(payload.created_at),
                })
                if len(answers) > limit:
                    break
        return {"answers": answers[:limit], "has_more": len(answers) > limit}

    @app.get("/v1/answers/{answer_id}")
    def get_answer(answer_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        record = store.get_answer(answer_id)
        if record is None or not _answer_readable(principal, record):
            raise ApiError(ErrorCode.NOT_FOUND, "no such answer")
        return {
            "answer": record.payload.model_dump(mode="json"),
            "answer_hash": record.payload_hash,
            "answer_signature": record.signature,
            "answer_key_id": record.key_id,
        }

    @app.get("/v1/answers/{answer_id}/lineage")
    def answer_lineage(answer_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        record = store.get_answer(answer_id)
        if record is None or not _answer_readable(principal, record):
            raise ApiError(ErrorCode.NOT_FOUND, "no such answer")
        graph = lineage_for_node(
            store,
            f"answer:{answer_id}",
            allowed_restricted=principal.has(Permission.READ_RESTRICTED),
        )
        return {"lineage": graph.model_dump(mode="json")}

    @app.get("/v1/answers/{answer_id}/bundle")
    def answer_bundle(answer_id: str, principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        record = store.get_answer(answer_id)
        if record is None or not _answer_readable(principal, record):
            raise ApiError(ErrorCode.NOT_FOUND, "no such answer")
        bundle = build_bundle(store, record)
        return {"bundle": bundle.model_dump(mode="json")}

    # ---------------------------------------------------------- verifications
    @app.post("/v1/verifications/source")
    async def verify_source(
        source_id: str = Form(...),
        file: UploadFile = File(...),
        principal=Depends(authenticate),
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        source = store.get_source(source_id)
        if not _source_readable(principal, source):
            raise ApiError(ErrorCode.NOT_FOUND, "no such source")
        raw = await file.read()
        report = verify_source_copy(store, source_id, raw)
        return {"report": report.model_dump(mode="json")}

    @app.post("/v1/verifications/bundle")
    async def verify_bundle_endpoint(
        request: Request, principal=Depends(authenticate)
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        body = await request.json()
        if isinstance(body, dict) and "bundle" in body:
            body = body["bundle"]
        try:
            bundle = EvidenceBundle.model_validate(body)
        except Exception as exc:  # noqa: BLE001 - malformed bundles are structured failures
            raise ApiError(
                ErrorCode.INVALID_INPUT,
                f"bundle does not match the EvidenceBundle contract: {exc}",
            )
        if bundle.tenant_id != store.tenant_id:
            return {
                "report": {
                    "target_type": "bundle",
                    "target_id": bundle.bundle_id,
                    "checks": [
                        {
                            "check": "tenant_match",
                            "status": "failed",
                            "reason": "bundle belongs to a different tenant",
                            "detail": {},
                        }
                    ],
                },
                "verified": False,
            }
        report = verify_bundle(bundle, registry=runtime.trusted_keys, tenant_id=store.tenant_id)
        return {"report": report.model_dump(mode="json"), "verified": not report.any_failed()}

    # -------------------------------------------------------------- federation
    @app.post("/v1/comparisons")
    async def comparison(request: Request, principal=Depends(authenticate)) -> dict[str, Any]:
        """Cross-office comparator used by the gateway after an approved import.

        Runs the local deterministic engine (own policy plus imported remote claims)
        and returns the structured result with passage quotes removed from transport.
        """

        _require_office_scope(principal, Permission.FEDERATION_SERVE)
        body = await request.json()
        try:
            query_request = QueryRequest.model_validate(body)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(ErrorCode.INVALID_INPUT, f"query is not valid: {exc}")
        engine = QueryEngine(
            store=store,
            signer=runtime.signer,
            extra_modes={"phrasing": Mode.REPLAY.value},
        )
        try:
            record = engine.answer(
                query_request, region=office, allowed_restricted=False
            )
        except StaleRemoteSnapshot as exc:
            # A stale, unknown or not-yet-received snapshot is rejected instead of
            # silently falling back to older or newer imported history.
            raise ApiError(ErrorCode.CONFLICT, str(exc), detail={"reason_code": "stale_remote_snapshot"}) from exc
        except UnknownRemoteSnapshot as exc:
            raise ApiError(
                ErrorCode.INVALID_INPUT, str(exc), detail={"reason_code": "unknown_remote_snapshot"}
            ) from exc

        # A comparison is an outbound derivative of local policy, not an exception
        # to the source's export permission. Do not infer a narrow/predicate-only
        # permission from the general office_export=false contract.
        local_views = store.claim_views(subject=query_request.target.subject.value)
        local_snapshot = select_snapshot(
            local_views,
            valid_at=query_request.valid_at,
            known_at=record.payload.known_at,
            subject=query_request.target.subject,
        )
        non_exportable = False
        for view in local_snapshot:
            if not scope_matches_target(view.revision.scope, query_request.target):
                continue
            source = store.get_source(view.revision.source_id)
            if source is None:
                non_exportable = True
                break
            if not source.restricted and not source.office_export:
                non_exportable = True
                break
        if non_exportable:
            _record_office_egress(
                runtime,
                request_id=record.payload.answer_id,
                destination=principal.principal_id,
                outcome=EgressOutcome.BLOCKED,
                error_code="egress_denied_source_permission",
                payload_bytes=0,
                payload_type="comparison_projection",
            )
            raise ApiError(
                ErrorCode.EGRESS_DENIED,
                "comparison includes local policy that is not permitted for office export",
                detail={"reason_code": "egress_denied_source_permission"},
            )

        # First form the exact authorized projection, then hash and sign those exact
        # bytes. The full answer remains in the local signed answers table; the
        # projection metadata establishes which local signed record it derives from.
        projection = record.payload.model_copy(deep=True)
        projection.citations = [
            citation.model_copy(update={"quote": None})
            for citation in projection.citations
        ]
        projection.model_metadata = {
            **projection.model_metadata,
            "export_projection": "comparison-v1",
            "local_answer_hash": record.payload_hash,
            "local_answer_signature": record.signature,
        }
        projection_bytes = canonical_json_bytes(projection)
        projection_hash = sha256_hex(projection_bytes)
        projection_signature = runtime.signer.sign(projection_bytes)
        _record_office_egress(
            runtime,
            request_id=record.payload.answer_id,
            destination=principal.principal_id,
            outcome=EgressOutcome.DELIVERED,
            error_code=None,
            payload_bytes=len(projection_bytes),
            payload_sha256=projection_hash,
            raw_source_bytes=0,
            payload_type="comparison_projection",
        )
        return {
            "answer": projection.model_dump(mode="json"),
            "answer_hash": projection_hash,
            "answer_signature": projection_signature,
            "answer_key_id": runtime.signer.key_id,
            "local_answer_id": record.payload.answer_id,
            "local_answer_hash": record.payload_hash,
            "transport_redaction": {
                "quotes_removed": len(record.payload.citations),
                "note": (
                    "the exported quote-free projection has its own signature; its signed "
                    "metadata links it to the separately stored full local answer"
                ),
            },
        }

    @app.post("/v1/federation/claims")
    async def federation_claims(
        request: Request, principal=Depends(authenticate)
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.FEDERATION_SERVE)
        body = await request.json()
        try:
            subquery = FederationSubquery.model_validate(body)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(ErrorCode.INVALID_INPUT, f"subquery is not valid: {exc}")
        if subquery.target_fingerprint is not None and subquery.target_fingerprint != target_fingerprint(
            subquery.target
        ):
            raise ApiError(
                ErrorCode.INVALID_INPUT,
                "subquery target_fingerprint does not match the canonical target",
                detail={"reason_code": "target_fingerprint_mismatch"},
            )
        try:
            export = build_export(store, query=subquery, signer=runtime.signer)
        except ExportDenied as exc:
            _record_office_egress(
                runtime,
                request_id=subquery.request_id,
                destination=principal.principal_id,
                outcome=EgressOutcome.BLOCKED,
                error_code=exc.reason_code,
                payload_bytes=0,
            )
            raise ApiError(ErrorCode.EGRESS_DENIED, exc.detail, detail={"reason_code": exc.reason_code})

        payload_bytes = len(canonical_json_bytes(export.payload))
        withheld = export.payload.withheld_restricted
        outcome = EgressOutcome.DELIVERED if export.payload.claims else (
            EgressOutcome.BLOCKED if withheld else EgressOutcome.DELIVERED
        )
        _record_office_egress(
            runtime,
            request_id=subquery.request_id,
            destination=principal.principal_id,
            outcome=outcome,
            error_code="egress_denied_restricted_source"
            if outcome is EgressOutcome.BLOCKED
            else None,
            payload_bytes=payload_bytes,
            payload_sha256=export.payload_hash,
        )
        return {
            "export": export.model_dump(mode="json"),
            "summary": {
                "claims": len(export.payload.claims),
                "withheld_restricted": withheld,
                "reason_codes": export.payload.reason_codes,
                "not_checked": export.payload.not_checked,
                "payload_bytes": payload_bytes,
            },
        }

    @app.post("/v1/federation/imports")
    async def federation_imports(
        request: Request, principal=Depends(authenticate)
    ) -> dict[str, Any]:
        _require_office_scope(principal, Permission.FEDERATION_SERVE)
        body = await request.json()
        candidate = body.get("export") if isinstance(body, dict) else None
        expect = (
            body.get("expect")
            if isinstance(body, dict) and isinstance(body.get("expect"), dict)
            else {}
        )
        try:
            export = FederationExport.model_validate(candidate)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(ErrorCode.INVALID_INPUT, f"export is not valid: {exc}")
        expected_origin = None
        if isinstance(body, dict):
            expected_origin = body.get("origin_region") or expect.get("origin_region")
        if expected_origin is None:
            expected_origin = export.payload.origin_region.value
        try:
            expected_valid_at = _parse_iso(expect.get("valid_at"))
            expected_known_at = _parse_iso(expect.get("known_at"))
        except (TypeError, ValueError) as exc:
            raise ApiError(
                ErrorCode.INVALID_INPUT,
                "import expectation timestamps must be valid ISO-8601 values",
            ) from exc
        payload, errors = verify_export(
            export,
            registry=runtime.trusted_keys,
            tenant_id=store.tenant_id,
            expected_origin=expected_origin,
            expected_request_id=expect.get("request_id"),
            expected_target_fingerprint=expect.get("target_fingerprint"),
            expected_valid_at=expected_valid_at,
            expected_known_at=expected_known_at,
        )
        if payload is None:
            return {
                "accepted": False,
                "imported": 0,
                "errors": errors,
                "note": "signature/binding/tenant checks failed; nothing was stored",
            }
        moment = utc_now()
        try:
            imported = import_export(
                store, export=export, payload=payload, received_at=moment
            )
        except RemoteClaimConflict as exc:
            raise ApiError(
                ErrorCode.CONFLICT,
                f"remote claim conflict: {exc}",
            ) from exc
        snapshot_id = snapshot_id_for(payload, export.payload_hash)
        return {
            "accepted": True,
            "imported": imported,
            "errors": [],
            "snapshot_id": snapshot_id,
            "snapshot_ids": [snapshot_id],
            "received_at": canonical_datetime(moment),
            "origin_region": payload.origin_region.value,
            "request_id": payload.request_id,
        }

    @app.get("/v1/federation/remote-claims")
    def remote_claims(principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.READ_LOCAL)
        with store.db.reader() as connection:
            rows = connection.execute(
                "SELECT origin_region, request_id, claim_id, revision_id, subject, "
                "claim_payload_hash, manifest_root, not_checked_json, export_key_id, received_at "
                "FROM remote_claims WHERE tenant_id = ? AND region = ? ORDER BY received_at",
                (store.tenant_id, store.region),
            ).fetchall()
        return {
            "remote_claims": [
                {
                    "origin_region": row["origin_region"],
                    "request_id": row["request_id"],
                    "claim_id": row["claim_id"],
                    "revision_id": row["revision_id"],
                    "subject": row["subject"],
                    "claim_payload_hash": row["claim_payload_hash"],
                    "manifest_root": row["manifest_root"],
                    "not_checked": json.loads(row["not_checked_json"]),
                    "export_key_id": row["export_key_id"],
                    "received_at": row["received_at"],
                }
                for row in rows
            ]
        }

    # ------------------------------------------------------------------- audit
    @app.get("/v1/audit/egress")
    def audit_egress(principal=Depends(authenticate)) -> dict[str, Any]:
        _require_office_scope(principal, Permission.AUDIT_READ)
        summary = store.summarize_egress()
        events = store.egress_events(limit=100)
        return {
            "summary": summary.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
            "model_calls": store.model_call_stats(),
        }

    return app


def _record_office_egress(
    runtime: OfficeRuntime,
    *,
    request_id: str,
    destination: str,
    outcome: EgressOutcome,
    payload_bytes: int,
    error_code: str | None,
    payload_sha256: str = "",
    raw_source_bytes: int = 0,
    payload_type: str = "federation_export",
) -> None:
    """Audit one office-to-office serialization; raw source text never crosses."""

    event = EgressEvent(
        event_id=new_id("egress"),
        tenant_id=runtime.store.tenant_id,
        region=runtime.settings.region,  # type: ignore[arg-type]
        channel=EgressChannel.OFFICE_TO_OFFICE,
        destination=destination[:200],
        request_id=request_id,
        payload_type=payload_type,
        payload_bytes=payload_bytes,
        payload_sha256=payload_sha256,
        raw_source_bytes=raw_source_bytes,
        outcome=outcome,
        error_code=error_code,
        created_at=utc_now(),
    )
    with runtime.store.db.transaction() as connection:
        runtime.store.record_egress(connection, event)


__all__ = ["OfficeRuntime", "build_runtime", "create_app"]


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
