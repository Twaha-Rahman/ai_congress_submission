"""Durable job restart recovery and bounded retry behavior."""

from __future__ import annotations

from meridian.contracts.common import JobStatus, Mode
from meridian.storage.db import Database
from meridian.storage.store import OfficeStore

from conftest import OfficeHarness


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
