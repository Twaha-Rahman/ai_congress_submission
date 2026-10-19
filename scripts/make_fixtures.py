"""Generate synthetic demo sources, manifests and offline extraction fixtures.

The generator writes PDFs and a saved Slack event, parses them with the *real*
parser, and only then writes replay proposals whose evidence quotes are asserted to
exist in the parsed clause text.  Regenerating fixtures is therefore the only way to
change replay content, and stale proposals cannot silently survive a text edit.

Run:  .venv/bin/python scripts/make_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from meridian.contracts.common import (  # noqa: E402
    Authority,
    Currency,
    LoanType,
    OfficeRegion,
    Product,
    RecordClass,
    RuleKind,
    Sensitivity,
    SourceType,
    StartingEvent,
    Subject,
    UnitKind,
)
from meridian.contracts.extraction import (  # noqa: E402
    EvidenceSpan,
    ExtractionProposal,
    ProposedRule,
)
from meridian.contracts.manifest import (  # noqa: E402
    SourceManifest,
    SourcePermissions,
    SupersessionClaim,
)
from meridian.ingestion.pdf import parse_pdf_bytes  # noqa: E402
from meridian.ingestion.slack import parse_slack_payload, slack_to_document  # noqa: E402
from meridian.integrity.canonical import sha256_hex  # noqa: E402

FIXTURES = ROOT / "fixtures"
DOCUMENTS = FIXTURES / "documents"
MANIFESTS = FIXTURES / "manifests"
SLACK = FIXTURES / "slack"
REPLAY = FIXTURES / "replay"
TAMPERED = FIXTURES / "tampered"
TENANT = "meridian_demo"
PROMPT_VERSION = "extract-v1"


def amount_interval(lower: int | None, lower_inclusive: bool, upper: int | None, upper_inclusive: bool):
    from meridian.contracts.common import AmountInterval

    return AmountInterval(
        lower=lower,
        lower_inclusive=lower_inclusive,
        upper=upper,
        upper_inclusive=upper_inclusive,
    )


def loan_scope(lower: int | None, lower_inclusive: bool, upper: int | None, upper_inclusive: bool):
    from meridian.contracts.common import AmountScope

    return AmountScope(
        loan_type=LoanType.BUSINESS,
        currency=Currency.USD,
        origin_office=OfficeRegion.DHAKA,
        amount_minor=amount_interval(lower, lower_inclusive, upper, upper_inclusive),
    )


def record_scope(origin: OfficeRegion = OfficeRegion.DHAKA, processing: OfficeRegion = OfficeRegion.FRANKFURT):
    from meridian.contracts.common import RecordScope

    return RecordScope(
        record_class=RecordClass.LOAN_RECORDS,
        origin_office=origin,
        processing_office=processing,
        product=Product.MTF_CROSS_OFFICE,
        starting_event=StartingEvent.LOAN_CLOSURE,
    )


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def make_pdf(path: Path, title: str, sections: list[tuple[str, str, str]]) -> bytes:
    """Render a text PDF: (section number, heading, one-line clause sentence)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes()
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    y = 72.0
    page.insert_text((72, y), title, fontsize=14, fontname="helv")
    y += 32
    for number, heading, sentence in sections:
        page.insert_text((72, y), f"{number} {heading}", fontsize=11, fontname="hebo")
        y += 18
        page.insert_text((72, y), sentence, fontsize=9, fontname="helv")
        y += 28
    document.save(str(path))
    document.close()
    return path.read_bytes()


def proposal(rules: list[ProposedRule], *, notes: str | None = None) -> ExtractionProposal:
    return ExtractionProposal(rules=rules, notes=notes)


def rule(
    *,
    subject: Subject,
    scope,
    kind: RuleKind,
    unit: UnitKind,
    value,
    quote: str,
    page: int = 1,
) -> ProposedRule:
    return ProposedRule(
        subject=subject,
        scope=scope,
        rule={"kind": kind.value, "unit": unit.value, "value": value},
        evidence=EvidenceSpan(page=page, quote=quote),
    )


