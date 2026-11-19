"""Demo 1 — The Catch: stale guidance after an explicit replacement.

    .venv/bin/python scripts/demo1_catch.py [--mode replay|cached|live]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import stack  # noqa: E402
from scripts.demo_client import (  # noqa: E402
    Client,
    DemoError,
    heading,
    ingest_slack,
    item,
    note,
    okay,
    services,
    step,
    token,
    wait_job,
    wait_ready,
)

DEMO_PLAN = ROOT / "fixtures" / "demo_plan.json"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=None, help="replay|cached|live")
    parser.add_argument("--no-ensure", action="store_true")
    args = parser.parse_args(argv[1:])

    import json
    import os

    from meridian.config import load_dotenv

    load_dotenv()
    mode = args.mode or os.environ.get("DEMO_EXTRACTION_MODE", "replay")
    plan = json.loads(DEMO_PLAN.read_text("utf-8"))

    if not args.no_ensure:
        stack.ensure()
    wait_ready()

    configured = services()
    dhaka = Client(configured["dhaka"].base_url)
    try:
        token_env = "DEMO_TOKEN_DHAKA_UPLOADER"

        heading("DEMO 1 — THE CATCH: stale guidance after a policy replacement")
        sources = dhaka.get("/v1/sources", token_env=token_env)["sources"]
        print("preloaded policy state")
        for source in sorted(sources, key=lambda s: (s["source_identity"], s["version_label"])):
            print(
                f"  {source['source_identity']:<28} {source['version_label']:<14} "
                f"{source['authority']:<10} effective {source['effective_from'] or '-':<22} "
                f"{source['sensitivity']}"
            )
        item("v2 closed by explicit supersession", _v2_closed(dhaka, sources))

        step(f"ingest the new Slack guidance (requested mode: {mode})")
        slack = plan["demo1_slack"]
        job = ingest_slack(
            dhaka,
            token_env,
            event_path=ROOT / "fixtures" / slack["file"],
            manifest_path=ROOT / "fixtures" / slack["manifest"],
            mode=mode,
        )
        # Live calls have a per-attempt model budget and durable jobs may retry the
        # extraction up to three times. Wait for that bounded budget rather than
        # returning while the worker is still legitimately processing the job.
        live_wait_seconds = max(
            90.0,
            3 * float(os.environ.get("LLM_JOB_MODEL_BUDGET_SECONDS", "65")) + 30.0,
        )
        done = wait_job(
            dhaka,
            token_env,
            job["job_id"],
            timeout=live_wait_seconds if mode == "live" else 90.0,
        )
        item("job_id", done["job_id"])
        item("status", done["status"])
        item("stage modes", done["stage_modes"])
        item("source_id", done["source_id"])
        if done["status"] not in {"succeeded", "needs_review"}:
            raise DemoError(
                f"Slack ingestion failed visibly: {done.get('error_code')} "
                f"{done.get('review_reason')}"
            )
        if done["stage_modes"].get("extraction") != mode:
            raise DemoError(
                f"stage mode {done['stage_modes'].get('extraction')!r} did not match requested {mode!r}"
            )
        if done["status"] == "needs_review" and done.get("review_reason"):
            note(f"review reason: {done['review_reason']}")

        step("derived findings on the Dhaka office")
        findings = dhaka.get("/v1/findings", token_env=token_env)["findings"]
        stale = [
            f for f in findings
            if f["finding_type"] == "stale_guidance" and f.get("alert", False)
        ]
        contradictions = [
            f for f in findings
            if f["finding_type"] == "contradiction" and f.get("alert", False)
        ]
        if not stale:
            raise DemoError("no stale-guidance finding was derived")
        finding = stale[0]
        detail = finding.get("detail", {})
        affected = detail.get("affected_amount_range", detail.get("affected_scope", "?"))
        item("finding_id", finding["finding_id"])
        item("type / severity", f"{finding['finding_type']} / {finding['severity']}")
        item("explanation_code", finding.get("explanation_code", "?"))
        item("affected amount range", affected)
        item("staleness evidence", detail.get("staleness_evidence", "-"))
        item("authority basis", finding.get("authority_basis", "-"))
        item("evidence disclosed", finding.get("evidence_disclosed", True))
        item("active contradiction alerts", len(contradictions))
        if len(stale) != 1:
            raise DemoError(f"expected exactly one stale-guidance finding, found {len(stale)}")
        if contradictions:
            raise DemoError("explicit v2 supersession must not raise a contradiction alert")
        if "25,000.00" not in affected or "50,000.00" not in affected:
            raise DemoError(f"unexpected affected range: {affected!r}")
        if "(" not in affected or "]" not in affected:
            raise DemoError(f"expected half-open (25000, 50000] range, got {affected!r}")
        okay("one high-severity stale guidance finding for (USD 25,000.00, USD 50,000.00]")
        okay("explicit v2 replacement produced no active contradiction alert")

        from scripts.demo_client import save_json

        save_json("evidence/demo1_finding.json", {"job": done, "findings": findings})
        print("\nevidence saved to evidence/demo1_finding.json")
    finally:
        dhaka.close()
    return 0


def _v2_closed(client: Client, sources: list[dict]) -> str:
    claims = client.get("/v1/claims", token_env="DEMO_TOKEN_DHAKA_UPLOADER")["claims"]
    v2 = [
        claim
        for claim in claims
        if claim["source_identity"] == "dhaka_lending_policy"
        and claim["source_version_label"] == "v2"
    ]
    if not v2:
        return "no v2 claims found (run `make seed` first)"
    closed = [claim for claim in v2 if claim["system_to"] is not None]
    return f"{len(closed)}/{len(v2)} v2 claims closed with signed closure events"


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except DemoError as exc:
        print(f"demo1 error: {exc}", file=sys.stderr)
        raise SystemExit(1)
