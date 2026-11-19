"""Live smoke test for the two Northwind policy-conflict PDFs.

This runs the real ingestion pipeline in an isolated temporary office, using the
model configured in the private `.env`.  It checks the expected conflict pairs and
the expected non-conflicts from ``fixtures/conflict_testing/expected_findings.json``.

It makes paid model calls and never touches the normal demo databases, sources or
fixture cache.

Run:
    .venv/bin/python scripts/check_conflict_test_docs.py --allow-paid-live
    .venv/bin/python scripts/check_conflict_test_docs.py --allow-paid-live --strict
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import OfficeSettings, load_dotenv
from meridian.contracts.common import Mode
from meridian.contracts.findings import FindingRecord
from meridian.contracts.manifest import SourceManifest
from meridian.extraction.service import ModelStageService
from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source
from meridian.integrity.signing import Signer
from meridian.storage.db import Database
from meridian.storage.store import OfficeStore

FIXTURES = ROOT / "fixtures" / "conflict_testing"
EXPECTED_PATH = FIXTURES / "expected_findings.json"
DOCUMENTS = [
    ("northwind_employee_handbook_2026", "northwind_employee_handbook_2026.pdf"),
    (
        "northwind_security_procurement_procedure_2026",
        "northwind_security_procurement_procedure_2026.pdf",
    ),
]


def _lower(value: str) -> str:
    return " ".join(value.casefold().split())


def _quote_has_all(quote: str, terms: list[str]) -> bool:
    text = _lower(quote)
    return all(_lower(term) in text for term in terms)


def _match_pair(finding: FindingRecord, left_terms: list[str], right_terms: list[str]) -> bool:
    quotes = [evidence.quote for evidence in finding.payload.evidence]
    if len(quotes) < 2:
        return False
    for index, quote in enumerate(quotes):
        if not _quote_has_all(quote, left_terms):
            continue
        for other_index, other in enumerate(quotes):
            if other_index != index and _quote_has_all(other, right_terms):
                return True
    for index, quote in enumerate(quotes):
        if not _quote_has_all(quote, right_terms):
            continue
        for other_index, other in enumerate(quotes):
            if other_index != index and _quote_has_all(other, left_terms):
                return True
    return False


def _findings(store: OfficeStore) -> list[FindingRecord]:
    return store.list_findings(limit=100000)


def _conflict_findings(findings: list[FindingRecord]) -> list[FindingRecord]:
    return [finding for finding in findings if finding.payload.explanation_code.value == "semantic_conflict"]


def _finding_summary(finding: FindingRecord) -> dict:
    payload = finding.payload
    return {
        "type": payload.finding_type.value,
        "severity": payload.severity.value,
        "explanation_code": payload.explanation_code.value,
        "authority_basis": payload.authority_basis,
        "detail": payload.detail,
        "evidence": [
            {
                "source_id": evidence.source_id,
                "section": evidence.section,
                "page": evidence.page,
                "quote": evidence.quote,
            }
            for evidence in payload.evidence
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid-live", action="store_true",
                        help="required: this makes real model calls")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when a conflict is missing or a decoy is flagged")
    parser.add_argument("--top-k", type=int, default=8,
                        help="candidate statements per statement (default: 8)")
    parser.add_argument("--max-pairs", type=int, default=120,
                        help="comparison pairs per document ingestion (default: 120)")
    parser.add_argument("--budget", type=float, default=900.0,
                        help="model seconds per ingestion (default: 900)")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "evidence" / "conflict_test_report.json")
    args = parser.parse_args()

    if not args.allow_paid_live:
        parser.error("live conflict checking makes paid model calls; pass --allow-paid-live")

    load_dotenv()
    settings = OfficeSettings.from_env(region="DHAKA")
    if not settings.has_model_credentials:
        parser.error("configure LLM_MODEL / LLM_API_KEY (or DHAKA_ overrides) before running")

    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    report: dict = {
        "mode": "live",
        "model": settings.llm_model,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "documents": [],
        "claims": [],
        "findings": [],
        "checks": {},
    }

    with tempfile.TemporaryDirectory(prefix="northwind-conflict-test-") as directory:
        base = Path(directory)
        live_settings = replace(
            settings,
            tenant_id="meridian_demo",
            region="DHAKA",
            db_path=base / "office.db",
            source_dir=base / "sources",
            key_dir=base / "keys",
            trusted_keys_path=base / "trusted_keys.json",
            fixtures_dir=base / "fixtures",
            policy_comparison_top_k=max(1, min(50, args.top_k)),
            policy_comparison_max_pairs=max(1, min(200, args.max_pairs)),
            llm_job_model_budget_seconds=args.budget,
        )
        store = OfficeStore(
            Database(live_settings.db_path),
            tenant_id=live_settings.tenant_id,
            region="DHAKA",
        )
        signer = Signer.generate(key_id="northwind-conflict-test", region="DHAKA")
        service = ModelStageService(live_settings)

        for source_identity, filename in DOCUMENTS:
            manifest_path = FIXTURES / "manifests" / f"{source_identity}.json"
            manifest = SourceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            prepared = prepare_pdf_source(manifest, (FIXTURES / filename).read_bytes())
            outcome = ingest_prepared(
                store,
                prepared,
                mode=Mode.LIVE,
                service=service,
                signer=signer,
                now=datetime(2026, 1, 15, tzinfo=timezone.utc),
                source_dir=live_settings.source_dir,
            )
            report["documents"].append({
                "source_identity": source_identity,
                "pages": prepared.parsed.page_count,
                "error_code": outcome.error_code,
                "error_detail": outcome.error_detail,
                "duplicate": outcome.duplicate,
                "claim_revision_ids": outcome.claim_revision_ids,
                "finding_types": outcome.finding_types,
                "review_reasons": outcome.review_reasons,
                "rejection_reasons": outcome.rejection_reasons,
                "warnings": outcome.warnings,
            })
            status = "ERROR" if outcome.error_code else "ok"
            print(f"{source_identity}: {status}; {len(outcome.claim_revision_ids)} accepted claims; "
                  f"review reasons={outcome.review_reasons or 'none'}")
            if outcome.error_code:
                print(f"  {outcome.error_code}: {outcome.error_detail}")

        views = store.claim_views(subject="general_policy", include_remote=False, limit=None)
        for view in views:
            revision = view.revision
            statement = getattr(revision.rule, "statement", "")
            report["claims"].append({
                "source_identity": revision.source_identity,
                "section": revision.evidence.section,
                "page": revision.evidence.page,
                "statement": statement,
                "authority": revision.authority.value,
                "current": view.is_current,
            })

        findings = _findings(store)
        report["findings"] = [_finding_summary(finding) for finding in findings]
        conflicts = _conflict_findings(findings)

        print("\nComparison findings:")
        if not findings:
            print("  none")
        for finding in findings:
            payload = finding.payload
            quotes = " || ".join(evidence.quote for evidence in payload.evidence)
            print(f"  [{payload.finding_type.value}/{payload.severity.value}] "
                  f"{payload.explanation_code.value}: {quotes[:240]}")
            if payload.detail.get("reason"):
                print(f"      reason={payload.detail['reason']}")

        checks = {"conflicts": [], "needs_review": [], "decoys": [], "unexpected_conflicts": []}
        for item in expected["expected_conflicts"]:
            matched = next(
                (
                    finding for finding in conflicts
                    if _match_pair(finding, item["left_terms"], item["right_terms"])
                    and finding.payload.finding_type.value == item["expected_finding_type"]
                ),
                None,
            )
            checks["conflicts"].append({
                "id": item["id"],
                "passed": matched is not None,
                "expected_finding_type": item["expected_finding_type"],
                "matched_finding": _finding_summary(matched) if matched else None,
            })
            print(("  PASS " if matched else "  MISS ") + item["id"])

        for item in expected.get("expected_needs_review", []):
            matched = next(
                (
                    finding for finding in findings
                    if finding.payload.finding_type.value == item["expected_finding_type"]
                    and _match_pair(finding, item["left_terms"], item["right_terms"])
                ),
                None,
            )
            checks["needs_review"].append({
                "id": item["id"],
                "passed": matched is not None,
                "matched_finding": _finding_summary(matched) if matched else None,
            })
            print(("  PASS " if matched else "  MISS ") + item["id"] + " (needs review)")

        for item in expected["expected_no_conflict"]:
            flagged = next(
                (finding for finding in conflicts
                 if _match_pair(finding, item["left_terms"], item["right_terms"])),
                None,
            )
            checks["decoys"].append({
                "id": item["id"],
                "passed": flagged is None,
                "false_conflict": _finding_summary(flagged) if flagged else None,
            })
            print(("  PASS " if flagged is None else "  FALSE CONFLICT ") + item["id"] + " (decoy)")

        matched_finding_ids = set()
        for item in expected["expected_conflicts"]:
            matched = next(
                (
                    finding for finding in conflicts
                    if _match_pair(finding, item["left_terms"], item["right_terms"])
                    and finding.payload.finding_type.value == item["expected_finding_type"]
                ),
                None,
            )
            if matched is not None:
                matched_finding_ids.add(matched.payload.finding_id)
        for finding in conflicts:
            if finding.payload.finding_id in matched_finding_ids:
                continue
            checks["unexpected_conflicts"].append(_finding_summary(finding))
        if checks["unexpected_conflicts"]:
            print(f"\nUnexpected conflict findings: {len(checks['unexpected_conflicts'])}")
            for item in checks["unexpected_conflicts"]:
                print("  " + " || ".join(evidence["quote"] for evidence in item["evidence"])[:240])

        report["checks"] = checks
        report["summary"] = {
            "conflicts_matched": sum(item["passed"] for item in checks["conflicts"]),
            "conflicts_expected": len(checks["conflicts"]),
            "needs_review_matched": sum(item["passed"] for item in checks["needs_review"]),
            "needs_review_expected": len(checks["needs_review"]),
            "decoys_clean": sum(item["passed"] for item in checks["decoys"]),
            "decoys_expected": len(checks["decoys"]),
            "unexpected_conflicts": len(checks["unexpected_conflicts"]),
        }
        report["finished_at"] = datetime.now(timezone.utc).isoformat()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print("\nSummary:")
    print(f"  conflicts: {summary['conflicts_matched']}/{summary['conflicts_expected']}")
    print(f"  needs review: {summary['needs_review_matched']}/{summary['needs_review_expected']}")
    print(f"  decoys clean: {summary['decoys_clean']}/{summary['decoys_expected']}")
    print(f"  unexpected conflict findings: {summary['unexpected_conflicts']}")
    print(f"Report: {args.output}")

    if args.strict:
        complete = (
            summary["conflicts_matched"] == summary["conflicts_expected"]
            and summary["needs_review_matched"] == summary["needs_review_expected"]
            and summary["decoys_clean"] == summary["decoys_expected"]
            and summary["unexpected_conflicts"] == 0
        )
        return 0 if complete else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
