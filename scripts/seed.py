"""Seed the synthetic baseline through the normal ingestion APIs.

Replay supplies extraction *proposals* only; validators, comparison, persistence and
signing run normally.  Running twice is safe: duplicate source versions are detected
and no new findings are created.

    .venv/bin/python scripts/seed.py [--mode replay|cached|live] [--no-ensure]
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
    ingest_pdf,
    item,
    note,
    okay,
    services,
    token,
    wait_job,
    wait_ready,
)

# The restricted source is intentionally first: Demo 3 replays the historical moment
# when it was the only claim known, proving that a restricted-only export is blocked.
BASELINE = [
    (
        "dhaka",
        "fixtures/documents/dhaka/dhaka_credit_note_restricted_v1.pdf",
        "fixtures/manifests/dhaka_credit_note_restricted_v1.json",
    ),
    (
        "dhaka",
        "fixtures/documents/dhaka/dhaka_lending_policy_v2.pdf",
        "fixtures/manifests/dhaka_lending_policy_v2.json",
    ),
    (
        "dhaka",
        "fixtures/documents/dhaka/dhaka_lending_policy_v3.pdf",
        "fixtures/manifests/dhaka_lending_policy_v3.json",
    ),
    (
        "dhaka",
        "fixtures/documents/dhaka/dhaka_records_procedure_v1.pdf",
        "fixtures/manifests/dhaka_records_procedure_v1.json",
    ),
    (
        "frankfurt",
        "fixtures/documents/frankfurt/frankfurt_records_policy_v1.pdf",
        "fixtures/manifests/frankfurt_records_policy_v1.json",
    ),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=None, help="replay|cached|live")
    parser.add_argument("--no-ensure", action="store_true")
    args = parser.parse_args(argv[1:])

    import os

    from meridian.config import load_dotenv

    load_dotenv()
    mode = args.mode or os.environ.get("DEMO_EXTRACTION_MODE", "replay")
    if mode not in {"replay", "cached", "live"}:
        raise DemoError(f"unsupported mode {mode!r}")

    if not args.no_ensure:
        stack.ensure()
    wait_ready()

    configured = services()
    clients = {
        name: Client(configured[name].base_url) for name in ("dhaka", "frankfurt")
    }
    tokens = {
        "dhaka": "DEMO_TOKEN_DHAKA_UPLOADER",
        "frankfurt": "DEMO_TOKEN_FRANKFURT_UPLOADER",
    }
    try:
        token("DEMO_TOKEN_DHAKA_UPLOADER")
        token("DEMO_TOKEN_FRANKFURT_UPLOADER")
        print(f"seeding baseline in {mode} mode")
        for office, pdf, manifest in BASELINE:
            job = ingest_pdf(
                clients[office],
                tokens[office],
                pdf_path=ROOT / pdf,
                manifest_path=ROOT / manifest,
                mode=mode,
            )
            done = wait_job(clients[office], tokens[office], job["job_id"])
            if done["status"] not in {"succeeded", "needs_review"}:
                raise DemoError(
                    f"{office} ingestion of {Path(pdf).name} ended {done['status']}: "
                    f"{done.get('error_code')} {done.get('review_reason')}"
                )
            source_line = Path(manifest).stem
            print(
                f"  {office:<9} {source_line:<42} job {done['job_id']} "
                f"[{done['status']}, {done['stage_modes'].get('extraction', '?')}]"
            )
            if done.get("review_reason"):
                note(done["review_reason"])

        print("\nsource and claim inventory")
        for office in ("dhaka", "frankfurt"):
            sources = clients[office].get(
                "/v1/sources", token_env=tokens[office]
            )["sources"]
            claims = clients[office].get(
                "/v1/claims", token_env=tokens[office]
            )["claims"]
            findings = clients[office].get(
                "/v1/findings", token_env=tokens[office]
            )["findings"]
            print(f"  {office.upper():<9} {len(sources)} sources, {len(claims)} claims, "
                  f"{len(findings)} findings")
            if office == "dhaka":
                for finding in findings:
                    print(
                        f"    finding: {finding['finding_type']:<18} "
                        f"{finding.get('severity', ''):<8} {finding['finding_id']}"
                    )
        okay("baseline seeded; Demo 1 Slack guidance is intentionally NOT seeded")
    finally:
        for client in clients.values():
            client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except DemoError as exc:
        print(f"seed error: {exc}", file=sys.stderr)
        raise SystemExit(1)
