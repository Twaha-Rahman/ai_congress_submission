"""Offline end-to-end evaluation over the labeled corpus.

For every scenario the runner starts an isolated three-service stack (Dhaka on
:8091, Frankfurt on :8092, gateway on :8090, fresh databases under
``runtime/evaluation/<scenario>/``, replay mode) and drives the *normal HTTP APIs*:
ingestion, queries, verification, federation and egress audits.  Finding quality is
then computed against the corpus labels: persisted findings from ``/v1/findings`` and
candidate classifications recomputed with the real comparison engine on the stored
claim views (a missed extraction is therefore counted as an end-to-end miss).

Held-out labels are never used to tune the system; the corpus records which policy
families were development and which were held out.

    .venv/bin/python scripts/evaluate.py [--keep-stack] [--only SCENARIO_ID]

Writes ``evidence/evaluation_results.json`` and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import load_dotenv  # noqa: E402
from meridian.rules.publish import compare_pair  # noqa: E402
from meridian.storage.db import Database  # noqa: E402
from meridian.storage.store import OfficeStore  # noqa: E402
from scripts.demo_client import (  # noqa: E402
    Client,
    DemoError,
    ingest_pdf,
    ingest_slack,
    loan_target,
    query_gateway,
    retention_target,
    save_json,
    step,
    token,
    wait_job,
)

EVAL_FIXTURES = ROOT / "fixtures" / "evaluation"
CORPUS_PATH = EVAL_FIXTURES / "corpus.json"
RUNTIME = ROOT / "runtime" / "evaluation"
RESULTS_PATH = ROOT / "evidence" / "evaluation_results.json"

PORTS = {"dhaka": 8091, "frankfurt": 8092, "gateway": 8090}
BASE_URLS = {name: f"http://127.0.0.1:{port}" for name, port in PORTS.items()}
TOKENS = {
    "dhaka": "DEMO_TOKEN_DHAKA_UPLOADER",
    "frankfurt": "DEMO_TOKEN_FRANKFURT_UPLOADER",
    "gateway": "DEMO_TOKEN_GATEWAY_SERVICE",
}
REVIEWER_TOKENS = {
    "dhaka": "DEMO_TOKEN_DHAKA_REVIEWER",
    "frankfurt": "DEMO_TOKEN_FRANKFURT_REVIEWER",
}
SERVICE_TOKENS = {
    "dhaka": "DEMO_TOKEN_DHAKA_SERVICE",
    "frankfurt": "DEMO_TOKEN_FRANKFURT_SERVICE",
}
TENANT = "meridian_demo"


# --------------------------------------------------------------------- services


@dataclass
class RunningService:
    name: str
    process: subprocess.Popen
    log_path: Path

    def stop(self, timeout: float = 6.0) -> None:
        if self.process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        except OSError:
            self.process.terminate()
        deadline = time.time() + timeout
        while time.time() < deadline and self.process.poll() is None:
            time.sleep(0.05)
        if self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except OSError:
                self.process.kill()


class EvalStack:
    """Three isolated services for one scenario, started/destroyed per scenario."""

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.dir = RUNTIME / scenario_id
        self.running: dict[str, RunningService] = {}
        self.startup_seconds: float | None = None

    # ------------------------------------------------------------------ layout
    def office_dir(self, region: str) -> Path:
        return self.dir / region.lower()

    def _spec(self, name: str) -> dict[str, Any]:
        if name == "gateway":
            return {
                "module": "meridian.gateway_api.main",
                "env": {
                    "TENANT_ID": TENANT,
                    "PORT": str(PORTS[name]),
                    "DHAKA_BASE_URL": BASE_URLS["dhaka"],
                    "FRANKFURT_BASE_URL": BASE_URLS["frankfurt"],
                    "GATEWAY_RUNTIME_DIR": str(self.dir / "gateway"),
                    "FIXTURES_DIR": str(EVAL_FIXTURES),
                },
            }
        region = name.upper()
        prefix = region
        office_dir = self.office_dir(name)
        return {
            "module": "meridian.office_api.main",
            "env": {
                "TENANT_ID": TENANT,
                "REGION": region,
                "PORT": str(PORTS[name]),
                "DB_PATH": str(office_dir / "meridian.db"),
                "SOURCE_DIR": str(office_dir / "sources"),
                # demo signing keys stay pinned in runtime/trusted_keys.json so
                # federation verification is exercised against the real registry
                "KEY_DIR": str(ROOT / "runtime" / "keys" / name),
                "FIXTURES_DIR": str(EVAL_FIXTURES),
                "DEFAULT_MODE": "replay",
                # The prefixed names win over the generic ones in configuration
                # resolution.  A developer ``.env`` commonly pins these to the demo
                # runtime, which must never leak into an isolated evaluation stack
                # (two workers polling one database would race for the same jobs).
                f"{prefix}_DB_PATH": str(office_dir / "meridian.db"),
                f"{prefix}_SOURCE_DIR": str(office_dir / "sources"),
                f"{prefix}_KEY_DIR": str(ROOT / "runtime" / "keys" / name),
                f"{prefix}_DEFAULT_MODE": "replay",
            },
        }

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        # A scenario run must be reproducible: stale databases or originals from a
        # previous attempt would make ingestion idempotent in the wrong way (same
        # versions, duplicated claims) and contaminate the measurement.
        shutil.rmtree(self.dir, ignore_errors=True)
        for name in ("dhaka", "frankfurt", "gateway"):
            spec = self._spec(name)
            env = os.environ.copy()
            env.update(spec["env"])
            env["PYTHONUNBUFFERED"] = "1"
            if name != "gateway":
                (self.office_dir(name) / "sources").mkdir(parents=True, exist_ok=True)
            (self.dir / "logs").mkdir(parents=True, exist_ok=True)
            log_path = self.dir / "logs" / f"{name}.log"
            started = time.perf_counter()
            with open(log_path, "ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", spec["module"]],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            self.running[name] = RunningService(name, process, log_path)
            expected_db = (
                Path(spec["env"][f"{name.upper()}_DB_PATH"]).resolve()
                if name != "gateway"
                else None
            )
            self._wait_health(name, process, started, expected_db=expected_db)

    def _wait_health(
        self,
        name: str,
        process: subprocess.Popen,
        started: float,
        *,
        expected_db: Path | None = None,
    ) -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            if process.poll() is not None:
                raise DemoError(
                    f"{name} exited during startup; log tail:\n{self._tail(name)}"
                )
            try:
                response = httpx.get(f"{BASE_URLS[name]}/health", timeout=1.0)
                if response.status_code == 200:
                    if expected_db is not None:
                        actual = Path(response.json().get("db_path", "")).resolve()
                        if actual != expected_db:
                            raise DemoError(
                                f"{name} is not using its isolated database: "
                                f"{actual} != {expected_db}; check .env for "
                                f"{name.upper()}_DB_PATH leaking into the evaluation stack"
                            )
                    if self.startup_seconds is None:
                        self.startup_seconds = time.perf_counter() - started
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise DemoError(f"{name} did not become healthy; log tail:\n{self._tail(name)}")

    def restart_one(self, name: str) -> None:
        service = self.running.pop(name, None)
        if service is not None:
            service.stop()
        spec = self._spec(name)
        env = os.environ.copy()
        env.update(spec["env"])
        env["PYTHONUNBUFFERED"] = "1"
        log_path = self.dir / "logs" / f"{name}.log"
        with open(log_path, "ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", spec["module"]],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.running[name] = RunningService(name, process, log_path)
        self._wait_health(name, process, time.perf_counter())

    def stop_one(self, name: str) -> None:
        service = self.running.pop(name, None)
        if service is not None:
            service.stop()

    def stop(self) -> None:
        for name in list(self.running):
            self.stop_one(name)

    def _tail(self, name: str, lines: int = 25) -> str:
        path = self.dir / "logs" / f"{name}.log"
        if not path.exists():
            return "(no log)"
        return "\n".join(path.read_text("utf-8", errors="replace").splitlines()[-lines:])

    def rss_kb(self) -> dict[str, int | None]:
        values: dict[str, int | None] = {}
        for name, service in self.running.items():
            try:
                status = Path(f"/proc/{service.process.pid}/status").read_text("utf-8")
                match = re.search(r"VmRSS:\s+(\d+) kB", status)
                values[name] = int(match.group(1)) if match else None
            except OSError:
                values[name] = None
        return values


# ------------------------------------------------------------------- utilities


def die(message: str) -> None:
    print(f"evaluate error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_target(spec: str) -> dict:
    parts = spec.split(":")
    if parts[0] == "record":
        return retention_target()
    target = loan_target(int(parts[1]))
    for extra in parts[2:]:
        key, _, value = extra.partition("=")
        target[key] = value
    return target


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


class CheckRecorder:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, bool(passed), detail))
        return bool(passed)

    def expect(self, name: str, condition: bool, detail: str = "") -> bool:
        if not condition:
            print(f"    FAIL  {name}  {detail}")
        return self.record(name, condition, detail)

    def summary(self) -> dict:
        passed = sum(1 for check in self.checks if check.passed)
        return {
            "total": len(self.checks),
            "passed": passed,
            "failed": len(self.checks) - passed,
            "checks": [check.as_dict() for check in self.checks],
        }


def office_store(stack: EvalStack, region: str) -> OfficeStore:
    db_path = stack.office_dir(region.lower()) / "meridian.db"
    return OfficeStore(Database(db_path), tenant_id=TENANT, region=region.upper())


def claims_by_clause(store: OfficeStore) -> dict[str, list]:
    mapping: dict[str, list] = defaultdict(list)
    for view in store.claim_views():
        mapping[view.revision.evidence.clause_id].append(view)
    return mapping


# --------------------------------------------------------------- ingest & read


def ingest_scenario(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder
) -> dict:
    clients = {name: Client(BASE_URLS[name]) for name in ("dhaka", "frankfurt", "gateway")}
    ingestions: list[dict] = []
    try:
        for entry in scenario["sources"]:
            region = entry["region"].lower()
            client = clients[region]
            token_env = TOKENS[region]
            started = time.perf_counter()
            if entry["kind"] == "pdf":
                job = ingest_pdf(
                    client,
                    token_env,
                    pdf_path=EVAL_FIXTURES / entry["file"],
                    manifest_path=EVAL_FIXTURES / entry["manifest"],
                    mode="replay",
                )
            else:
                job = ingest_slack(
                    client,
                    token_env,
                    event_path=EVAL_FIXTURES / entry["file"],
                    manifest_path=EVAL_FIXTURES / entry["manifest"],
                    mode="replay",
                )
            finished = wait_job(client, token_env, job["job_id"], timeout=120)
            elapsed_ms = (time.perf_counter() - started) * 1000
            record = {
                "source_identity": entry["source_identity"],
                "version_label": entry["version_label"],
                "region": entry["region"],
                "status": finished["status"],
                "error_code": finished["error_code"],
                "review_reason": finished["review_reason"],
                "stage_modes": finished["stage_modes"],
                "attempts": finished["attempts"],
                "elapsed_ms": round(elapsed_ms, 1),
            }
            ingestions.append(record)
            print(
                f"    ingest {entry['source_identity']:<34} {entry['version_label']:<12} "
                f"{finished['status']:<13} {elapsed_ms:7.0f} ms"
            )
        return {"ingestions": ingestions}
    finally:
        for client in clients.values():
            client.close()


def collect_office_state(
    stack: EvalStack, region: str, recorder: CheckRecorder
) -> dict:
    region = region.lower()
    client = Client(BASE_URLS[region])
    try:
        uploader = TOKENS[region]
        reviewer = REVIEWER_TOKENS[region]
        sources = client.get("/v1/sources", token_env=uploader)["sources"]
        claims = client.get("/v1/claims", token_env=reviewer, params={"include_review": "true"})[
            "claims"
        ]
        reviews = client.get("/v1/claims/reviews", token_env=reviewer)["reviews"]
        findings = client.get("/v1/findings", token_env=reviewer)["findings"]
        audit = client.get("/v1/audit/egress", token_env=reviewer)
        return {
            "sources": sources,
            "claims": claims,
            "reviews": reviews,
            "findings": findings,
            "egress_summary": audit.get("summary"),
            "model_calls": audit.get("model_calls"),
        }
    finally:
        client.close()


def per_source_extraction(state: dict, scenario: dict) -> dict:
    """Accepted/review/rejection counts per ingested source, expected vs observed."""

    # Count distinct claim identities: a supersession later carries a closed claim
    # forward as a new signed revision (same claim_id) to correct the effective
    # history, and that administrative revision is not another extraction result.
    accepted: dict[str, set[str]] = defaultdict(set)
    for claim in state["claims"]:
        if claim["status"] == "accepted":
            accepted[f"{claim['source_identity']}:{claim['source_version_label']}"].add(
                claim["claim_id"]
            )
    reviews: dict[str, Counter] = defaultdict(Counter)
    for review in state["reviews"]:
        reviews[review["source_id"]][review["reason_code"]] += 1
    source_id_key = {
        f"{source['source_identity']}:{source['version_label']}": source["source_id"]
        for source in state["sources"]
    }
    results = []
    for entry in scenario["sources"]:
        key = f"{entry['source_identity']}:{entry['version_label']}"
        source_id = source_id_key.get(key)
        observed_reviews = dict(reviews.get(source_id, {})) if source_id else {}
        expected_reviews = dict(entry.get("expect_reviews", {}))
        expected_rejections = dict(entry.get("expect_rejections", {}))
        job_entry = next(
            (
                item
                for item in scenario.get("_ingestions", [])
                if item["source_identity"] == entry["source_identity"]
                and item["version_label"] == entry["version_label"]
            ),
            None,
        )
        observed_rejections: dict[str, int] = {}
        if job_entry and job_entry.get("review_reason"):
            for code in re.findall(r"rejected:([a-z_]+)", job_entry["review_reason"]):
                observed_rejections[code] = observed_rejections.get(code, 0) + 1
        results.append(
            {
                "source": key,
                "region": entry["region"],
                "expected_accepted": entry.get("expect_accepted", 0),
                "observed_accepted": len(accepted.get(key, ())),
                "expected_reviews": expected_reviews,
                "observed_reviews": observed_reviews,
                "expected_rejections": expected_rejections,
                "observed_rejections": observed_rejections,
                "job_status": job_entry.get("status") if job_entry else None,
                "accepted_correct": len(accepted.get(key, ()))
                == entry.get("expect_accepted", 0),
                "reviews_correct": observed_reviews == expected_reviews,
                "rejections_correct": observed_rejections == expected_rejections,
            }
        )
    return {"per_source": results}


# ------------------------------------------------------------------- labeling


def evaluate_labels(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder
) -> dict:
    """Compare persisted findings and recomputed classifications to the labels."""

    stores = {
        region: office_store(stack, region)
        for region in _regions_of(scenario)
    }
    clause_maps = {region: claims_by_clause(store) for region, store in stores.items()}
    state = scenario.get("_state", {})
    findings = list(state.get("findings", []))

    finding_rows = []
    for finding in findings:
        clause_ids = sorted(
            evidence["clause_id"] for evidence in finding.get("evidence", [])
        )
        finding_rows.append(
            {
                "finding_id": finding["finding_id"],
                "finding_type": finding["finding_type"],
                "explanation_code": finding.get("explanation_code"),
                "alert": finding.get("alert"),
                "clause_ids": clause_ids,
                "detail": finding.get("detail", {}),
                "affected_scope": finding.get("affected_scope"),
            }
        )

    matched_finding_ids: set[str] = set()
    label_results = []
    for label in scenario["labels"]:
        left_clause, right_clause = label["left"], label["right"]
        views_left = [
            view
            for region in clause_maps
            for view in clause_maps[region].get(left_clause, [])
        ]
        views_right = [
            view
            for region in clause_maps
            for view in clause_maps[region].get(right_clause, [])
        ]
        result: dict[str, Any] = {
            "pair_id": label["pair_id"],
            "left": left_clause,
            "right": right_clause,
            "expected_type": label["expected_type"],
            "expected_explanation": label["expected_explanation"],
            "expected_persisted": label["persisted"],
            "views_found": bool(views_left and views_right),
            "computed_type": None,
            "computed_explanation": None,
            "classification_correct": False,
            "scope_correct": None,
            "matched_findings": [],
        }
        if views_left and views_right:
            # Real engine on the stored views; the same function publication uses.
            all_views = [view for region in stores for view in stores[region].claim_views()]
            started = time.perf_counter()
            computed = compare_pair(views_left[0], views_right[0], all_views)
            result["comparison_ms"] = round((time.perf_counter() - started) * 1000, 3)
            result["computed_type"] = computed.finding_type.value
            result["computed_explanation"] = computed.explanation_code.value
            result["classification_correct"] = (
                computed.finding_type.value == label["expected_type"]
                and computed.explanation_code.value == label["expected_explanation"]
            )
            scope = computed.affected_scope
            if label.get("expect_scope") and scope is not None:
                scope_json = scope.model_dump(mode="json")
                result["scope_correct"] = all(
                    scope_json.get(key) == value
                    for key, value in label["expect_scope"].items()
                )
            if label.get("expect_detail"):
                result["scope_correct"] = all(
                    str(computed.detail.get(key)) == value
                    if key == "affected_amount_range"
                    else computed.detail.get(key) == value
                    for key, value in label["expect_detail"].items()
                )
        clause_ids = sorted([left_clause, right_clause])
        for row in finding_rows:
            if row["clause_ids"] == clause_ids and row["finding_id"] not in matched_finding_ids:
                result["matched_findings"].append(
                    {
                        "finding_id": row["finding_id"],
                        "finding_type": row["finding_type"],
                        "explanation_code": row["explanation_code"],
                    }
                )
                matched_finding_ids.add(row["finding_id"])
                break
        result["persisted_count"] = len(result["matched_findings"])
        result["persistence_correct"] = (
            result["persisted_count"] > 0
        ) == label["persisted"]
        if label["persisted"]:
            result["persistence_correct"] = (
                result["persistence_correct"]
                and result["matched_findings"][0]["finding_type"] == label["expected_type"]
                and result["matched_findings"][0]["explanation_code"]
                == label["expected_explanation"]
            )
        label_results.append(result)

    unmatched = [
        row for row in finding_rows if row["finding_id"] not in matched_finding_ids
    ]
    return {
        "labels": label_results,
        "unmatched_findings": unmatched,
        "finding_count": len(finding_rows),
    }


def _regions_of(scenario: dict) -> list[str]:
    regions = {entry["region"].upper() for entry in scenario["sources"]}
    return sorted(regions)


# --------------------------------------------------------------------- queries


def run_queries(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder
) -> dict:
    queries = scenario.get("queries", [])
    if not queries:
        return {"checks": [], "timings_ms": []}
    results = []
    for query in queries:
        office = query.get("office", "dhaka")
        client = Client(BASE_URLS[office])
        token_env = TOKENS[office]
        target = parse_target(query["target"])
        body: dict[str, Any] = {
            "question": query["question"],
            "target": target,
            "valid_at": query.get("valid_at"),
        }
        if query.get("known_at"):
            body["known_at"] = query["known_at"]
        started = time.perf_counter()
        try:
            if "expect_http_status" in query:
                try:
                    client.post("/v1/queries", token_env=token_env, expect=query["expect_http_status"], json=body)
                    passed = True
                except DemoError as exc:
                    passed = f"HTTP {query['expect_http_status']}" in str(exc)
                elapsed_ms = (time.perf_counter() - started) * 1000
                results.append(
                    {
                        "query_id": query["query_id"],
                        "expect_http_status": query["expect_http_status"],
                        "passed": passed,
                        "elapsed_ms": round(elapsed_ms, 1),
                    }
                )
                recorder.expect(
                    f"query:{query['query_id']}",
                    passed,
                    f"expected HTTP {query['expect_http_status']}",
                )
                client.close()
                continue
            answer_body = client.post("/v1/queries", token_env=token_env, expect=201, json=body)
            elapsed_ms = (time.perf_counter() - started) * 1000
            answer = answer_body["answer"]
            record: dict[str, Any] = {
                "query_id": query["query_id"],
                "office": office,
                "status": answer["status"],
                "answer_text": answer["answer_text"],
                "elapsed_ms": round(elapsed_ms, 1),
                "warnings": [warning["code"] for warning in answer["warnings"]],
                "versions": sorted(
                    {citation["source_version_label"] for citation in answer["citations"]}
                ),
                "remote_citations": sum(1 for c in answer["citations"] if c["remote"]),
                "quotes_present": sum(1 for c in answer["citations"] if c.get("quote")),
                "answer_id": answer["answer_id"],
            }
            checks: list[tuple[str, bool, str]] = []
            if "expect_status" in query:
                checks.append(
                    ("status", answer["status"] == query["expect_status"], answer["status"])
                )
            if query.get("answer_contains"):
                checks.append(
                    (
                        "answer_text",
                        query["answer_contains"] in answer["answer_text"],
                        answer["answer_text"][:120],
                    )
                )
            if "expect_stale_warning" in query:
                stale = any(
                    warning["code"].startswith("stale_guidance")
                    for warning in answer["warnings"]
                )
                checks.append(("stale_warning", stale == query["expect_stale_warning"], str(stale)))
            if query.get("expect_versions"):
                checks.append(
                    (
                        "cited_versions",
                        record["versions"] == sorted(query["expect_versions"]),
                        str(record["versions"]),
                    )
                )
            if query.get("fetch_bundle"):
                bundle = client.get(
                    f"/v1/answers/{answer['answer_id']}/bundle", token_env=token_env
                )["bundle"]
                record["bundle"] = bundle
            for name, passed, detail in checks:
                recorder.expect(f"query:{query['query_id']}:{name}", passed, detail)
            results.append(record)
        except DemoError as exc:
            results.append(
                {
                    "query_id": query["query_id"],
                    "error": str(exc)[:400],
                }
            )
            recorder.expect(f"query:{query['query_id']}", False, str(exc)[:200])
        finally:
            client.close()
    return {
        "queries": [
            {key: value for key, value in record.items() if key != "bundle"}
            for record in results
        ],
        "bundles": {
            record["query_id"]: record.get("bundle")
            for record in results
            if record.get("bundle")
        },
    }


# ------------------------------------------------------------------ integrity


def check_status(report: dict, name: str) -> str:
    for check in report.get("checks", []):
        if check["check"] == name:
            return check["status"]
    return "missing"


def run_integrity(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder, query_result: dict
) -> dict:
    spec = scenario.get("integrity")
    if not spec:
        return {}
    region = "dhaka"
    client = Client(BASE_URLS[region])
    token_env = TOKENS[region]
    uploader = TOKENS[region]
    identity, version = spec["source"].split(":")
    findings: dict[str, Any] = {}
    try:
        sources = client.get("/v1/sources", token_env=uploader)["sources"]
        source = next(
            item
            for item in sources
            if item["source_identity"] == identity and item["version_label"] == version
        )
        original_path = RUNTIME / "originals" / f"{identity}_{version}.pdf"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(
            client.request(
                "GET", f"/v1/sources/{source['source_id']}/content", token_env=uploader
            ).content
        )
        original = client.post(
            "/v1/verifications/source",
            token_env=token_env,
            data={"source_id": source["source_id"]},
            files={"file": (original_path.name, original_path.read_bytes(), "application/pdf")},
        )["report"]
        findings["source_original"] = {
            "source_file_hash": check_status(original, "source_file_hash"),
            "clause_text_match": check_status(original, "clause_text_match"),
        }
        recorder.expect(
            "integrity:source_original",
            check_status(original, "source_file_hash") == "passed"
            and check_status(original, "clause_text_match") == "passed",
            str(findings["source_original"]),
        )

        metadata_only = EVAL_FIXTURES / spec["metadata_only_file"]
        meta_report = client.post(
            "/v1/verifications/source",
            token_env=token_env,
            data={"source_id": source["source_id"]},
            files={"file": (metadata_only.name, metadata_only.read_bytes(), "application/pdf")},
        )["report"]
        findings["source_metadata_only"] = {
            "source_file_hash": check_status(meta_report, "source_file_hash"),
            "content_normalized_text": check_status(meta_report, "content_normalized_text"),
        }
        recorder.expect(
            "integrity:source_metadata_only",
            check_status(meta_report, "source_file_hash") == "failed"
            and check_status(meta_report, "content_normalized_text") == "passed",
            str(findings["source_metadata_only"]),
        )

        modified = EVAL_FIXTURES / spec["modified_text_file"]
        mod_report = client.post(
            "/v1/verifications/source",
            token_env=token_env,
            data={"source_id": source["source_id"]},
            files={"file": (modified.name, modified.read_bytes(), "application/pdf")},
        )["report"]
        findings["source_modified_text"] = {
            "source_file_hash": check_status(mod_report, "source_file_hash"),
            "clause_text_match": check_status(mod_report, "clause_text_match"),
        }
        recorder.expect(
            "integrity:source_modified_text",
            check_status(mod_report, "source_file_hash") == "failed"
            and check_status(mod_report, "clause_text_match") == "failed",
            str(findings["source_modified_text"]),
        )

        bundle = query_result.get("bundles", {}).get(spec["answer_query"])
        if bundle is None:
            recorder.expect("integrity:bundle_available", False, "bundle was not fetched")
            return findings
        report = client.post(
            "/v1/verifications/bundle", token_env=token_env, json={"bundle": bundle}
        )
        findings["bundle_ok"] = {
            "verified": report["verified"],
            "checks": {item["check"]: item["status"] for item in report["report"]["checks"]},
        }
        recorder.expect("integrity:bundle_ok", bool(report["verified"]), str(findings["bundle_ok"]))

        tampered_answer = json.loads(json.dumps(bundle))
        tampered_answer["answer"]["answer_text"] = tampered_answer["answer"]["answer_text"].replace(
            "At least 2", "At least 1"
        )
        report_answer = client.post(
            "/v1/verifications/bundle", token_env=token_env, json={"bundle": tampered_answer}
        )
        failed = {
            item["check"]
            for item in report_answer["report"]["checks"]
            if item["status"] == "failed"
        }
        findings["bundle_tampered_answer"] = {
            "verified": report_answer["verified"],
            "failed_checks": sorted(failed),
        }
        recorder.expect(
            "integrity:bundle_tampered_answer",
            report_answer["verified"] is False
            and {"answer_text_hash", "answer_signature"} <= failed,
            str(findings["bundle_tampered_answer"]),
        )

        tampered_claim = json.loads(json.dumps(bundle))
        if tampered_claim["claims"]:
            tampered_claim["claims"][0]["claim"]["evidence"]["quote"] += " (altered)"
        report_claim = client.post(
            "/v1/verifications/bundle", token_env=token_env, json={"bundle": tampered_claim}
        )
        failed = {
            item["check"]
            for item in report_claim["report"]["checks"]
            if item["status"] == "failed"
        }
        findings["bundle_tampered_claim"] = {
            "verified": report_claim["verified"],
            "failed_checks": sorted(failed),
        }
        recorder.expect(
            "integrity:bundle_tampered_claim",
            report_claim["verified"] is False and "claim_signature" in failed,
            str(findings["bundle_tampered_claim"]),
        )

        tampered_manifest = json.loads(json.dumps(bundle))
        if tampered_manifest["manifests"]:
            payload = tampered_manifest["manifests"][0]["manifest_payload"]
            payload.setdefault("trusted_metadata", {})["authority"] = "procedure"
        report_manifest = client.post(
            "/v1/verifications/bundle", token_env=token_env, json={"bundle": tampered_manifest}
        )
        failed = {
            item["check"]
            for item in report_manifest["report"]["checks"]
            if item["status"] == "failed"
        }
        findings["bundle_tampered_manifest"] = {
            "verified": report_manifest["verified"],
            "failed_checks": sorted(failed),
        }
        recorder.expect(
            "integrity:bundle_tampered_manifest",
            report_manifest["verified"] is False and "manifest_signature" in failed,
            str(findings["bundle_tampered_manifest"]),
        )

        tampered_clause = json.loads(json.dumps(bundle))
        if tampered_clause["manifests"] and tampered_clause["manifests"][0]["clauses"]:
            tampered_clause["manifests"][0]["clauses"][0]["text"] += " (altered)"
        report_clause = client.post(
            "/v1/verifications/bundle", token_env=token_env, json={"bundle": tampered_clause}
        )
        failed = {
            item["check"]
            for item in report_clause["report"]["checks"]
            if item["status"] == "failed"
        }
        findings["bundle_tampered_clause"] = {
            "verified": report_clause["verified"],
            "failed_checks": sorted(failed),
        }
        recorder.expect(
            "integrity:bundle_tampered_clause",
            report_clause["verified"] is False and "clause_inclusion" in failed,
            str(findings["bundle_tampered_clause"]),
        )
        return findings
    finally:
        client.close()


# ------------------------------------------------------------------- security


def run_security(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder, state: dict
) -> dict:
    spec = scenario.get("security")
    if not spec:
        return {}
    identity, version = spec["restricted_source"].split(":")
    results: dict[str, Any] = {}
    uploader = Client(BASE_URLS["frankfurt"])
    reader = Client(BASE_URLS["frankfurt"])
    service = Client(BASE_URLS["frankfurt"])
    try:
        sources = uploader.get("/v1/sources", token_env=TOKENS["frankfurt"])["sources"]
        source = next(
            item
            for item in sources
            if item["source_identity"] == identity and item["version_label"] == version
        )
        results["source_metadata"] = {
            "sensitivity": source["sensitivity"],
            "office_export": source["office_export"],
        }
        recorder.expect(
            "security:manifest_metadata_not_overridden",
            source["sensitivity"] == "restricted" and source["office_export"] is False,
            str(results["source_metadata"]),
        )
        source_id = source["source_id"]

        try:
            reader.get(
                f"/v1/sources/{source_id}",
                token_env=spec["reader_token_env"],
                expect=404,
            )
            hidden = True
        except DemoError:
            hidden = False
        results["reader_source_hidden"] = hidden
        recorder.expect("security:reader_source_hidden", hidden)

        try:
            reader.request(
                "GET",
                f"/v1/sources/{source_id}/content",
                token_env=spec["reader_token_env"],
                expect=404,
            )
            contents_hidden = True
        except DemoError:
            contents_hidden = False
        results["reader_content_hidden"] = contents_hidden
        recorder.expect("security:reader_content_hidden", contents_hidden)

        reader_claims = reader.get(
            "/v1/claims", token_env=spec["reader_token_env"], params={"include_review": "true"}
        )["claims"]
        restricted_revisions = {
            claim["revision_id"]
            for claim in reader_claims
            if claim["source_id"] == source_id
        }
        results["restricted_claims_visible_to_reader"] = len(restricted_revisions)
        recorder.expect(
            "security:reader_claims_filtered", not restricted_revisions
        )

        query = {
            "request_id": "eval_restricted_export",
            "subject": "loan_approval",
            "target": {**parse_target(spec["restricted_export_target"]), "kind": "loan"},
            "valid_at": scenario.get("scenario_time", "2026-03-03T12:00:00Z"),
            # Microsecond precision matters: a wall clock truncated to whole seconds
            # can precede the just-ingested claim's system_from and hide it from the
            # bitemporal snapshot.
            "known_at": datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        }
        export = service.post(
            "/v1/federation/claims",
            token_env=SERVICE_TOKENS["frankfurt"],
            json=query,
        )
        summary = export["summary"]
        exported_source_ids = {
            claim["source_ref"] for claim in export["export"]["payload"]["claims"]
        }
        results["restricted_export"] = {
            "claims": summary["claims"],
            "withheld_restricted": summary["withheld_restricted"],
            "reason_codes": summary["reason_codes"],
            "restricted_source_exported": source_id in exported_source_ids,
        }
        recorder.expect(
            "security:restricted_export_denied",
            summary["withheld_restricted"] >= 1
            and "egress_denied_restricted_source" in summary["reason_codes"]
            and source_id not in exported_source_ids,
            str(results["restricted_export"]),
        )
        serialized = json.dumps(export)
        results["export_contains_clause_text"] = spec["restricted_clause_quote"] in serialized
        recorder.expect(
            "security:export_strips_clause_text",
            spec["restricted_clause_quote"] not in serialized,
        )
        return results
    finally:
        uploader.close()
        reader.close()
        service.close()


# ----------------------------------------------------------------- federation


def run_federation(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder
) -> dict:
    spec = scenario.get("federation")
    if not spec:
        return {}
    results: dict[str, Any] = {}
    gateway = Client(BASE_URLS["gateway"])
    dhaka = Client(BASE_URLS["dhaka"])
    try:
        body = {
            "question": spec["question"],
            "target": parse_target(spec["target"]),
            "valid_at": spec["valid_at"],
        }
        started = time.perf_counter()
        response = query_gateway(gateway, body)
        elapsed_ms = (time.perf_counter() - started) * 1000
        federated = response["federated_answer"]
        answer = federated["comparison"]["answer"]
        results["gateway_query"] = {
            "status": federated["status"],
            "comparator_region": federated["comparator_region"],
            "answer_text": answer["answer_text"],
            "origin_export": federated["origin_export"],
            "import": federated["import"],
            "remote_citations": sum(1 for c in answer["citations"] if c["remote"]),
            "quotes_present": sum(1 for c in answer["citations"] if c.get("quote")),
            "not_checked": federated["not_checked"],
            "elapsed_ms": round(elapsed_ms, 1),
        }
        expected_result = spec.get("expect_result", "compliance_gap")
        expected_text = spec.get(
            "expect_result_text", spec.get("expect_gap_text", "does not meet the requirement")
        )
        expected_status = spec.get("expect_status", "answered")
        recorder.expect(
            f"federation:{expected_result}",
            expected_text in answer["answer_text"] and answer["status"] == expected_status,
            answer["answer_text"][:160],
        )
        recorder.expect(
            "federation:remote_citation",
            sum(1 for c in answer["citations"] if c["remote"]) >= 1
            and all(not c.get("quote") for c in answer["citations"] if c["remote"]),
        )
        recorder.expect(
            "federation:origin_export",
            federated["origin_export"]["claims"] >= 1
            and federated["import"].get("accepted") is True,
            json.dumps(federated["origin_export"]),
        )
        serialized = json.dumps(response)
        canaries = [
            entry["source_identity"]
            for entry in scenario["sources"]
            if entry["region"] == "DHAKA"
        ]
        del canaries  # names are metadata, not clause text; the text check is below
        clause_texts = _scenario_clause_texts(scenario)
        leaked = [text for text in clause_texts if text in serialized]
        results["gateway_clause_text_leaks"] = leaked
        recorder.expect("federation:no_clause_text_on_wire", not leaked)

        # egress accounting on both offices
        for region in ("dhaka", "frankfurt"):
            client = Client(BASE_URLS[region])
            try:
                audit = client.get("/v1/audit/egress", token_env=REVIEWER_TOKENS[region])
                summary = audit.get("summary", {})
                results[f"egress_{region}"] = {
                    "summary": summary,
                    "model_calls": audit.get("model_calls"),
                }
                raw = int(summary.get("raw_source_text_bytes_between_offices") or 0)
                recorder.expect(f"federation:no_raw_text_{region}", raw == 0, str(raw))
            finally:
                client.close()
        gateway_audit = gateway.get(
            "/v1/audit/egress", token_env="DEMO_TOKEN_GATEWAY_SERVICE"
        )
        results["egress_gateway"] = {
            "counts": gateway_audit.get("counts"),
            "raw_source_text_transferred": gateway_audit.get("raw_source_text_transferred"),
        }
        recorder.expect(
            "federation:gateway_zero_raw_text",
            int(gateway_audit.get("raw_source_text_transferred") or 0) == 0,
        )
        results["relay_events"] = gateway_audit.get("relay_events", [])[-20:]
        return results
    finally:
        gateway.close()
        dhaka.close()


def _scenario_clause_texts(scenario: dict) -> list[str]:
    """All full clause sentences that appear in the scenario's fixture files."""

    texts: list[str] = []
    for entry in scenario["sources"]:
        if entry.get("clause_texts"):
            texts.extend(entry["clause_texts"])
    return texts


