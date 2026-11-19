"""Offline checks for the Northwind conflict-test fixtures.

These tests do not call a model. They keep the PDFs at two pages and ensure the
manifests and expected-result file still describe the same, comparable documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from meridian.contracts.manifest import SourceManifest
from meridian.ingestion.pdf import parse_pdf_bytes

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "conflict_testing"
DOCUMENTS = {
    "northwind_employee_handbook_2026": [
        "3.1 Employees must submit travel claims within 30 calendar days of returning.",
        "3.2 Employees may submit travel claims up to 60 calendar days after returning.",
        "3.4 Employees may claim economy-class airfare only; premium cabins are not reimbursable.",
        "4.1 Full-time employees are entitled to 25 working days of annual leave each year.",
        "4.2 Full-time employees are entitled to at most 20 working days of annual leave each year.",
    ],
    "northwind_security_procurement_procedure_2026": [
        "2.1 Employees may book premium economy airfare at company expense for all business flights.",
        "3.1 Employees must never send customer data to personal email accounts.",
        "3.2 Employees may send customer data to personal email accounts when working remotely.",
        "4.1 Purchases above EUR 500 require written approval from the employee's manager.",
        "4.2 Purchases up to EUR 2,000 may be ordered by any employee without prior approval.",
    ],
}


def test_conflict_test_documents_are_two_text_pages():
    for source_identity, statements in DOCUMENTS.items():
        path = FIXTURES / f"{source_identity}.pdf"
        with pymupdf.open(path) as document:
            assert document.page_count == 2
        parsed = parse_pdf_bytes(path.read_bytes())
        assert parsed.page_count == 2
        text = "\n".join(clause.text for clause in parsed.clauses)
        for statement in statements:
            assert statement in text


def test_conflict_test_manifests_are_comparable():
    manifests = []
    for source_identity in DOCUMENTS:
        manifest = SourceManifest.model_validate_json(
            (FIXTURES / "manifests" / f"{source_identity}.json").read_text(encoding="utf-8")
        )
        manifests.append(manifest)

    assert manifests[0].scope == manifests[1].scope
    assert manifests[0].effective_from == manifests[1].effective_from
    assert manifests[0].permissions.hosted_model is True
    assert manifests[1].permissions.hosted_model is True
    assert [manifest.authority.value for manifest in manifests] == ["policy", "procedure"]


def test_expected_findings_cover_conflicts_review_and_decoys():
    expected = json.loads((FIXTURES / "expected_findings.json").read_text(encoding="utf-8"))
    conflict_ids = {item["id"] for item in expected["expected_conflicts"]}
    assert conflict_ids == {
        "travel_claim_deadline",
        "annual_leave_entitlement",
        "personal_email_customer_data",
        "purchase_approval_threshold",
        "cross_document_airfare_class",
    }
    assert {item["expected_finding_type"] for item in expected["expected_conflicts"]} == {
        "contradiction",
        "compliance_gap",
    }
    assert expected["expected_needs_review"][0]["expected_finding_type"] == "needs_review"
    assert len(expected["expected_no_conflict"]) >= 4
    for item in expected["expected_conflicts"] + expected["expected_no_conflict"]:
        assert item["left_terms"] and item["right_terms"]
