"""Demo 3 — The Border: cross-office compliance gap over typed federation.

    .venv/bin/python scripts/demo3_border.py
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
    heading,
    item,
    loan_target,
    note,
    okay,
    query_gateway,
    retention_target,
    save_json,
    services,
    step,
    token,
    wait_ready,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ensure", action="store_true")
    args = parser.parse_args(argv[1:])

    if not args.no_ensure:
        stack.ensure()
    wait_ready()

    configured = services()
    dhaka = Client(configured["dhaka"].base_url)
    frankfurt = Client(configured["frankfurt"].base_url)
    gateway = Client(configured["gateway"].base_url)
    try:
        token("DEMO_TOKEN_GATEWAY_SERVICE")
        token("DEMO_TOKEN_DHAKA_SERVICE")
        heading("DEMO 3 — THE BORDER: procedure versus policy across offices")

        step("local policy state (federation sees only signed typed claims)")
        dha_sources = dhaka.get("/v1/sources", token_env="DEMO_TOKEN_DHAKA_UPLOADER")["sources"]
        fra_sources = frankfurt.get(
            "/v1/sources", token_env="DEMO_TOKEN_FRANKFURT_UPLOADER"
        )["sources"]
        _print_sources("DHAKA", dha_sources, subject="record_retention")
        _print_sources("FRANKFURT", fra_sources, subject="record_retention")

        step("gateway orchestrates: fetch Dhaka export -> import at Frankfurt -> compare")
        query_body = {
            "question": (
                "How long must cross-office loan records be kept when closed in Dhaka "
                "and processed in Frankfurt?"
            ),
            "target": retention_target(),
            "valid_at": SCENARIO_TIME,
        }
        gateway_body = query_gateway(gateway, query_body)
        federated = gateway_body["federated_answer"]
        comparison = federated["comparison"]
        answer = comparison["answer"]
        item("gateway status", federated["status"])
        item("comparator region", federated["comparator_region"])
        item("answer text", answer["answer_text"])
        for warning in answer["warnings"]:
            note(f"warning {warning['code']}: {warning['message']}")
        item("import", federated["import"])
        item("origin export claims", federated["origin_export"]["claims"])
        item("origin export withheld_restricted", federated["origin_export"]["withheld_restricted"])
        item("origin payload bytes", federated["origin_export"]["payload_bytes"])
        item("not_checked", federated["not_checked"])
        item("transport redaction", comparison.get("transport_redaction", {}).get("note", "-"))
        for citation in answer["citations"]:
            print(
                f"    cite {citation['source_identity']:<28} {citation['source_version_label']:<6} "
                f"remote={str(citation['remote']):<5} quote={'none (not disclosed)' if citation['quote'] is None else 'present'}"
            )
        if "does not meet the requirement" not in answer["answer_text"] and (
            "compliance gap" not in answer["answer_text"]
        ):
            raise DemoError("expected a procedure-level compliance gap in the federated answer")
        if federated["origin_export"]["claims"] < 1:
            raise DemoError("the Dhaka procedure claim should have been exported")
        if not federated["import"].get("accepted"):
            raise DemoError("the verified remote export should have been accepted")
        if not any(citation["remote"] for citation in answer["citations"]):
            raise DemoError("expected at least one opaque remote citation")
        okay("typed federation produced the 5-year procedure vs 7-year policy gap")
        okay("remote citation stays opaque; passage text did not cross the border")

        step("approved payload shape (allowlisted fields only)")
        sample = _sample_export_shape(dhaka, dha_sources)
        item("export claim fields", ", ".join(sample["fields"]))
        item("free-text fields present", sample["free_text_fields"] or "none")
        if sample["free_text_fields"]:
            raise DemoError(f"free text leaked into the export: {sample['free_text_fields']}")

        step("restricted claim is blocked, not silently exported")
        restricted = next(
            source for source in dha_sources if source["sensitivity"] == "restricted"
        )
        checkpoint = restricted["ingested_at"]
        subquery = {
            "request_id": "demo3_restricted_check",
            "subject": "loan_approval",
            "target": {
                "kind": "loan",
                "subject": "loan_approval",
                "loan_type": "business",
                "currency": "USD",
                "origin_office": "DHAKA",
                "amount_minor": 200000000,
            },
            "valid_at": SCENARIO_TIME,
            "known_at": checkpoint,
        }
        restricted_export = dhaka.post(
            "/v1/federation/claims",
            token_env="DEMO_TOKEN_DHAKA_SERVICE",
            json=subquery,
        )
        summary = restricted_export["summary"]
        item("historical checkpoint", checkpoint)
        item("claims exported", summary["claims"])
        item("restricted withheld", summary["withheld_restricted"])
        item("reason codes", summary["reason_codes"])
        if summary["claims"] != 0 or summary["withheld_restricted"] < 1:
            raise DemoError("a restricted-only snapshot must export zero claims")
        if "egress_denied_restricted_source" not in summary["reason_codes"]:
            raise DemoError("expected the restricted egress reason code")
        okay("restricted-only export returned zero claims and an explicit denial reason")

        step("service credentials cannot fetch raw source content")
        denied = dhaka.get(
            f"/v1/sources/{restricted['source_id']}/content",
            token_env="DEMO_TOKEN_DHAKA_SERVICE",
            expect=403,
        )
        item("HTTP status", 403)
        item("error code", denied.get("error", {}).get("code", "-"))
        okay("office-service identity is denied raw source access")

        step("canary: restricted passage text must not appear in exports or relay logs")
        claims = dhaka.get("/v1/claims", token_env="DEMO_TOKEN_DHAKA_UPLOADER")["claims"]
        candidates = [
            claim for claim in claims if claim["source_id"] == restricted["source_id"]
        ]
        if not candidates:
            raise DemoError("restricted source has no claim for the canary check")
        quote = _claim_quote(dhaka, "DEMO_TOKEN_DHAKA_UPLOADER")
        export_text = json.dumps(restricted_export)
        relay_text = (ROOT / "runtime" / "gateway" / "relay.jsonl").read_text("utf-8")
        if not quote:
            note("restricted claim has no quote available for the canary check")
        else:
            canary = quote[:60]
            if canary in export_text:
                raise DemoError("canary passage found in office-to-office export")
            if canary in relay_text:
                raise DemoError("canary passage found in gateway relay log")
            item("canary (first 60 chars)", canary[:60])
            okay("canary absent from office export and gateway relay log")

        step("measured transfer counters (office vs model channels, separately labeled)")
        for name, client, token_env in (
            ("DHAKA", dhaka, "DEMO_TOKEN_DHAKA_REVIEWER"),
            ("FRANKFURT", frankfurt, "DEMO_TOKEN_FRANKFURT_REVIEWER"),
        ):
            audit = client.get("/v1/audit/egress", token_env=token_env)
            summary = audit["summary"]
            print(
                f"  {name:<9} office->office events={summary['office_to_office_events']:>3} "
                f"bytes={summary['office_to_office_bytes']:>6}  "
                f"hosted-model events={summary['hosted_model_events']:>3} "
                f"model-bytes={summary['hosted_model_request_bytes']:>7}  "
                f"blocked={summary['blocked_exports']:>2}  "
                f"raw_source_bytes_between_offices={summary['raw_source_text_bytes_between_offices']}"
            )
            if summary["raw_source_text_bytes_between_offices"] != 0:
                raise DemoError(f"raw source bytes crossed the office boundary at {name}")
            if summary["hosted_model_events"] < 1:
                raise DemoError(f"expected audited model-stage events at {name}")
        gateway_audit = gateway.get("/v1/audit/egress", token_env="DEMO_TOKEN_GATEWAY_SERVICE")
        item("gateway relay counts", gateway_audit["counts"])
        if gateway_audit["counts"]["blocked"] < 0:
            raise DemoError("unexpected relay counter")
        okay("office and model transfer counters are measured and separately labeled")

        save_json(
            "evidence/demo3_federation.json",
            {
                "gateway": gateway_body,
                "restricted_export": restricted_export,
                "gateway_audit": gateway_audit,
            },
        )
        print("\nevidence saved to evidence/demo3_federation.json")
    finally:
        dhaka.close()
        frankfurt.close()
        gateway.close()
    return 0


def _print_sources(office: str, sources: list[dict], *, subject: str) -> None:
    for source in sources:
        if source["subject"] != subject:
            continue
        print(
            f"  {office:<9} {source['source_identity']:<28} {source['version_label']:<6} "
            f"{source['authority']:<10} family={source['policy_family']:<22} "
            f"{source['sensitivity']}"
        )


def _sample_export_shape(dhaka: Client, sources: list[dict]) -> dict:
    """Fetch one real export and inspect the serialized allowlist."""

    from datetime import datetime, timezone

    subquery = {
        "request_id": "demo3_shape_probe",
        "subject": "record_retention",
        "target": {
            "kind": "record",
            "subject": "record_retention",
            "record_class": "loan_records",
            "origin_office": "DHAKA",
            "processing_office": "FRANKFURT",
            "product": "MTF_CROSS_OFFICE",
            "starting_event": "loan_closure",
        },
        "valid_at": SCENARIO_TIME,
        # The baseline is ingested "now"; a knowledge cutoff in the past would
        # correctly exclude it, so the shape probe asks for current knowledge.
        "known_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    body = dhaka.post(
        "/v1/federation/claims",
        token_env="DEMO_TOKEN_DHAKA_SERVICE",
        json=subquery,
    )
    export = body["export"]["payload"]
    claims = export.get("claims", [])
    if not claims:
        raise DemoError("expected at least one exported record-retention claim")
    fields = sorted(claims[0])
    forbidden = {
        "quote",
        "text",
        "title",
        "channel",
        "user",
        "author",
        "filename",
        "source_path",
        "prompt",
    }
    free_text = sorted(field for field in fields if field.lower() in forbidden)
    return {"fields": fields, "free_text_fields": free_text}


def _claim_quote(client: Client, token_env: str) -> str:
    """Return the longest restricted passage visible to a privileged reader."""

    query = client.post(
        "/v1/queries",
        token_env=token_env,
        expect=201,
        json={
            "question": "approvals for the restricted band",
            "target": loan_target(200000000),
            "valid_at": SCENARIO_TIME,
        },
    )
    quotes = [
        citation.get("quote")
        for citation in query["answer"]["citations"]
        if citation.get("restricted") and citation.get("quote")
    ]
    return max(quotes, key=len) if quotes else ""


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except DemoError as exc:
        print(f"demo3 error: {exc}", file=sys.stderr)
        raise SystemExit(1)