def write_manifest(name: str, manifest: SourceManifest) -> Path:
    path = MANIFESTS / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def write_replay(
    *,
    region: str,
    source_identity: str,
    version_label: str,
    content_sha256: str,
    proposal_model: ExtractionProposal,
) -> Path:
    path = REPLAY / region.lower() / f"{source_identity}__{version_label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "region": region,
        "source_identity": source_identity,
        "version_label": version_label,
        "content_sha256": content_sha256,
        "prompt_version": PROMPT_VERSION,
        "model_metadata": {
            "provider": "synthetic-replay-fixture",
            "model": "synthetic-fixture-v1",
            "route": "offline-replay",
            "attempts": 1,
            "latency_ms": 0,
        },
        "proposal": proposal_model.model_dump(mode="json"),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def assert_quotes(parsed, quotes: list[str]) -> None:
    texts = [clause.text for clause in parsed.clauses]
    for quote in quotes:
        if not any(quote in text for text in texts):
            raise SystemExit(
                "fixture quote is not present verbatim in parsed clause text; "
                f"refusing to write a stale replay proposal:\n  {quote!r}\n"
                "parsed clauses:\n" + "\n---\n".join(texts)
            )


def build_pdf_source(
    *,
    region: str,
    filename: str,
    title: str,
    sections: list[tuple[str, str, str]],
    manifest: SourceManifest,
    proposal_model: ExtractionProposal,
    quotes: list[str],
) -> None:
    raw = make_pdf(DOCUMENTS / region.lower() / filename, title, sections)
    parsed = parse_pdf_bytes(raw)
    assert_quotes(parsed, quotes)
    content_sha = sha256_hex(parsed.normalized_text().encode("utf-8"))
    write_manifest(filename.replace(".pdf", ""), manifest)
    if region.upper() == "DHAKA":
        write_replay(
            region="DHAKA",
            source_identity=manifest.source_identity,
            version_label=manifest.version_label,
            content_sha256=content_sha,
            proposal_model=proposal_model,
        )
    else:
        write_replay(
            region="FRANKFURT",
            source_identity=manifest.source_identity,
            version_label=manifest.version_label,
            content_sha256=content_sha,
            proposal_model=proposal_model,
        )
    print(f"  [{region}] {filename}: {len(parsed.clauses)} clauses, content {content_sha[:12]}…")