def run_outage(
    stack: EvalStack, scenario: dict, recorder: CheckRecorder
) -> dict:
    spec = scenario.get("outage")
    if not spec:
        return {}
    results: dict[str, Any] = {}
    gateway = Client(BASE_URLS["gateway"])
    try:
        stack.stop_one(spec["office_to_stop"])
        time.sleep(0.4)
        body = {
            "question": "How many approvals are required for a USD 30,000 loan?",
            "target": parse_target(spec["loan_query"]),
            "valid_at": scenario.get("scenario_time", "2026-03-03T12:00:00Z"),
        }
        try:
            response = gateway.post(
                "/v1/queries",
                token_env="DEMO_TOKEN_GATEWAY_SERVICE",
                expect=(200, 201),
                json=body,
            )
            federated = response["federated_answer"]
            offices = {item["region"]: item["status"] for item in federated["offices"]}
            results["partial_loan_query"] = {
                "status": federated["status"],
                "offices": offices,
                "warnings": [warning["code"] for warning in federated["warnings"]],
            }
            recorder.expect(
                "outage:partial_result_visible",
                federated["status"] == "abstained"
                and offices.get(spec["office_to_stop"].upper()) == "unavailable",
                json.dumps(results["partial_loan_query"]),
            )
        except DemoError as exc:
            results["partial_loan_query"] = {"error": str(exc)[:300]}
            recorder.expect("outage:partial_result_visible", False, str(exc)[:200])

        record_body = {
            "question": "How long must cross-office loan records be kept?",
            "target": parse_target(spec["record_query"]),
            "valid_at": scenario.get("scenario_time", "2026-03-03T12:00:00Z"),
        }
        status = None
        code = None
        try:
            gateway.post(
                "/v1/queries",
                token_env="DEMO_TOKEN_GATEWAY_SERVICE",
                expect=200,
                json=record_body,
            )
        except DemoError as exc:
            match = re.search(r"HTTP (\d+)", str(exc))
            status = int(match.group(1)) if match else None
            code_match = re.search(r'"code":\s*"([a-z_]+)"', str(exc))
            code = code_match.group(1) if code_match else None
        results["outage_record_query"] = {"http_status": status, "error_code": code}
        recorder.expect(
            "outage:structured_failure_visible",
            status == 503 and code == "office_unavailable",
            json.dumps(results["outage_record_query"]),
        )
        stack.restart_one(spec["office_to_stop"])
        return results
    finally:
        gateway.close()


