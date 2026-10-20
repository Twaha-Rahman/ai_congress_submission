"""Durable ingestion jobs and the single office worker.

Jobs are persisted before the API acknowledges the upload.  The worker processes one
job at a time per office process; unfinished ``running`` jobs are safely requeued on
startup, and retryable failures back off within the attempt budget.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import OfficeSettings
from ..contracts.common import (
    EgressChannel,
    EgressOutcome,
    ErrorCode,
    JobStatus,
    Mode,
    Region,
    utc_now,
)
from ..contracts.federation import EgressEvent, ModelCallMetadata
from ..contracts.manifest import SourceManifest
from ..extraction.service import ModelStageService
from ..integrity.signing import Signer
from ..storage.store import JobRow, OfficeStore, new_id
from .pdf import UnsupportedDocument
from .pipeline import (
    IngestionOutcome,
    ManifestSourceMismatch,
    VersionPayloadMismatch,
    ingest_prepared,
    prepare_pdf_source,
    prepare_slack_source,
)

RETRYABLE_CODES = {
    ErrorCode.PROVIDER_TIMEOUT.value,
    ErrorCode.PROVIDER_ERROR.value,
    ErrorCode.INTERNAL_ERROR.value,
}

#: Provider-stage outcome labels mapped onto the audited transport outcome enum.
_PROVIDER_OUTCOMES = {
    "ok": EgressOutcome.DELIVERED,
    "failed": EgressOutcome.FAILED,
    "timeout": EgressOutcome.TIMEOUT,
    "cache_miss": EgressOutcome.FAILED,
    "replay_missing": EgressOutcome.FAILED,
    "prerequisite_missing": EgressOutcome.FAILED,
    "blocked": EgressOutcome.BLOCKED,
}


def _egress_outcome(value: object) -> EgressOutcome:
    if isinstance(value, EgressOutcome):
        return value
    return _PROVIDER_OUTCOMES.get(str(value), EgressOutcome.FAILED)


class EgressRecorder:
    """Buffers audited transport events; flushed after the publication commit."""

    def __init__(self, *, region: str, tenant_id: str) -> None:
        self.region = region
        self.tenant_id = tenant_id
        self.events: list[dict[str, Any]] = []

    def sink(self, data: dict[str, Any]) -> None:
        self.events.append(dict(data))

    def flush(self, store: OfficeStore) -> int:
        if not self.events:
            return 0
        buffered = list(self.events)
        self.events.clear()
        with store.db.transaction() as connection:
            for item in buffered:
                event = EgressEvent(
                    event_id=new_id("egress"),
                    tenant_id=self.tenant_id,
                    region=Region(self.region),
                    channel=EgressChannel(item["channel"]),
                    destination=str(item["destination"])[:200],
                    request_id=str(item["request_id"]),
                    payload_type=item["payload_type"],
                    payload_bytes=int(item["payload_bytes"]),
                    payload_sha256=item.get("payload_sha256", ""),
                    raw_source_bytes=int(item.get("raw_source_bytes", 0)),
                    outcome=_egress_outcome(item.get("outcome")),
                    error_code=item.get("error_code"),
                    model_metadata=item.get("model_metadata"),
                    created_at=utc_now(),
                )
                store.record_egress(connection, event)
        return len(buffered)


class OfficeWorker:
    """Processes persisted ingestion jobs for one office."""

    def __init__(
        self,
        *,
        store: OfficeStore,
        settings: OfficeSettings,
        signer: Signer,
        transport=None,
        write_cache: bool = False,
        poll_interval: float = 0.2,
    ) -> None:
        self.store = store
        self.settings = settings
        self.signer = signer
        self.transport = transport
        self.write_cache = write_cache
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ----------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.store.requeue_unfinished_jobs()
        self._thread = threading.Thread(target=self._run, name="meridian-office-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.process_once()
            except Exception:  # noqa: BLE001 - the worker must survive one bad job
                logging.getLogger(__name__).exception(
                    "office worker iteration failed; continuing after a short backoff"
                )
                processed = False
                self._stop.wait(1.0)
                continue
            if not processed:
                self._stop.wait(self.poll_interval)

    # ----------------------------------------------------------------- processing
    def process_once(self) -> bool:
        job = self.store.claim_next_job()
        if job is None:
            return False
        self.process_job(job)
        return True

    def process_job(self, job: JobRow) -> IngestionOutcome | None:
        recorder = EgressRecorder(region=self.settings.region, tenant_id=self.settings.tenant_id)
        service = ModelStageService(
            self.settings,
            transport=self.transport,
            write_cache=self.write_cache,
            egress_sink=recorder.sink,
        )
        if job.kind == "policy_comparison":
            from ..rules.general import recompare_policy_source

            try:
                outcome = recompare_policy_source(self.store, job.request["source_id"],
                    service=service, signer=self.signer, mode=Mode(job.mode), request_id=job.job_id)
            except Exception as exc:  # keep the durable worker alive
                outcome = IngestionOutcome(error_code=ErrorCode.INTERNAL_ERROR.value,
                                           error_detail=f"{type(exc).__name__}: {exc}"[:400])
            recorder.flush(self.store)
            self._finalise(job, outcome)
            return outcome
        try:
            prepared, request_id = self._prepare(job)
        except (UnsupportedDocument, ManifestSourceMismatch, VersionPayloadMismatch) as exc:
            code = getattr(exc, "error_code", None)
            error_code = code.value if hasattr(code, "value") else ErrorCode.UNSUPPORTED_CONTENT.value
            if isinstance(exc, VersionPayloadMismatch):
                error_code = ErrorCode.VERSION_PAYLOAD_MISMATCH.value
            self.store.update_job(
                job.job_id,
                status=JobStatus.FAILED,
                error_code=error_code,
                review_reason=str(exc)[:400],
                finished=True,
            )
            recorder.flush(self.store)
            return None
        except FileNotFoundError:
            self.store.update_job(
                job.job_id,
                status=JobStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR.value,
                review_reason="staged upload file is missing",
                finished=True,
            )
            return None

        outcome: IngestionOutcome | None = None
        try:
            outcome = ingest_prepared(
                self.store,
                prepared,
                mode=Mode(job.mode),
                service=service,
                signer=self.signer,
                now=utc_now(),
                request_id=request_id,
                source_dir=self.settings.source_dir,
            )
        except Exception as exc:  # noqa: BLE001 - job must not crash the worker
            self.store.update_job(
                job.job_id,
                status=self._failure_status(job, ErrorCode.INTERNAL_ERROR.value),
                error_code=ErrorCode.INTERNAL_ERROR.value,
                review_reason=f"{type(exc).__name__}: {exc}"[:400],
                finished=True,
            )
            recorder.flush(self.store)
            return None

        recorder.flush(self.store)
        self._finalise(job, outcome)
        self._cleanup_staging(job)
        return outcome

    def _prepare(self, job: JobRow) -> tuple[Any, str]:
        request = job.request
        manifest = SourceManifest.model_validate(request["manifest"])
        request_id = request.get("request_id") or new_id("req")
        kind = job.kind
        file_ref = Path(request["file_ref"])
        raw_bytes = file_ref.read_bytes()
        if kind == "pdf":
            return prepare_pdf_source(manifest, raw_bytes), request_id
        return prepare_slack_source(manifest, raw_bytes), request_id

    def _failure_status(self, job: JobRow, error_code: str) -> JobStatus:
        if error_code in RETRYABLE_CODES and job.attempts < job.max_attempts:
            return JobStatus.QUEUED
        return JobStatus.FAILED

    def _finalise(self, job: JobRow, outcome: IngestionOutcome) -> None:
        # Failed extraction never commits its staged source. Keep authorization
        # tied to the job's trusted manifest rather than an unresolvable source ID.
        persisted_source_id = outcome.source_id if outcome.source_id and self.store.get_source(outcome.source_id) else None
        if outcome.error_code is not None:
            status = self._failure_status(job, outcome.error_code)
            self.store.update_job(
                job.job_id,
                status=status,
                error_code=outcome.error_code,
                review_reason=outcome.error_detail,
                source_id=persisted_source_id,
                stage_modes=outcome.stage_modes,
                finished=status is JobStatus.FAILED,
            )
            return
        accepted = [
            revision_id
            for revision_id in outcome.claim_revision_ids
            if self._is_accepted(revision_id)
        ]
        if outcome.stage_modes.get("policy_comparison") and (outcome.review_reasons or outcome.rejection_reasons):
            status = JobStatus.NEEDS_REVIEW
        elif accepted:
            status = JobStatus.SUCCEEDED
        elif outcome.review_reasons or outcome.rejection_reasons:
            status = JobStatus.NEEDS_REVIEW
        else:
            status = JobStatus.SUCCEEDED if outcome.duplicate else JobStatus.NEEDS_REVIEW
        self.store.update_job(
            job.job_id,
            status=status,
            source_id=persisted_source_id,
            stage_modes=outcome.stage_modes,
            review_reason=(
                "; ".join(
                    sorted(set(outcome.review_reasons))
                    + [f"rejected:{code}" for code in sorted(set(outcome.rejection_reasons))]
                )[:400]
                or None
            ),
            finished=True,
        )

    def _is_accepted(self, revision_id: str) -> bool:
        record = self.store.get_claim(revision_id)
        return record is not None and record.payload.status.value == "accepted"

    def _cleanup_staging(self, job: JobRow) -> None:
        ref = job.request.get("file_ref")
        if not ref:
            return
        path = Path(ref)
        try:
            if path.exists() and "_staging" in str(path):
                path.unlink()
        except OSError:  # pragma: no cover - best effort cleanup
            pass
