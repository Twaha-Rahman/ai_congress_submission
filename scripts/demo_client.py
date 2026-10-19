"""Shared HTTP client and terminal formatting for seed/demo/evaluation scripts."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import load_dotenv  # noqa: E402

TENANT = "meridian_demo"
SCENARIO_TIME = "2026-03-03T12:00:00Z"
OFFICES = ("DHAKA", "FRANKFURT")


class DemoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    base_url: str
    token_env: str


def services() -> dict[str, Service]:
    load_dotenv()
    return {
        "dhaka": Service(
            "dhaka",
            os.environ.get("DHAKA_BASE_URL", "http://127.0.0.1:8081"),
            "DEMO_TOKEN_DHAKA_UPLOADER",
        ),
        "frankfurt": Service(
            "frankfurt",
            os.environ.get("FRANKFURT_BASE_URL", "http://127.0.0.1:8082"),
            "DEMO_TOKEN_FRANKFURT_UPLOADER",
        ),
        "gateway": Service(
            "gateway",
            os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:8080"),
            "DEMO_TOKEN_GATEWAY_SERVICE",
        ),
    }


def token(name: str) -> str:
    load_dotenv()
    value = os.environ.get(name, "")
    if not value:
        raise DemoError(
            f"missing {name}; run `make setup` and source the generated .env"
        )
    return value


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        token_env: str | None = None,
        expect: int | tuple[int, ...] = 200,
        **kwargs: Any,
    ) -> Any:
        headers = kwargs.pop("headers", {})
        if token_env:
            headers["authorization"] = f"Bearer {token(token_env)}"
        response = self.http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        expected = (expect,) if isinstance(expect, int) else expect
        if response.status_code not in expected:
            detail = response.text
            try:
                detail = json.dumps(response.json(), indent=2)[:4000]
            except ValueError:
                pass
            raise DemoError(
                f"{method} {self.base_url}{path} -> HTTP {response.status_code}\n{detail}"
            )
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)


def wait_ready(timeout: float = 45.0) -> dict[str, dict]:
    """Wait for all three services and fail with a readable log hint."""

    deadline = time.time() + timeout
    last_error = "no response"
    while time.time() < deadline:
        bodies: dict[str, dict] = {}
        try:
            for name, service in services().items():
                response = httpx.get(f"{service.base_url}/health", timeout=2.0)
                response.raise_for_status()
                bodies[name] = response.json()
            return bodies
        except Exception as exc:  # noqa: BLE001 - retry until deadline
            last_error = str(exc)
            time.sleep(0.3)
    raise DemoError(
        f"services did not become ready within {timeout:.0f}s ({last_error}). "
        "Run `make local-up` and inspect runtime/logs/."
    )


def wait_job(client: Client, token_env: str, job_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        body = client.get(
            f"/v1/jobs/{job_id}", token_env=token_env, expect=200
        )
        last = body["job"]
        if last["status"] in {"succeeded", "needs_review", "failed"}:
            return last
        time.sleep(0.25)
    raise DemoError(f"job {job_id} did not finish within {timeout:.0f}s: {last}")


def ingest_pdf(
    client: Client,
    token_env: str,
    *,
    pdf_path: Path,
    manifest_path: Path,
    mode: str | None = None,
) -> dict:
    data = {"manifest": manifest_path.read_text("utf-8")}
    if mode:
        data["mode"] = mode
    with open(pdf_path, "rb") as handle:
        body = client.post(
            "/v1/ingestions/pdf",
            token_env=token_env,
            expect=202,
            data=data,
            files={"file": (pdf_path.name, handle, "application/pdf")},
        )
    return body["job"]


def ingest_slack(
    client: Client,
    token_env: str,
    *,
    event_path: Path,
    manifest_path: Path,
    mode: str | None = None,
) -> dict:
    payload = json.loads(event_path.read_text("utf-8"))
    payload["manifest"] = json.loads(manifest_path.read_text("utf-8"))
    if mode:
        payload["mode"] = mode
    body = client.post(
        "/v1/ingestions/slack",
        token_env=token_env,
        expect=202,
        json=payload,
    )
    return body["job"]


def verify_source(client: Client, token_env: str, source_id: str, path: Path) -> dict:
    with open(path, "rb") as handle:
        body = client.post(
            "/v1/verifications/source",
            token_env=token_env,
            data={"source_id": source_id},
            files={"file": (path.name, handle, "application/pdf")},
        )
    return body["report"]


def verify_bundle(client: Client, token_env: str, bundle: dict) -> dict:
    return client.post(
        "/v1/verifications/bundle",
        token_env=token_env,
        json={"bundle": bundle},
    )


def query_office(
    client: Client,
    token_env: str,
    *,
    question: str,
    target: dict,
    valid_at: str = SCENARIO_TIME,
    known_at: str | None = None,
) -> dict:
    body: dict[str, Any] = {
        "question": question,
        "target": target,
        "valid_at": valid_at,
    }
    if known_at is not None:
        body["known_at"] = known_at
    return client.post("/v1/queries", token_env=token_env, expect=201, json=body)


def query_gateway(client: Client, query: dict) -> dict:
    return client.post(
        "/v1/queries",
        token_env="DEMO_TOKEN_GATEWAY_SERVICE",
        expect=(200, 201),
        json=query,
    )


def loan_target(amount_minor: int, *, origin: str = "DHAKA") -> dict:
    return {
        "subject": "loan_approval",
        "loan_type": "business",
        "currency": "USD",
        "origin_office": origin,
        "amount_minor": amount_minor,
    }


def retention_target() -> dict:
    return {
        "subject": "record_retention",
        "record_class": "loan_records",
        "origin_office": "DHAKA",
        "processing_office": "FRANKFURT",
        "product": "MTF_CROSS_OFFICE",
        "starting_event": "loan_closure",
    }


# --------------------------------------------------------------------- output
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def heading(text: str) -> None:
    print(f"\n{BOLD}{'=' * 78}{RESET}")
    print(f"{BOLD}{text}{RESET}")
    print(f"{BOLD}{'=' * 78}{RESET}")


def step(text: str) -> None:
    print(f"\n{CYAN}▸ {text}{RESET}")


def item(label: str, value: Any) -> None:
    print(f"  {label:<30} {value}")


def okay(text: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {text}")


def warn(text: str) -> None:
    print(f"  {YELLOW}WARN{RESET}  {text}")


def fail(text: str) -> None:
    print(f"  {RED}FAIL{RESET}  {text}")


def note(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


def save_json(relative: str, payload: Any) -> Path:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