# ------------------------------------------------------------------------ main


def aggregate_quality(per_scenario: list[dict]) -> dict:
    classes: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    totals = {
        "labels": 0,
        "views_found": 0,
        "classification_correct": 0,
        "persistence_correct": 0,
        "scope_checked": 0,
        "scope_correct": 0,
        "persisted_expected": 0,
        "persisted_absent_expected": 0,
    }
    for scenario in per_scenario:
        labels = scenario["quality"]["labels"]
        for label in labels:
            totals["labels"] += 1
            expected = label["expected_type"]
            totals["views_found"] += 1 if label["views_found"] else 0
            totals["classification_correct"] += 1 if label["classification_correct"] else 0
            totals["persistence_correct"] += 1 if label["persistence_correct"] else 0
            if label["scope_correct"] is not None:
                totals["scope_checked"] += 1
                totals["scope_correct"] += 1 if label["scope_correct"] else 0
            persisted_types = {row["finding_type"] for row in label["matched_findings"]}
            if label["expected_persisted"]:
                totals["persisted_expected"] += 1
                if expected in persisted_types:
                    classes[expected]["tp"] += 1
                else:
                    classes[expected]["fn"] += 1
            else:
                totals["persisted_absent_expected"] += 1
        for row in scenario["quality"]["unmatched_findings"]:
            expected_persisted = any(
                label["expected_persisted"]
                and set(row["clause_ids"]) == {label["left"], label["right"]}
                for label in labels
            )
            if not expected_persisted:
                classes[row["finding_type"]]["fp"] += 1
    for stats in classes.values():
        precision = stats["tp"] / (stats["tp"] + stats["fp"]) if stats["tp"] + stats["fp"] else None
        recall = stats["tp"] / (stats["tp"] + stats["fn"]) if stats["tp"] + stats["fn"] else None
        stats["precision"] = round(precision, 4) if precision is not None else None
        stats["recall"] = round(recall, 4) if recall is not None else None
    tp = sum(stats["tp"] for stats in classes.values())
    fp = sum(stats["fp"] for stats in classes.values())
    fn = sum(stats["fn"] for stats in classes.values())
    return {
        "per_class": {key: dict(value) for key, value in sorted(classes.items())},
        "totals": {
            **totals,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "classification_accuracy": round(totals["classification_correct"] / totals["labels"], 4)
            if totals["labels"]
            else None,
            "scope_accuracy": round(totals["scope_correct"] / totals["scope_checked"], 4)
            if totals["scope_checked"]
            else None,
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-stack", action="store_true")
    parser.add_argument("--only", action="append", default=None)
    parser.add_argument("--corpus", default=str(CORPUS_PATH))
    args = parser.parse_args(argv[1:])

    load_dotenv()
    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        die(f"corpus not found at {corpus_path}; run scripts/make_eval_corpus.py first")
    corpus = json.loads(corpus_path.read_text("utf-8"))
    try:
        token("DEMO_TOKEN_DHAKA_UPLOADER")
        token("DEMO_TOKEN_FRANKFURT_UPLOADER")
        token("DEMO_TOKEN_GATEWAY_SERVICE")
    except DemoError as exc:
        die(str(exc))

    scenarios = corpus["scenarios"]
    for scenario in scenarios:
        # ``scenario_time`` is a corpus-level constant; expose it on each scenario
        # for the security/outage probes that do not carry their own timestamp.
        scenario["scenario_time"] = corpus["scenario_time"]
    if args.only:
        scenarios = [s for s in scenarios if s["scenario_id"] in set(args.only)]
        if not scenarios:
            die(f"no scenario matched {args.only}")

    print("Evaluation run")
    print(f"  corpus          {corpus_path.relative_to(ROOT)}")
    print(f"  scenarios       {len(scenarios)} ({sum(len(s['labels']) for s in scenarios)} labels)")
    print(f"  mode            replay (offline; no model credentials required)")
    print(f"  events file     {RESULTS_PATH.relative_to(ROOT)}")

    started_at = time.time()
    recorder = CheckRecorder()
    per_scenario: list[dict] = []
    stack: EvalStack | None = None
    try:
        for scenario in scenarios:
            scenario_id = scenario["scenario_id"]
            print(f"\n[{scenario_id}] {scenario['split']} — {scenario['description']}")
            stack = EvalStack(scenario_id)
            stack.start()
            print(f"    stack ready in {stack.startup_seconds * 1000:.0f} ms (fresh databases)")
            try:
                ingestion = ingest_scenario(stack, scenario, recorder)
                scenario["_ingestions"] = ingestion["ingestions"]
                state = {}
                for region in _regions_of(scenario):
                    state[region] = collect_office_state(stack, region, recorder)
                merged = {
                    "sources": [s for r in state.values() for s in r["sources"]],
                    "claims": [c for r in state.values() for c in r["claims"]],
                    "reviews": [v for r in state.values() for v in r["reviews"]],
                    "findings": [f for r in state.values() for f in r["findings"]],
                    "egress": {region: data["egress_summary"] for region, data in state.items()},
                    "model_calls": {region: data["model_calls"] for region, data in state.items()},
                }
                scenario["_state"] = merged
                extraction = per_source_extraction(merged, scenario)
                for item in extraction["per_source"]:
                    if not (item["accepted_correct"] and item["reviews_correct"] and item["rejections_correct"]):
                        print(
                            f"    extraction mismatch {item['source']}: "
                            f"accepted {item['observed_accepted']}/{item['expected_accepted']}, "
                            f"reviews {item['observed_reviews']} vs {item['expected_reviews']}, "
                            f"rejections {item['observed_rejections']} vs {item['expected_rejections']}"
                        )
                    recorder.expect(
                        f"extraction:{item['source']}:accepted",
                        item["accepted_correct"],
                        f"{item['observed_accepted']} != {item['expected_accepted']}",
                    )
                    recorder.expect(
                        f"extraction:{item['source']}:reviews",
                        item["reviews_correct"],
                        f"{item['observed_reviews']} != {item['expected_reviews']}",
                    )
                    recorder.expect(
                        f"extraction:{item['source']}:rejections",
                        item["rejections_correct"],
                        f"{item['observed_rejections']} != {item['expected_rejections']}",
                    )
                quality = evaluate_labels(stack, scenario, recorder)
                query_result = run_queries(stack, scenario, recorder)
                integrity = run_integrity(stack, scenario, recorder, query_result)
                security = run_security(stack, scenario, recorder, merged)
                federation = run_federation(stack, scenario, recorder)
                outage = run_outage(stack, scenario, recorder)

                passed = sum(1 for x in quality["labels"] if x["classification_correct"])
                print(
                    f"    labels {passed}/{len(quality['labels'])} classified as expected; "
                    f"persisted findings {quality['finding_count']} "
                    f"({len(quality['unmatched_findings'])} unmatched)"
                )
                per_scenario.append(
                    {
                        "scenario_id": scenario_id,
                        "split": scenario["split"],
                        "family": scenario["family"],
                        "description": scenario["description"],
                        "sources": scenario["sources"],
                        "startup_ms": round((stack.startup_seconds or 0) * 1000, 1),
                        "ingestion": ingestion,
                        "extraction": extraction,
                        "quality": quality,
                        "queries": query_result.get("queries", []),
                        "integrity": integrity,
                        "security": security,
                        "federation": federation,
                        "outage": outage,
                        "rss_kb": stack.rss_kb(),
                        "egress": merged["egress"],
                        "model_calls": merged["model_calls"],
                    }
                )
            finally:
                if not args.keep_stack:
                    stack.stop()
    finally:
        if stack is not None and not args.keep_stack:
            stack.stop()

    scenario_rss = [
        value
        for scenario in per_scenario
        for value in (scenario.get("rss_kb") or {}).values()
        if value
    ]
    total_ingestion_ms = sum(
        item["elapsed_ms"]
        for scenario in per_scenario
        for item in scenario["ingestion"]["ingestions"]
    )
    model_modes = Counter(
        item["stage_modes"].get("extraction")
        for scenario in per_scenario
        for item in scenario["ingestion"]["ingestions"]
        if item.get("stage_modes")
    )
    model_calls_total = Counter()
    for scenario in per_scenario:
        for region, stats in (scenario.get("model_calls") or {}).items():
            if not stats:
                continue
            if isinstance(stats, dict):
                model_calls_total["calls"] += int(stats.get("calls") or stats.get("total") or 0)
                model_calls_total["attempts"] += int(stats.get("attempts") or 0)
                model_calls_total["latency_ms"] += int(stats.get("latency_ms") or 0)
    quality = aggregate_quality(per_scenario)
    results = {
        "schema_version": "1",
        "generated_by": "scripts/evaluate.py",
        "corpus": {
            "path": str(corpus_path.relative_to(ROOT)),
            "schema_version": corpus["schema_version"],
            "scenarios": len(per_scenario),
            "labels": sum(len(s["quality"]["labels"]) for s in per_scenario),
            "split_rule": corpus["split_rule"],
            "limitations": corpus.get("limitations", []),
        },
        "configuration": {
            "mode": "replay",
            "tenant_id": TENANT,
            "ports": PORTS,
            "fixtures_dir": str(EVAL_FIXTURES.relative_to(ROOT)),
            "runtime_dir": str(RUNTIME.relative_to(ROOT)),
            "stack_lifecycle": "fresh services per scenario (isolated databases)",
        },
        "quality": quality,
        "extraction": {
            "per_scenario": [
                {"scenario_id": scenario["scenario_id"], **scenario["extraction"]}
                for scenario in per_scenario
            ],
            "accepted_total": sum(
                item["observed_accepted"]
                for scenario in per_scenario
                for item in scenario["extraction"]["per_source"]
            ),
            "reviews_total": sum(
                sum(item["observed_reviews"].values())
                for scenario in per_scenario
                for item in scenario["extraction"]["per_source"]
            ),
            "rejections_total": sum(
                sum(item["observed_rejections"].values())
                for scenario in per_scenario
                for item in scenario["extraction"]["per_source"]
            ),
        },
        "timing": {
            "total_wall_seconds": round(time.time() - started_at, 2),
            "stack_startup_seconds": {
                scenario["scenario_id"]: round(scenario["startup_ms"] / 1000, 3)
                for scenario in per_scenario
            },
            "ingestion_seconds_total": round(total_ingestion_ms / 1000, 2),
            "ingestion_ms_per_source": [
                {
                    "scenario_id": scenario["scenario_id"],
                    "source": f"{item['source_identity']}:{item['version_label']}",
                    "status": item["status"],
                    "elapsed_ms": item["elapsed_ms"],
                }
                for scenario in per_scenario
                for item in scenario["ingestion"]["ingestions"]
            ],
        },
        "model_use": {
            "modes": dict(model_modes),
            "office_model_call_stats": dict(model_calls_total) or None,
            "note": (
                "replay fixtures return no provider usage; live runs record provider usage "
                "when the provider returns it and never invent tokens or cost"
            ),
        },
        "resource_use": {
            "evaluation_process_peak_rss_mb": round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1
            ),
            "service_rss_kb_samples": {
                scenario["scenario_id"]: scenario.get("rss_kb") for scenario in per_scenario
            },
            "max_service_rss_mb": round(max(scenario_rss) / 1024, 1) if scenario_rss else None,
        },
        "checks": recorder.summary(),
        "scenarios": per_scenario,
    }
    save_json(str(RESULTS_PATH.relative_to(ROOT)), results)

    print("\nResults")
    totals = quality["totals"]
    print(
        f"  findings        TP {totals['tp']}  FP {totals['fp']}  FN {totals['fn']}  "
        f"precision {totals['precision']}  recall {totals['recall']}"
    )
    print(
        f"  label accuracy  type {totals['classification_accuracy']}  "
        f"scope {totals['scope_accuracy']}  persistence "
        f"{totals['persistence_correct']}/{totals['labels']}"
    )
    print(f"  checks          {recorder.summary()['passed']}/{recorder.summary()['total']} passed")
    failed = [check for check in recorder.checks if not check.passed]
    if failed:
        print(f"  failed checks   {len(failed)}")
        for check in failed[:20]:
            print(f"    - {check.name}  {check.detail[:140]}")
    print(f"  results file    {RESULTS_PATH.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