def main() -> None:
    for directory in (DOCUMENTS, MANIFESTS, SLACK, REPLAY, TAMPERED):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(REPLAY / "dhaka", ignore_errors=True)
    shutil.rmtree(REPLAY / "frankfurt", ignore_errors=True)

    print("Generating Dhaka lending policy v2 …")
    v2_sentence_large = (
        "A business loan in USD with an amount greater than USD 50,000 requires at "
        "least two approvals from the credit committee."
    )
    v2_sentence_small = (
        "A business loan in USD with an amount of USD 50,000 or less requires at "
        "least one approval from the credit committee."
    )
    v2_manifest = SourceManifest(
        tenant_id=TENANT,
        region=OfficeRegion.DHAKA,
        source_identity="dhaka_lending_policy",
        version_label="v2",
        source_type=SourceType.PDF,
        subject=Subject.LOAN_APPROVAL,
        authority=Authority.POLICY,
        policy_family="dha_retail_lending",
        scope=loan_scope(0, True, None, False),
        effective_from=utc("2026-01-01T00:00:00Z"),
        effective_to=None,
        publication_time=utc("2025-12-15T00:00:00Z"),
        sensitivity=Sensitivity.DEMO_SHAREABLE,
        permissions=SourcePermissions(office_export=True, hosted_model=True),
    )
    build_pdf_source(
        region="DHAKA",
        filename="dhaka_lending_policy_v2.pdf",
        title="Dhaka Retail Lending Policy — version 2",
        sections=[
            ("4.1", "Large business loans", v2_sentence_large),
            ("4.2", "Small business loans", v2_sentence_small),
        ],
        manifest=v2_manifest,
        proposal_model=proposal(
            [
                rule(
                    subject=Subject.LOAN_APPROVAL,
                    scope=loan_scope(5_000_000, False, None, False),
                    kind=RuleKind.REQUIRED_MINIMUM,
                    unit=UnitKind.APPROVALS,
                    value=2,
                    quote=v2_sentence_large,
                ),
                rule(
                    subject=Subject.LOAN_APPROVAL,
                    scope=loan_scope(0, False, 5_000_000, True),
                    kind=RuleKind.REQUIRED_MINIMUM,
                    unit=UnitKind.APPROVALS,
                    value=1,
                    quote=v2_sentence_small,
                ),
            ],
            notes="Synthetic fixture for the Dhaka lending policy v2 demonstration.",
        ),
        quotes=[v2_sentence_large, v2_sentence_small],
    )

    print("Generating Dhaka lending policy v3 (explicit supersession) …")
    v3_sentence_large = (
        "A business loan in USD with an amount greater than USD 25,000 requires at "
        "least two approvals from the credit committee."
    )
    v3_sentence_small = (
        "A business loan in USD with an amount of USD 25,000 or less requires at "
        "least one approval from the credit committee."
    )
    v3_manifest = SourceManifest(
        tenant_id=TENANT,
        region=OfficeRegion.DHAKA,
        source_identity="dhaka_lending_policy",
        version_label="v3",
        source_type=SourceType.PDF,
        subject=Subject.LOAN_APPROVAL,
        authority=Authority.POLICY,
        policy_family="dha_retail_lending",
        scope=loan_scope(0, True, None, False),
        effective_from=utc("2026-02-01T00:00:00Z"),
        effective_to=None,
        publication_time=utc("2026-01-20T00:00:00Z"),
        sensitivity=Sensitivity.DEMO_SHAREABLE,
        permissions=SourcePermissions(office_export=True, hosted_model=True),
        supersedes=SupersessionClaim(
            supersedes_source_identity="dhaka_lending_policy",
            supersedes_version_label="v2",
            replaced_clause_ids=[
                "dhaka_lending_policy:v2:4.1",
                "dhaka_lending_policy:v2:4.2",
            ],
            replaced_scope=loan_scope(0, True, None, False),
            effective_from=utc("2026-02-01T00:00:00Z"),
        ),
    )
    build_pdf_source(
        region="DHAKA",
        filename="dhaka_lending_policy_v3.pdf",
        title="Dhaka Retail Lending Policy — version 3",
        sections=[
            ("4.1", "Large business loans", v3_sentence_large),
            ("4.2", "Small business loans", v3_sentence_small),
        ],
        manifest=v3_manifest,
        proposal_model=proposal(
            [
                rule(
                    subject=Subject.LOAN_APPROVAL,
                    scope=loan_scope(2_500_000, False, None, False),
                    kind=RuleKind.REQUIRED_MINIMUM,
                    unit=UnitKind.APPROVALS,
                    value=2,
                    quote=v3_sentence_large,
                ),
                rule(
                    subject=Subject.LOAN_APPROVAL,
                    scope=loan_scope(0, False, 2_500_000, True),
                    kind=RuleKind.REQUIRED_MINIMUM,
                    unit=UnitKind.APPROVALS,
                    value=1,
                    quote=v3_sentence_small,
                ),
            ],
            notes="Synthetic fixture for the Dhaka lending policy v3 demonstration.",
        ),
        quotes=[v3_sentence_large, v3_sentence_small],
    )

    print("Generating the stale Slack guidance event …")
    slack_payload = {
        "channel": {"id": "C_DHA_CREDIT", "name": "dhaka-credit-policy"},
        "event": {
            "type": "message",
            "event_id": "Ev_DEMO_STALE_GUIDANCE",
            "ts": "2026-03-03T09:15:00Z",
            "user": "U_DHA_CREDIT_OPS",
            "user_name": "Dhaka Credit Operations",
            "text": (
                "For our USD business loans up to 50k, one approval is sufficient. "
                "You do not need a second sign-off."
            ),
        },
    }
    slack_path = SLACK / "dhaka_credit_update_2026_03_03.json"
    slack_path.write_text(
        json.dumps(slack_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    slack_raw = slack_path.read_bytes()
    slack_parsed = slack_to_document(parse_slack_payload(slack_raw))
    slack_quote = slack_payload["event"]["text"]
    assert_quotes(slack_parsed, [slack_quote])
    slack_manifest = SourceManifest(
        tenant_id=TENANT,
        region=OfficeRegion.DHAKA,
        source_identity="dha_slack_credit_channel",
        version_label="2026-03-03",
        source_type=SourceType.SLACK,
        subject=Subject.LOAN_APPROVAL,
        authority=Authority.INFORMAL,
        policy_family="dha_retail_lending",
        scope=loan_scope(None, True, 5_000_000, True),
        effective_from=utc("2026-03-03T09:15:00Z"),
        effective_to=None,
        publication_time=utc("2026-03-03T09:15:00Z"),
        sensitivity=Sensitivity.DEMO_SHAREABLE,
        permissions=SourcePermissions(office_export=True, hosted_model=True),
    )
    write_manifest("dhaka_credit_update_2026_03_03", slack_manifest)
    write_replay(
        region="DHAKA",
        source_identity=slack_manifest.source_identity,
        version_label=slack_manifest.version_label,
        content_sha256=sha256_hex(slack_parsed.normalized_text().encode("utf-8")),
        proposal_model=proposal(
            [
                rule(
                    subject=Subject.LOAN_APPROVAL,
                    scope=loan_scope(None, True, 5_000_000, True),
                    kind=RuleKind.ADVISED_SUFFICIENT,
                    unit=UnitKind.APPROVALS,
                    value=1,
                    quote=slack_quote,
                )
            ],
            notes="Synthetic saved Slack event; treated as informal guidance, not authority.",
        ),
    )
    print("  [DHAKA] Slack saved event: 1 clause, guidance proposal written")

    print("Generating the Dhaka records procedure (border demo) …")
    dhaka_procedure_sentence = "Delete these records after exactly five years from loan closure."
    dhaka_procedure_manifest = SourceManifest(
        tenant_id=TENANT,
        region=OfficeRegion.DHAKA,
        source_identity="dhaka_records_procedure",
        version_label="v1",
        source_type=SourceType.PDF,
        subject=Subject.RECORD_RETENTION,
        authority=Authority.PROCEDURE,
        policy_family="dha_records_ops",
        scope=record_scope(),
        effective_from=utc("2026-01-01T00:00:00Z"),
        effective_to=None,
        publication_time=utc("2025-12-20T00:00:00Z"),
        sensitivity=Sensitivity.DEMO_SHAREABLE,
        permissions=SourcePermissions(office_export=True, hosted_model=True),
    )
    build_pdf_source(
        region="DHAKA",
        filename="dhaka_records_procedure_v1.pdf",
        title="Dhaka Records Operations Procedure — version 1",
        sections=[("2.3", "Record deletion", dhaka_procedure_sentence)],
        manifest=dhaka_procedure_manifest,
        proposal_model=proposal(
            [
                rule(
                    subject=Subject.RECORD_RETENTION,
                    scope=record_scope(),
                    kind=RuleKind.OPERATING_EXACT,
                    unit=UnitKind.YEARS,
                    value="5",
                    quote=dhaka_procedure_sentence,
                )
            ],
            notes="Planned operating procedure; actual deletion was not observed.",
        ),
        quotes=[dhaka_procedure_sentence],
    )

    print("Generating the Frankfurt records policy (border demo) …")
    frankfurt_sentence = "These records must be retained for at least seven years from loan closure."
    frankfurt_manifest = SourceManifest(
        tenant_id=TENANT,
        region=OfficeRegion.FRANKFURT,
        source_identity="frankfurt_records_policy",
        version_label="v1",
        source_type=SourceType.PDF,
        subject=Subject.RECORD_RETENTION,
        authority=Authority.POLICY,
        policy_family="frb_records_policy",
        scope=record_scope(),
        effective_from=utc("2026-01-01T00:00:00Z"),
        effective_to=None,
        publication_time=utc("2025-12-18T00:00:00Z"),
        sensitivity=Sensitivity.DEMO_SHAREABLE,
        permissions=SourcePermissions(office_export=True, hosted_model=True),
    )
    build_pdf_source(
        region="FRANKFURT",
        filename="frankfurt_records_policy_v1.pdf",
        title="Frankfurt Records Retention Policy — version 1",
        sections=[("7.2", "Cross-office loan records", frankfurt_sentence)],
        manifest=frankfurt_manifest,
        proposal_model=proposal(
            [
                rule(
                    subject=Subject.RECORD_RETENTION,
                    scope=record_scope(),
                    kind=RuleKind.REQUIRED_MINIMUM,
                    unit=UnitKind.YEARS,
                    value="7",
                    quote=frankfurt_sentence,
                )
            ],
            notes="Frankfurt requirement; comparison happens at Frankfurt after import.",
        ),
        quotes=[frankfurt_sentence],
    )

    print("Generating the restricted Dhaka credit note (blocked export demo) …")
    restricted_sentence = (
        "Business loans above USD 1,000,000 require at least three approvals from "
        "the credit committee."
    )
    restricted_manifest = SourceManifest(
        tenant_id=TENANT,
        region=OfficeRegion.DHAKA,
        source_identity="dhaka_credit_note_restricted",
        version_label="v1",
        source_type=SourceType.PDF,
        subject=Subject.LOAN_APPROVAL,
        authority=Authority.POLICY,
        policy_family="dha_credit_committee",
        scope=loan_scope(100_000_000, False, None, False),
        effective_from=utc("2026-01-01T00:00:00Z"),
        effective_to=None,
        publication_time=utc("2026-01-05T00:00:00Z"),
        sensitivity=Sensitivity.RESTRICTED,
        permissions=SourcePermissions(office_export=False, hosted_model=True),
    )
    build_pdf_source(
        region="DHAKA",
        filename="dhaka_credit_note_restricted_v1.pdf",
        title="Dhaka Credit Committee Note — restricted",
        sections=[("1.1", "High-value approvals", restricted_sentence)],
        manifest=restricted_manifest,
        proposal_model=proposal(
            [
                rule(
                    subject=Subject.LOAN_APPROVAL,
                    scope=loan_scope(100_000_000, False, None, False),
                    kind=RuleKind.REQUIRED_MINIMUM,
                    unit=UnitKind.APPROVALS,
                    value=3,
                    quote=restricted_sentence,
                )
            ],
            notes="Restricted source: local processing only, never exported.",
        ),
        quotes=[restricted_sentence],
    )

    print("Generating tampered copies of lending policy v3 …")
    original = DOCUMENTS / "dhaka" / "dhaka_lending_policy_v3.pdf"
    metadata_copy = TAMPERED / "dhaka_lending_policy_v3_metadata_only.pdf"
    document = pymupdf.open(str(original))
    metadata = dict(document.metadata or {})
    metadata["title"] = "Dhaka Retail Lending Policy — metadata altered for demo"
    document.set_metadata(metadata)
    document.save(str(metadata_copy))
    document.close()

    content_copy = TAMPERED / "dhaka_lending_policy_v3_modified_text.pdf"
    make_pdf(
        content_copy,
        "Dhaka Retail Lending Policy — version 3",
        [
            ("4.1", "Large business loans", v3_sentence_large),
            (
                "4.2",
                "Small business loans",
                "A business loan in USD with an amount of USD 25,000 or less requires at "
                "least four approvals from the credit committee.",
            ),
        ],
    )
    print("  tampered copies written")

    plan = {
        "tenant_id": TENANT,
        "scenario_time": "2026-03-03T12:00:00Z",
        "sources": [
            {
                "region": "DHAKA",
                "kind": "pdf",
                "file": "documents/dhaka/dhaka_lending_policy_v2.pdf",
                "manifest": "manifests/dhaka_lending_policy_v2.json",
            },
            {
                "region": "DHAKA",
                "kind": "pdf",
                "file": "documents/dhaka/dhaka_lending_policy_v3.pdf",
                "manifest": "manifests/dhaka_lending_policy_v3.json",
            },
            {
                "region": "DHAKA",
                "kind": "pdf",
                "file": "documents/dhaka/dhaka_records_procedure_v1.pdf",
                "manifest": "manifests/dhaka_records_procedure_v1.json",
            },
            {
                "region": "DHAKA",
                "kind": "pdf",
                "file": "documents/dhaka/dhaka_credit_note_restricted_v1.pdf",
                "manifest": "manifests/dhaka_credit_note_restricted_v1.json",
            },
            {
                "region": "FRANKFURT",
                "kind": "pdf",
                "file": "documents/frankfurt/frankfurt_records_policy_v1.pdf",
                "manifest": "manifests/frankfurt_records_policy_v1.json",
            },
        ],
        "demo1_slack": {
            "file": "slack/dhaka_credit_update_2026_03_03.json",
            "manifest": "manifests/dhaka_credit_update_2026_03_03.json",
        },
        "tampered": {
            "metadata_only": "tampered/dhaka_lending_policy_v3_metadata_only.pdf",
            "modified_text": "tampered/dhaka_lending_policy_v3_modified_text.pdf",
        },
    }
    (FIXTURES / "demo_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("Wrote fixtures/demo_plan.json")


if __name__ == "__main__":
    main()
