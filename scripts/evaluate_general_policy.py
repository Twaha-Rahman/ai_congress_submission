"""Isolated general-policy rehearsal, using the real parser and ingestion pipeline.

Offline mode uses controlled model responses: it checks plumbing, not intelligence.
Live mode evaluates the configured model and requires explicit paid-call opt-in.
Never touches the office's normal databases, keys, sources or fixture cache.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sys
import tempfile

import httpx
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import OfficeSettings, load_dotenv
from meridian.contracts.common import Mode
from meridian.contracts.manifest import SourceManifest
from meridian.extraction.service import ModelStageService
from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source, prepare_slack_source
from meridian.integrity.signing import Signer
from meridian.storage.db import Database
from meridian.storage.store import OfficeStore

CORPUS = ROOT / "fixtures/general_policy/cases.json"


def source_manifest(case: dict, *, slack=False) -> SourceManifest:
    return SourceManifest(
        tenant_id="general_policy_evaluation", region="DHAKA",
        source_identity=f"{case['id']}_{'message' if slack else 'policy'}", version_label="v1",
        source_type="slack" if slack else "pdf", subject="general_policy",
        authority="informal" if slack else "policy",
        policy_family="team_chat" if slack else case["domain"],
        scope={"kind": "policy", "description": "See policy and message applicability",
               "attributes": case.get("message_attributes" if slack else "policy_attributes", {})},
        effective_from=None if slack else case.get("policy_effective_from", "2026-10-01T00:00:00Z"),
        effective_to=case.get("message_effective_to") if slack else None,
        publication_time="2026-10-20T00:00:00Z", sensitivity="demo_shareable",
        permissions={"office_export": False, "hosted_model": True},
    )


def source(case, *, slack=False):
    manifest = source_manifest(case, slack=slack)
    if slack:
        raw = json.dumps({"channel": {"id": "CEVALUATION", "name": "evaluation"}, "event": {
            "ts": "2026-10-20T00:00:00Z", "text": case["message"], "event_id": case["id"],
        }}).encode()
        return prepare_slack_source(manifest, raw)
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), case["policy"], fontsize=11)
        raw = document.tobytes()
    return prepare_pdf_source(manifest, raw)


def offline_transport(case):
    """Controlled fixture outputs. Labels are intentionally used ONLY offline."""
    def respond(request):
        body = json.loads(request.content)
        user = body["messages"][1]["content"]
        lines = user.splitlines()
        name = body["response_format"]["json_schema"]["name"]
        if name == "policy_comparison":
            left = re.search(r"(?ms)^\[left_primary [^\n]*\]\n(.*?)(?=\n\n\[)", user).group(1)
            right = re.search(r"(?ms)^\[right_primary [^\n]*\]\n(.*?)(?=\n\n\[)", user).group(1)
            output = {
                "relationship": "insufficient_context" if case["expected"] == "needs_review" else case["expected"],
                "explanation": "Controlled offline response for ingestion/publication checks; not a model judgment.",
                "left_quote": left, "right_quote": right, "same_action": True,
                "scope_overlap": True, "time_overlap": True,
                "exceptions_resolved": case["expected"] != "needs_review",
                "evidence_sufficient": case["expected"] != "needs_review",
            }
        else:
            index = next(i for i, line in enumerate(lines) if line.startswith("[") and " | page " in line)
            text = "\n".join(lines[index+1:]).split("\n--- END UNTRUSTED SOURCE TEXT ---")[0].strip()
            output = {"rules": [{"subject": "general_policy", "scope": json.loads(lines[1]),
                "rule": {"kind": "policy_statement", "statement": text, "modality": "assertion",
                         "action": text}, "evidence": {"quote": text}}]}
        return httpx.Response(200, json={"model": "controlled-offline-fixture",
            "choices": [{"message": {"content": json.dumps(output)}}]})
    return httpx.MockTransport(respond)


def evaluate_case(case: dict, base: Path, *, settings: OfficeSettings | None = None) -> dict:
    live = settings is not None
    if settings is None:
        settings = OfficeSettings.from_env(region="DHAKA")
    settings = replace(settings, tenant_id="general_policy_evaluation", region="DHAKA",
        db_path=base / "office.db", source_dir=base / "sources", key_dir=base / "keys",
        trusted_keys_path=base / "trusted.json", fixtures_dir=base / "fixtures",
        llm_model=settings.llm_model if live else "controlled-offline-fixture",
        llm_api_key=settings.llm_api_key if live else "offline-not-a-real-key")
    store = OfficeStore(Database(settings.db_path), tenant_id=settings.tenant_id, region="DHAKA")
    signer = Signer.generate(key_id="evaluation-key", region="DHAKA")
    service = ModelStageService(settings, **({} if live else {"transport": offline_transport(case)}))
    outcomes = []
    for slack in (False, True):
        outcomes.append(ingest_prepared(store, source(case, slack=slack), mode=Mode.LIVE,
            service=service, signer=signer, now=datetime(2026, 10, 20, tzinfo=timezone.utc)))
    findings = store.list_findings()
    conflict = any(f.payload.explanation_code.value == "semantic_conflict" for f in findings)
    errors = [o.error_code for o in outcomes if o.error_code]
    reviews = sorted({reason for o in outcomes for reason in o.review_reasons + o.rejection_reasons})
    types = [f.payload.finding_type.value for f in findings]
    observed = "error" if errors else "conflict" if conflict else "needs_review" if reviews or "needs_review" in types else "consistent"
    return {"id": case["id"], "domain": case["domain"], "expected": case["expected"],
        "observed": observed, "passed": observed == case["expected"],
        "errors": errors, "review_reasons": reviews, "finding_types": types,
        "model_usage": store.model_call_stats()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--allow-paid-live", action="store_true")
    parser.add_argument("--only", help="Run one case ID")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/general_policy_evaluation.json")
    args = parser.parse_args()
    settings = None
    if args.mode == "live":
        if not args.allow_paid_live:
            parser.error("live evaluation requires --allow-paid-live; it makes paid model calls")
        load_dotenv()
        settings = OfficeSettings.from_env(region="DHAKA")
        if not settings.has_model_credentials:
            parser.error("configure LLM_MODEL/LLM_API_KEY (or DHAKA_ overrides) before live evaluation")
    cases = json.loads(CORPUS.read_text())["cases"]
    if args.only:
        cases = [case for case in cases if case["id"] == args.only]
        if not cases:
            parser.error("unknown case ID")
    results = []
    with tempfile.TemporaryDirectory(prefix="meridian-policy-evaluation-") as directory:
        for case in cases:
            result = evaluate_case(case, Path(directory) / case["id"], settings=settings)
            results.append(result)
            print(f"{case['id']}: expected {result['expected']}, observed {result['observed']}")
    report = {"mode": args.mode, "model": settings.llm_model if settings else "controlled-offline-fixture",
        "meaning": "Development-corpus model evaluation" if settings else "Offline contract simulation; NOT a model accuracy result",
        "passed": sum(r["passed"] for r in results), "total": len(results), "cases": results}
    if settings:
        tp = sum(r["expected"] == r["observed"] == "conflict" for r in results)
        predicted = sum(r["observed"] == "conflict" for r in results)
        actual = sum(r["expected"] == "conflict" for r in results)
        report.update(conflict_precision=tp / predicted if predicted else None,
                      conflict_recall=tp / actual if actual else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['passed']}/{report['total']} passed. {report['meaning']}. Report: {args.output}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
