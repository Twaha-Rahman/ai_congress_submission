"""Durable job restart recovery and bounded retry behavior."""

from __future__ import annotations

import pytest

from meridian.contracts.common import ErrorCode, JobStatus, Mode
from meridian.ingestion import worker as worker_module
from meridian.ingestion.pipeline import IngestionOutcome
from meridian.ingestion.worker import OfficeWorker
from meridian.storage.db import Database
from meridian.storage.store import OfficeStore

from conftest import DEMO_POLICY_V2, FIXTURES, OfficeHarness, read_manifest


def _restart(harness: OfficeHarness) -> OfficeStore:
    """Open the same office database the way a restarted process would."""

    return OfficeStore(
        Database(harness.settings.db_path),
        tenant_id=harness.store.tenant_id,
        region=harness.store.region,
    )


def test_restart_requeues_a_running_job_and_keeps_the_attempt(
    dhaka: OfficeHarness,
) -> None:
    job = dhaka.store.create_job(
        kind="pdf", mode=Mode.REPLAY, request={"probe": "restart"}, max_attempts=3
    )
    claimed = dhaka.store.claim_next_job()
    assert claimed is not None and claimed.job_id == job.job_id
    assert claimed.status == JobStatus.RUNNING.value
    assert claimed.attempts == 1

    restarted = _restart(dhaka)
    assert restarted.requeue_unfinished_jobs() == 1

    recovered = restarted.get_job(job.job_id)
    assert recovered is not None
    assert recovered.status == JobStatus.QUEUED.value
    assert recovered.attempts == 1
    assert recovered.finished_at is None


def test_restart_fails_an_interrupted_job_that_exhausted_attempts(
    dhaka: OfficeHarness,
) -> None:
    job = dhaka.store.create_job(
        kind="pdf", mode=Mode.REPLAY, request={"probe": "exhausted"}, max_attempts=1
    )
    claimed = dhaka.store.claim_next_job()
    assert claimed is not None and claimed.job_id == job.job_id

    restarted = _restart(dhaka)
    assert restarted.requeue_unfinished_jobs() == 0

    recovered = restarted.get_job(job.job_id)
    assert recovered is not None
    assert recovered.status == JobStatus.FAILED.value
    assert recovered.error_code == "interrupted_attempts_exhausted"
    assert recovered.finished_at is not None


@pytest.mark.parametrize("recover", [True, False])
def test_model_retry_keeps_pdf_until_terminal_result(dhaka: OfficeHarness, monkeypatch, recover: bool) -> None:
    staged = dhaka.settings.source_dir / "_staging" / "retry.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes((FIXTURES / DEMO_POLICY_V2[0]).read_bytes())
    job = dhaka.store.create_job(kind="pdf", mode=Mode.REPLAY, max_attempts=2, request={
        "file_ref": str(staged),
        "manifest": read_manifest(DEMO_POLICY_V2[1]).model_dump(mode="json"),
    })
    original = worker_module.ingest_prepared
    calls = 0

    def flaky_model(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1 or not recover:
            return IngestionOutcome(error_code=ErrorCode.PROVIDER_ERROR.value,
                                    error_detail="Model provider unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(worker_module, "ingest_prepared", flaky_model)
    worker = OfficeWorker(store=dhaka.store, settings=dhaka.settings, signer=dhaka.signer)
    assert worker.process_once()
    assert dhaka.store.get_job(job.job_id).status == JobStatus.QUEUED.value
    assert staged.exists()
    assert worker.process_once()
    final = dhaka.store.get_job(job.job_id)
    assert calls == 2
    assert final.attempts == 2
    assert final.status == (JobStatus.SUCCEEDED.value if recover else JobStatus.FAILED.value)
    if not recover:
        assert final.error_code == ErrorCode.PROVIDER_ERROR.value
        assert final.review_reason == "Model provider unavailable"
    assert not staged.exists()


def test_internal_failure_retry_has_no_finished_time_or_stale_error(dhaka: OfficeHarness, monkeypatch) -> None:
    staged = dhaka.settings.source_dir / "_staging" / "retry.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes((FIXTURES / DEMO_POLICY_V2[0]).read_bytes())
    job = dhaka.store.create_job(kind="pdf", mode=Mode.REPLAY, max_attempts=2, request={
        "file_ref": str(staged), "manifest": read_manifest(DEMO_POLICY_V2[1]).model_dump(mode="json"),
    })
    original = worker_module.ingest_prepared
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Controlled persistence failure")
        running = dhaka.store.get_job(job.job_id)
        assert running.status == "running"
        assert running.finished_at is running.error_code is running.review_reason is None
        return original(*args, **kwargs)

    monkeypatch.setattr(worker_module, "ingest_prepared", fail_once)
    worker = OfficeWorker(store=dhaka.store, settings=dhaka.settings, signer=dhaka.signer)
    assert worker.process_once()
    queued = dhaka.store.get_job(job.job_id)
    assert queued.status == "queued" and queued.finished_at is None
    assert queued.error_code == "internal_error" and staged.exists()
    assert worker.process_once()
    final = dhaka.store.get_job(job.job_id)
    assert final.status == "succeeded" and final.finished_at is not None
    assert final.error_code is final.review_reason is None


def test_retry_recovery_clears_legacy_finished_metadata(dhaka: OfficeHarness) -> None:
    job = dhaka.store.create_job(kind="pdf", mode=Mode.REPLAY, request={})
    assert dhaka.store.claim_next_job()
    # Simulate an old worker that incorrectly marked a retrying attempt finished.
    with dhaka.store.db.transaction() as conn:
        conn.execute("UPDATE jobs SET finished_at=updated_at, error_code='internal_error', review_reason='old failure' WHERE job_id=?", (job.job_id,))
    assert dhaka.store.requeue_unfinished_jobs() == 1
    assert dhaka.store.get_job(job.job_id).finished_at is None
    running = dhaka.store.claim_next_job()
    assert running.attempts == 2
    assert running.finished_at is running.error_code is running.review_reason is None
