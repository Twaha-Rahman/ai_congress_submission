"""Durable stage progress for one worker attempt, independent of model output."""

import copy
import time

from ..contracts.common import canonical_datetime, utc_now


class JobProgress:
    def __init__(self, store, job):
        self.store = store
        self.job_id = job.job_id
        previous = job.progress
        history = list(previous.get("previous_attempts", []))
        if previous.get("stages"):
            history.append({k: copy.deepcopy(v) for k, v in previous.items()
                            if k != "previous_attempts"})
        self.data = {"attempt": job.attempts, "current_stage": None,
                     "stages": [], "previous_attempts": history[-2:]}
        self.started = None

    def _close(self, status):
        if self.started is not None:
            current = self.data["stages"][-1]
            current.update(status=status, finished_at=canonical_datetime(utc_now()),
                           elapsed_ms=max(0, int((time.monotonic() - self.started) * 1000)))
            self.started = None

    def __call__(self, stage, **details):
        if self.data["current_stage"] != stage:
            self._close("completed")
            self.data["current_stage"] = stage
            self.started = time.monotonic()
            self.data["stages"].append({"key": stage, "status": "running",
                "started_at": canonical_datetime(utc_now()), "finished_at": None,
                "elapsed_ms": None})
        self.data["stages"][-1].update(details)
        self.store.update_job(self.job_id, progress=self.data)

    def finish(self, status):
        self._close("completed" if status in {"succeeded", "needs_review"} else "failed")
        self.data["current_stage"] = None
        self.store.update_job(self.job_id, progress=self.data)
