"""Demo 2 — The Trace: deterministic answer, history, and tamper detection.

    .venv/bin/python scripts/demo2_trace.py [--mode replay|cached|live]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import stack  # noqa: E402
from scripts.demo_client import (  # noqa: E402
    SCENARIO_TIME,
    Client,
    DemoError,
    fail,
    heading,
    item,
    loan_target,
    note,
    okay,
    query_office,
    save_json,
    services,
    step,
    token,
    verify_bundle,
    verify_source,
    wait_ready,
)

QUESTION = "How many approvals are required for a USD 30,000 business loan originated in Dhaka?"
BOUNDARIES = (
    (2500000, 1, "0.01 below the advice gap start"),
    (2500001, 2, "first cent inside the stale advice gap"),
    (5000000, 2, "upper endpoint of the stale advice gap"),
    (5000001, 2, "one cent above the advice scope"),
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=None)
    parser.add_argument("--no-ensure", action="store_true")
    args = parser.parse_args(argv[1:])

    if not args.no_ensure:
        stack.ensure()
    wait_ready()

    configured = services()
    dhaka = Client(configured["dhaka"].base_url)
    token_env = "DEMO_TOKEN_DHAKA_UPLOADER"
    try:
        token(token_env)
        heading("DEMO 2 — THE TRACE: answer, historical truth, verified evidence")
        sources = dhaka.get("/v1/sources", token_env=token_env)["sources"]
        v3 = _source(sources, "dhaka_lending_policy", "v3")
        if v3 is None:
            raise DemoError("dhaka_lending_policy v3 is missing; run `make seed` first")
        slack = _source(sources, "dha_slack_credit_channel", "2026-03-03")
        if slack is None:
            raise DemoError("Slack guidance is missing; run `make demo-replay` (Demo 1) first")

        step("boundary behavior under the current (v3) policy at 2026-03-03")
        for amount, expected, label in BOUNDARIES:
            body = query_office(
                dhaka,
                token_env,
                question=f"approvals for USD {amount / 100:,.2f}?",
                target=loan_target(amount),
            )
            answer = body["answer"]
            text = answer["answer_text"]
            numbers = _approval_counts(text)
            stale_warned = any(
                warning["code"].startswith("stale_guidance")
                for warning in answer["warnings"]
            )
            shown = sorted(numbers)[0] if numbers else "?"
            print(
                f"  USD {amount / 100:>10,.2f}  ->  At least {shown} "
                f"stale_warning={str(stale_warned):<5} ({label})"
            )
            if expected not in numbers:
                raise DemoError(
                    f"expected {expected} approval(s) for {amount} minor units; got {numbers}: {text}"
                )
            expected_warning = amount in (2500001, 5000000)
            if stale_warned != expected_warning:
                raise DemoError(
                    f"stale-guidance warning for {amount} was {stale_warned}, "
                    f"expected {expected_warning}"
                )

        step("history: valid_at selects the January policy, known_at cannot use v3 early")
        january = query_office(
            dhaka,
            token_env,
            question=QUESTION,
            target=loan_target(3000000),
            valid_at="2026-01-15T12:00:00Z",
        )
        item("valid_at 2026-01-15 -> answer", _short(january["answer"]["answer_text"]))
        if 1 not in _approval_counts(january["answer"]["answer_text"]):
            raise DemoError("January valid_at must select the v2 one-approval rule")

        from datetime import datetime, timedelta, timezone

        v3_time = datetime.fromisoformat(v3["ingested_at"].replace("Z", "+00:00"))
        just_before = (v3_time - timedelta(microseconds=1)).astimezone(timezone.utc)
        early = query_office(
            dhaka,
            token_env,
            question=QUESTION,
            target=loan_target(3000000),
            known_at=just_before.isoformat().replace("+00:00", "Z"),
        )
        versions_early = {
            citation["source_version_label"] for citation in early["answer"]["citations"]
        }
        item("known_at = 1µs before v3 ingestion", f"cited versions: {sorted(versions_early)}")
        if versions_early != {"v2"}:
            raise DemoError(f"expected only v2 at the early checkpoint, got {versions_early}")
        if 1 not in _approval_counts(early["answer"]["answer_text"]):
            raise DemoError("the pre-v3 knowledge snapshot must require one approval")

        at_checkpoint = query_office(
            dhaka,
            token_env,
            question=QUESTION,
            target=loan_target(3000000),
            known_at=v3["ingested_at"],
        )
        versions_now = {
            citation["source_version_label"] for citation in at_checkpoint["answer"]["citations"]
        }
        item("known_at = v3 ingestion checkpoint", f"cited versions: {sorted(versions_now)}")
        if versions_now != {"v3"}:
            raise DemoError(f"at the v3 checkpoint only v3 may govern, got {versions_now}")
        okay("history is version-correct on both axes (valid_at and known_at)")

        step("current USD 30,000 answer with citations and signature")
        body = query_office(dhaka, token_env, question=QUESTION, target=loan_target(3000000))
        answer = body["answer"]
        item("status", answer["status"])
        item("answer", answer["answer_text"])
        item("signature key", body["answer_key_id"])
        item("answer_hash", body["answer_hash"][:16] + "…")
        item("modes", answer["modes"])
        for citation in answer["citations"]:
            quote = citation.get("quote") or ""
            print(
                f"    cite {citation['source_identity']} {citation['source_version_label']} "
                f"clause {citation['clause_id'].split(':')[-1]} p{citation['page']}: "
                f"\"{quote[:90]}{'…' if len(quote) > 90 else ''}\""
            )
        if 2 not in _approval_counts(answer["answer_text"]):
            raise DemoError("the USD 30,000 answer must require two approvals")
        if not any(w["code"].startswith("stale_guidance") for w in answer["warnings"]):
            raise DemoError("the USD 30,000 answer must warn about stale guidance")

        step("lineage graph for the answer")
        lineage = dhaka.get(
            f"/v1/answers/{answer['answer_id']}/lineage", token_env=token_env
        )["lineage"]
        item("nodes / edges", f"{len(lineage['nodes'])} / {len(lineage['edges'])}")
        for node in lineage["nodes"][:10]:
            print(f"    {node['node_type']:<14} {node['label']}")
        if len(lineage["nodes"]) < 4:
            raise DemoError("lineage graph is unexpectedly shallow")

        step("signed evidence bundle and independent verification")
        bundle = dhaka.get(
            f"/v1/answers/{answer['answer_id']}/bundle", token_env=token_env
        )["bundle"]
        bundle_path = save_json("evidence/demo2_bundle.json", bundle)
        item("bundle saved", str(bundle_path.relative_to(ROOT)))
        report = verify_bundle(dhaka, token_env, bundle)
        _print_report(report)
        if not report.get("verified"):
            raise DemoError("the untouched bundle must verify")
        okay("untouched bundle verifies against pinned keys")

        step("original vs changed source copies")
        original = dhaka.request(
            "GET",
            f"/v1/sources/{v3['source_id']}/content",
            token_env=token_env,
            expect=200,
        )
        original_path = ROOT / "evidence" / "demo2_v3_original.pdf"
        original_path.write_bytes(original.content)
        report_ok = verify_source(dhaka, token_env, v3["source_id"], original_path)
        _print_source_report("original copy", report_ok)
        if _status(report_ok, "source_file_hash") != "passed":
            raise DemoError("the stored original must pass the file-hash check")

        metadata_only = ROOT / "fixtures" / "tampered" / "dhaka_lending_policy_v3_metadata_only.pdf"
        report_meta = verify_source(dhaka, token_env, v3["source_id"], metadata_only)
        _print_source_report("metadata-only edit", report_meta)
        if _status(report_meta, "source_file_hash") != "failed":
            raise DemoError("a metadata-only edit must fail the raw file hash")
        if _status(report_meta, "content_normalized_text") != "passed":
            raise DemoError("metadata-only edit must leave normalized clause text unchanged")

        modified = ROOT / "fixtures" / "tampered" / "dhaka_lending_policy_v3_modified_text.pdf"
        report_mod = verify_source(dhaka, token_env, v3["source_id"], modified)
        _print_source_report("modified text", report_mod)
        if _status(report_mod, "clause_text_match") != "failed":
            raise DemoError("modified clause text must fail the clause match")
        okay("file identity is separate from passage identity")

        step("tampered answer bundle")
        tampered = json.loads(json.dumps(bundle))
        tampered["answer"]["answer_text"] = (
            tampered["answer"]["answer_text"].replace("At least 2", "At least 1")
        )
        tamper_report = verify_bundle(dhaka, token_env, tampered)
        _print_report(tamper_report)
        if tamper_report.get("verified"):
            raise DemoError("a modified answer text must not verify")
        fail_statuses = {
            check["check"] for check in tamper_report["report"]["checks"] if check["status"] == "failed"
        }
        if not {"answer_text_hash", "answer_signature"} <= fail_statuses:
            raise DemoError(f"tampered answer failed checks {fail_statuses}, expected text+signature")
        okay(f"tampered answer fails: {', '.join(sorted(fail_statuses))}")
        save_json(
            "evidence/demo2_tamper_report.json",
            {"tampered": tamper_report, "source_reports": {
                "original": report_ok, "metadata_only": report_meta, "modified_text": report_mod
            }},
        )
    finally:
        dhaka.close()
    return 0


def _source(sources: list[dict], identity: str, version: str) -> dict | None:
    for source in sources:
        if source["source_identity"] == identity and source["version_label"] == version:
            return source
    return None


def _approval_counts(text: str) -> set[int]:
    import re

    return {int(match) for match in re.findall(r"At least (\d+) approval", text)}


def _short(text: str, limit: int = 110) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _print_report(body: dict) -> None:
    report = body.get("report", {})
    item("verified", body.get("verified"))
    for check in report.get("checks", []):
        detail = check.get("detail") or {}
        reason = f"  ({check['reason']})" if check.get("reason") else ""
        extra = f"  {detail}" if detail else ""
        print(f"    {check['status']:<11} {check['check']}{reason}{extra}")


def _print_source_report(label: str, report: dict) -> None:
    print(f"  {label}")
    for check in report.get("checks", []):
        print(f"    {check['status']:<11} {check['check']}")


def _status(report: dict, name: str) -> str:
    for check in report.get("checks", []):
        if check["check"] == name:
            return check["status"]
    return "missing"


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except DemoError as exc:
        print(f"demo2 error: {exc}", file=sys.stderr)
        raise SystemExit(1)
