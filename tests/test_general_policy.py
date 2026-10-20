"""General policy integration and trust-boundary tests, with offline model doubles.

These verify the real parser/HTTP adapter/validation/publication pipeline. Semantic
responses are controlled fixtures, so passing them is not a model accuracy score.
"""

from dataclasses import replace
from datetime import datetime, timezone
import json
import re

import httpx
import pymupdf
import pytest
from pydantic import ValidationError

from meridian.contracts.common import Mode, PolicyScope, Subject
from meridian.contracts.extraction import ExtractionProposal, PolicyComparisonProposal
from meridian.contracts.manifest import SourceManifest
from meridian.contracts.qa import TargetFacts
from meridian.extraction.policy import POLICY_COMPARISON_VERSION, POLICY_EXTRACTION_VERSION
from meridian.extraction.provider import ProviderResult
from meridian.extraction.service import ModelStageService
from meridian.extraction.validate import ValidatorClause, validate_proposal
from meridian.ingestion.pipeline import ingest_prepared, prepare_pdf_source, prepare_slack_source
from meridian.rules.compare import ClaimView
from meridian.rules.general import classify_policy, comparison_request, rank_candidates, prepare_policy_comparisons
from meridian.rules.intervals import scope_intersection
from conftest import OfficeHarness, make_office

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
POLICY = "Employees must submit travel expenses within 30 days."
MESSAGE = "Employees may submit travel expenses within 60 days."


def manifest(identity="travel_policy", *, source_type="pdf", **changes):
    data = dict(
        tenant_id="meridian_demo", region="DHAKA", source_identity=identity,
        version_label="v1", source_type=source_type, subject="general_policy",
        authority="policy" if source_type == "pdf" else "informal",
        policy_family="travel" if source_type == "pdf" else "team_chat",
        scope={"kind": "policy", "description": "All employees", "attributes": {}},
        effective_from="2026-10-01T00:00:00Z" if source_type == "pdf" else None,
        effective_to=None, publication_time="2026-10-20T00:00:00Z",
        sensitivity="demo_shareable", permissions={"office_export": False, "hosted_model": True},
    )
    data.update(changes)
    return SourceManifest.model_validate(data)


def proposal(text, scope=None):
    return ExtractionProposal.model_validate({"rules": [{
        "subject": "general_policy", "scope": scope or manifest().scope.model_dump(),
        "rule": {
            "kind": "policy_statement", "statement": text, "modality": "assertion",
            "actor": None, "action": text, "object": None, "constraint": None,
            "applies_to": [], "conditions": [], "exceptions": [],
        }, "evidence": {"quote": text},
    }]})


def verdict(left, right, relationship="conflict", **changes):
    fields = dict(
        relationship=relationship, explanation="For the same employees and expense submission, the stated deadline differs.",
        left_quote=left, right_quote=right, same_action=True, scope_overlap=True,
        time_overlap=True, exceptions_resolved=True, evidence_sufficient=True,
    )
    fields.update(changes)
    return PolicyComparisonProposal(**fields)


def pdf(text):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=11)
        return document.tobytes()


def prepared(text, source_manifest):
    if source_manifest.source_type.value == "pdf":
        return prepare_pdf_source(source_manifest, pdf(text))
    raw = json.dumps({"channel": {"id": "CDEMO", "name": "demo"}, "event": {
        "text": text, "ts": "2026-10-20T00:00:00Z", "event_id": source_manifest.source_identity,
    }}).encode()
    return prepare_slack_source(source_manifest, raw)


def model_service(office, *, relationship="conflict", comparison_changes=None,
                  extraction_change=None, comparison_error=None, write_cache=False):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        user = body["messages"][1]["content"]
        name = body["response_format"]["json_schema"]["name"]
        if name == "policy_comparison":
            if comparison_error:
                return httpx.Response(comparison_error, json={"error": "unavailable"})
            lines = user.splitlines()
            left = re.search(r"(?ms)^\[left_primary [^\n]*\]\n(.*?)(?=\n\n\[)", user).group(1)
            right = re.search(r"(?ms)^\[right_primary [^\n]*\]\n(.*?)(?=\n\n\[)", user).group(1)
            output = verdict(left, right, relationship, **(comparison_changes or {})).model_dump(mode="json")
        else:
            start = next(i for i, line in enumerate(user.splitlines()) if line.startswith("[") and " | page " in line)
            text = "\n".join(user.splitlines()[start + 1:]).split("\n--- END UNTRUSTED SOURCE TEXT ---")[0].strip()
            scope = json.loads(user.split("\n")[1])
            output = proposal(text, scope).model_dump(mode="json")
            if extraction_change:
                extraction_change(output)
        return httpx.Response(200, json={
            "model": "offline-test-model", "usage": {"total_tokens": 25},
            "choices": [{"message": {"content": json.dumps(output)}}],
        })

    settings = replace(office.settings, llm_model="offline-test-model", llm_api_key="test-only",
                       fixtures_dir=office.base / "fixtures")
    service = ModelStageService(settings, transport=httpx.MockTransport(transport),
                                sleep=lambda _: None, write_cache=write_cache)
    return service, calls


def ingest(office, text, source_manifest, *, service, mode=Mode.LIVE):
    return ingest_prepared(office.store, prepared(text, source_manifest), mode=mode,
                           service=service, signer=office.signer, now=NOW)


def pair(office, *, service, policy=POLICY, message=MESSAGE, policy_manifest=None, message_manifest=None):
    first = ingest(office, policy, policy_manifest or manifest(), service=service)
    second = ingest(office, message, message_manifest or manifest("team_message", source_type="slack"), service=service)
    assert first.ok and second.ok, (first, second)
    return first, second


@pytest.mark.parametrize("changes", [
    {"subject": "loan_approval"}, {"scope": {"kind": "record"}},
    {"scope": {"kind": "policy", "description": " "}},
])
def test_general_manifest_rejects_incompatible_contracts(changes):
    with pytest.raises(ValidationError):
        manifest(**changes)


def test_general_policy_cannot_accidentally_enter_numeric_qa():
    with pytest.raises(ValidationError, match="ingestion/findings"):
        TargetFacts(subject="general_policy")


def test_travel_pdf_and_slack_produce_signed_review_candidate(dhaka):
    service, calls = model_service(dhaka)
    first, second = pair(dhaka, service=service)
    assert len(calls) == 3
    assert second.stage_modes == {"extraction": "live", "policy_comparison": "live"}
    findings = dhaka.store.list_findings()
    assert len(findings) == 1
    finding = findings[0]
    assert finding.payload.finding_type.value == "incorrect_guidance"
    assert finding.payload.severity.value == "review"
    assert finding.payload.explanation_code.value == "semantic_conflict"
    assert finding.payload.detail["requires_human_review"] == "true"
    assert {e.quote for e in finding.payload.evidence} == {POLICY, MESSAGE}
    assert finding.signature and finding.payload.evidence[0].manifest_root
    from meridian.integrity.canonical import canonical_json_bytes
    from meridian.integrity.signing import verify_signature
    assert verify_signature(canonical_json_bytes(finding.payload), finding.signature, dhaka.signer.public_key_hex)
    assert all(r.payload.scope.kind == "policy" for r in dhaka.store.claim_rows())
    message_claim = dhaka.store.claims_for_source(second.source_id)[0].payload
    assert message_claim.valid_from == NOW
    with dhaka.store.db.reader() as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 3
        assert connection.execute("SELECT alert FROM findings").fetchone()[0] == 0
    duplicate = ingest(dhaka, MESSAGE, manifest("team_message", source_type="slack"), service=service)
    assert duplicate.duplicate and len(calls) == 3


@pytest.mark.parametrize("policy,message", [
    ("Full-time employees are entitled to 25 days of annual leave.", "Full-time employees are entitled to only 20 days of annual leave."),
    ("Purchases above EUR 500 must receive manager approval.", "Purchases above EUR 500 may proceed without manager approval."),
    ("Employees must never send customer data to personal email accounts.", "Employees may send customer data to personal email accounts."),
    ("Visitors must wear an identification badge throughout their visit.", "Visitors may remove their identification badge during their visit."),
])
def test_multiple_subjects_run_the_same_pipeline(dhaka, policy, message):
    service, _ = model_service(dhaka)
    pair(dhaka, service=service, policy=policy, message=message)
    assert dhaka.store.list_findings()[0].payload.explanation_code.value == "semantic_conflict"


@pytest.mark.parametrize("changes", [
    {"scope_overlap": None}, {"time_overlap": None}, {"same_action": False},
    {"exceptions_resolved": False}, {"evidence_sufficient": False},
    {"left_quote": "Invented policy quotation."},
])
def test_uncertainty_or_hallucination_never_becomes_a_conflict(dhaka, changes):
    service, _ = model_service(dhaka, comparison_changes=changes)
    _, outcome = pair(dhaka, service=service)
    finding = dhaka.store.list_findings()[0].payload
    assert finding.finding_type.value == "needs_review"
    assert finding.severity.value == "review"
    assert outcome.review_reasons


def test_provider_failure_is_persisted_as_review_not_consistency(dhaka):
    service, _ = model_service(dhaka, comparison_error=503)
    _, outcome = pair(dhaka, service=service)
    assert outcome.ok and "policy_comparison_failed" in outcome.review_reasons
    finding = dhaka.store.list_findings()[0].payload
    assert finding.detail["error_code"] == "provider_error"


def test_missing_effective_date_requires_review_even_if_model_claims_conflict(dhaka):
    service, _ = model_service(dhaka)
    pair(dhaka, service=service, policy_manifest=manifest(effective_from=None))
    assert dhaka.store.list_findings()[0].payload.finding_type.value == "needs_review"


@pytest.mark.parametrize("policy,message", [
    ("Employees must submit expenses within 30 days. Overseas travel allows 60 days.", "Employees may submit overseas travel expenses within 60 days."),
    ("Employees must use passwords of at least 12 characters.", "Employees must use passwords of at least 16 characters."),
])
def test_compatible_rules_and_exceptions_do_not_create_findings(dhaka, policy, message):
    service, calls = model_service(dhaka, relationship="consistent")
    pair(dhaka, service=service, policy=policy, message=message)
    assert len(calls) == 3
    assert dhaka.store.list_findings() == []
    assert "Overseas" not in policy or "Overseas travel allows 60 days." in calls[-1]["messages"][1]["content"]


@pytest.mark.parametrize("boundary", ["scope", "time"])
def test_proven_disjoint_applicability_avoids_model_comparison(dhaka, boundary):
    service, calls = model_service(dhaka)
    if boundary == "scope":
        policy_manifest = manifest(scope={"kind": "policy", "description": "UK team", "attributes": {"country": "UK"}})
        message_manifest = manifest("team_message", source_type="slack", scope={"kind": "policy", "description": "BD team", "attributes": {"country": "BD"}})
    else:
        policy_manifest = manifest(effective_from="2026-11-01T00:00:00Z")
        message_manifest = manifest("team_message", source_type="slack", effective_to="2026-10-31T00:00:00Z")
    pair(dhaka, service=service, policy_manifest=policy_manifest, message_manifest=message_manifest)
    assert len(calls) == 2
    assert dhaka.store.list_findings() == []


def test_comparison_cannot_send_a_non_shareable_policy_to_hosted_model(dhaka):
    # Extract with an explicitly approved local endpoint first, then switch to hosted.
    service, calls = model_service(dhaka)
    events = []
    service.egress_sink = events.append
    local = ModelStageService(replace(service.settings, llm_base_url="http://127.0.0.1:9000/v1",
        llm_local_endpoint_approved=True), transport=service.live._transport)
    first = ingest(dhaka, POLICY, manifest(permissions={"office_export": False, "hosted_model": False}), service=local)
    assert first.ok
    second = ingest(dhaka, MESSAGE, manifest("team_message", source_type="slack"), service=service)
    assert second.ok
    assert len(calls) == 2  # policy extraction + message extraction, no comparison egress
    assert dhaka.store.list_findings()[0].payload.detail["error_code"] == "egress_denied"
    blocked = next(e for e in events if e["payload_type"] == "policy_comparison")
    assert blocked["outcome"] == "blocked" and blocked["raw_source_bytes"] == 0


@pytest.mark.parametrize("change", ["quote", "field", "scope"])
def test_ungrounded_extraction_is_not_accepted(dhaka, change):
    def modify(output):
        r = output["rules"][0]
        if change == "quote":
            r["evidence"]["quote"] = r["rule"]["statement"] = "An invented quotation is unsupported."
        elif change == "field":
            r["rule"]["actor"] = "Chief executive officer"
        else:
            r["scope"]["description"] = "Invented applicability"
    service, _ = model_service(dhaka, extraction_change=modify)
    outcome = ingest(dhaka, POLICY, manifest(), service=service)
    assert outcome.review_reasons or outcome.rejection_reasons
    assert dhaka.store.claim_rows() == []
    assert dhaka.store.list_findings() == []


def test_repeated_quote_resolves_page_hint_without_losing_offsets():
    p = proposal(POLICY)
    p.rules[0].evidence.page = 2
    result = validate_proposal(p, manifest=manifest(), manifest_root="root", clauses=[
        ValidatorClause("c1", 1, None, POLICY, "leaf1"),
        ValidatorClause("c2", 2, None, POLICY, "leaf2"),
    ])
    assert len(result.accepted) == 1
    assert result.accepted[0].evidence.clause_id == "c2"


def test_compact_hosted_policy_text_preserves_qualifications_and_rejects_inventions(dhaka):
    text = "Contractors must obtain approval before travel, except during an evacuation."

    def transport(request):
        body = json.loads(request.content)
        schema = body["response_format"]["json_schema"]["schema"]
        assert "actor" not in json.dumps(schema)
        assert "start_char" not in json.dumps(schema)
        output = {"rules": [{"scope": manifest().scope.model_dump(),
            "evidence": {"quote": text}, "modality": "required"}]}
        return httpx.Response(200, json={"model": "offline-test-model", "choices": [
            {"message": {"content": json.dumps(output)}}]})

    service = ModelStageService(replace(dhaka.settings, llm_model="offline-test-model",
        llm_api_key="test-only"), transport=httpx.MockTransport(transport))
    outcome = ingest(dhaka, text, manifest(), service=service)
    assert outcome.ok and not outcome.review_reasons
    claim = dhaka.store.claims_for_source(outcome.source_id)[0].payload
    assert claim.rule.statement == claim.rule.action == claim.evidence.quote == text
    assert claim.evidence.end_char > claim.evidence.start_char
    # Compact output still cannot turn a fabricated quotation into a claim.
    rejected = ingest(dhaka, "Contractors must obtain approval before travel.",
        manifest("other"), service=service)
    assert rejected.rejection_reasons
    assert dhaka.store.claims_for_source(rejected.source_id) == []


def test_compact_policy_output_cannot_assign_authority():
    from meridian.extraction.openrouter import OpenRouterExtractionProvider
    provider = OpenRouterExtractionProvider(base_url="http://localhost", model="test", api_key="test")
    output = {"rules": [{"scope": manifest().scope.model_dump(),
        "evidence": {"quote": POLICY}, "modality": "required", "authority": "policy"}]}
    parsed = provider._parse_response(json.dumps({"choices": [
        {"message": {"content": json.dumps(output)}}]}).encode())
    assert parsed[-1][0].value == "schema_violation"


def test_retrieval_ranks_relevant_policy_without_requiring_family_match(dhaka):
    service, _ = model_service(dhaka)
    ingest(dhaka, POLICY, manifest(), service=service)
    ingest(dhaka, "Employees must wear a badge inside the office building.", manifest("security", policy_family="security"), service=service)
    ingest(dhaka, MESSAGE, manifest("team_message", source_type="slack"), service=service)
    views = dhaka.store.claim_views(subject="general_policy")
    left = next(v for v in views if v.revision.source_identity == "team_message")
    candidates = [v for v in views if v != left]
    assert rank_candidates(left, candidates)[0].revision.source_identity == "travel_policy"


def test_comparison_stage_honors_cache_and_replay_modes(dhaka):
    service, calls = model_service(dhaka, write_cache=True)
    pair(dhaka, service=service)
    views = sorted(dhaka.store.claim_views(subject="general_policy"), key=lambda v: v.revision_id)
    request = comparison_request(*views, store=dhaka.store, manifest=manifest(), new_clauses=[], mode=Mode.CACHED, request_id="cache-test")
    hit = service.compare_policy(request)
    assert hit.ok and isinstance(hit.proposal, PolicyComparisonProposal)
    assert len(calls) == 3
    assert service.compare_policy(replace(request, content_sha256="changed")).error_code.value == "cache_miss"
    assert service.compare_policy(replace(request, mode=Mode.REPLAY)).error_code.value == "replay_fixture_missing"
    assert len(calls) == 3


def test_explicit_policy_replacement_is_not_a_new_conflict_and_retires_old_assessment(dhaka):
    service, calls = model_service(dhaka)
    first, second = pair(dhaka, service=service)
    old = dhaka.store.list_findings()[0]
    clause_id = dhaka.store.clauses_for_source(first.source_id)[0].clause_id
    scope = manifest().scope.model_dump()
    replacement = manifest(version_label="v2", effective_from="2026-10-15T00:00:00Z", supersedes={
        "supersedes_source_identity": "travel_policy", "supersedes_version_label": "v1",
        "replaced_clause_ids": [clause_id], "replaced_scope": scope,
        "effective_from": "2026-10-15T00:00:00Z",
    })
    outcome = ingest(dhaka, "Employees must submit travel expenses within 60 days.", replacement, service=service)
    assert outcome.ok
    findings = dhaka.store.list_findings()
    assert any(f.payload.finding_type.value == "supersession" for f in findings)
    reloaded = dhaka.store.get_finding(old.payload.finding_id)
    assert reloaded.payload.detail["assessment"] == "historical"
    assert reloaded.payload.severity.value == "info"
    assert reloaded.snapshot_id != old.snapshot_id
    assert not any(f.payload.finding_type.value == "contradiction" for f in findings)


def test_general_job_with_comparison_failure_finishes_needs_review(dhaka):
    from meridian.ingestion.worker import OfficeWorker
    service, _ = model_service(dhaka, comparison_error=503)
    _, outcome = pair(dhaka, service=service)
    source_manifest = manifest("team_message", source_type="slack")
    job = dhaka.store.create_job(kind="slack", mode=Mode.LIVE,
        request={"manifest": source_manifest.model_dump(mode="json")})
    worker = OfficeWorker(store=dhaka.store, settings=service.settings, signer=dhaka.signer)
    worker._finalise(job, outcome)
    assert dhaka.store.get_job(job.job_id).status == "needs_review"


def test_pair_limit_is_visible_and_does_not_silently_report_clean(dhaka):
    service, calls = model_service(dhaka)
    service.settings = replace(service.settings, policy_comparison_top_k=1)
    ingest(dhaka, POLICY, manifest(), service=service)
    ingest(dhaka, "Employees must wear an identification badge in the office.", manifest("badges"), service=service)
    outcome = ingest(dhaka, MESSAGE, manifest("team_message", source_type="slack"), service=service)
    assert "policy_retrieval_limited" in outcome.review_reasons
    assert any(r["reason_code"] == "policy_retrieval_limited" for r in dhaka.store.list_claim_reviews())


def test_global_pair_budget_prioritizes_relevance_over_extraction_order(dhaka):
    service, calls = model_service(dhaka, relationship="unrelated")
    ingest(dhaka, "The facilities team maintains the office directory.", manifest("directory"), service=service)
    ingest(dhaka, POLICY, manifest(), service=service)
    ingest(dhaka, MESSAGE, manifest("team_message", source_type="slack"), service=service)
    views = dhaka.store.claim_views(subject="general_policy", limit=None)
    revisions = [v.revision for v in sorted(views, key=lambda v: v.revision.source_identity != "directory")]
    service.settings = replace(service.settings, policy_comparison_max_pairs=1)
    calls.clear()
    for ordered in (revisions, list(reversed(revisions))):
        batch = prepare_policy_comparisons(dhaka.store, new_revisions=ordered,
            new_clauses=[], manifest=manifest(), service=service, mode=Mode.LIVE,
            request_id="global-priority", recheck=True)
        assert len(batch.calls) == 1
        request, _ = batch.calls[0]
        assert {c.text for c in request.clauses[:2]} == {POLICY, MESSAGE}
        assert "policy_comparison_limit" in {code for code, _ in batch.reviews}


def test_general_findings_are_readable_through_existing_ui_api(dhaka, monkeypatch):
    from meridian.ingestion.worker import OfficeWorker
    from meridian.office_api.main import OfficeRuntime, create_app
    from meridian.security.auth import Permission, Principal, PrincipalRegistry, Role
    service, _ = model_service(dhaka)
    pair(dhaka, service=service)
    runtime = OfficeRuntime(settings=dhaka.settings,
        registry=PrincipalRegistry.from_file(dhaka.settings.principals_path),
        trusted_keys=dhaka.registry, signer=dhaka.signer, store=dhaka.store,
        worker=OfficeWorker(store=dhaka.store, settings=service.settings, signer=dhaka.signer))
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(dhaka.settings)
    reader = Principal(principal_id="reader", tenant_id="meridian_demo", office="DHAKA",
        role=Role.READER, display_name="Reader", permissions=frozenset({Permission.READ_LOCAL}))
    endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/v1/findings")
    finding = endpoint(principal=reader)["findings"][0]
    assert finding["subject"] == "general_policy" and finding["alert"] is False
    detail = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/v1/findings/{finding_id}")
    assert detail(finding["finding_id"], principal=reader)["finding"]["payload"]["affected_scope"]["kind"] == "policy"
    recheck = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/v1/sources/{source_id}/comparisons")
    uploader = Principal(principal_id="uploader", tenant_id="meridian_demo", office="DHAKA",
        role=Role.UPLOADER, display_name="Uploader", permissions=frozenset({Permission.READ_LOCAL, Permission.INGEST}))
    source_id = finding["evidence"][0]["source_id"]
    queued = recheck(source_id, mode="replay", principal=uploader)
    assert queued["job"]["kind"] == "policy_comparison"
    assert dhaka.store.get_job(queued["job"]["job_id"]).request["source_id"] == source_id


def test_explicit_retry_recovers_a_failed_comparison_without_reupload(dhaka):
    from meridian.rules.general import recompare_policy_source
    failed_service, _ = model_service(dhaka, comparison_error=503)
    _, outcome = pair(dhaka, service=failed_service)
    old = dhaka.store.list_findings()[0]
    healthy, calls = model_service(dhaka)
    retried = recompare_policy_source(dhaka.store, outcome.source_id, service=healthy,
        signer=dhaka.signer, mode=Mode.LIVE, request_id="recheck")
    assert retried.ok and retried.review_reasons == []
    assert len(calls) == 1  # no repeated extraction
    findings = dhaka.store.list_findings()
    assert any(f.payload.explanation_code.value == "semantic_conflict" for f in findings)
    assert dhaka.store.get_finding(old.payload.finding_id).payload.detail["assessment"] == "historical"


def test_retry_can_withdraw_a_candidate_when_model_finds_an_exception(dhaka):
    from meridian.rules.general import recompare_policy_source
    service, _ = model_service(dhaka)
    _, outcome = pair(dhaka, service=service)
    old = dhaka.store.list_findings()[0]
    consistent, _ = model_service(dhaka, relationship="consistent")
    retried = recompare_policy_source(dhaka.store, outcome.source_id, service=consistent,
        signer=dhaka.signer, mode=Mode.LIVE, request_id="recheck")
    assert retried.ok
    reloaded = dhaka.store.get_finding(old.payload.finding_id)
    assert reloaded.payload.detail["assessment"] == "historical" and reloaded.payload.severity.value == "info"


def test_retry_worker_uses_durable_job_without_staged_upload(dhaka):
    from meridian.ingestion.worker import OfficeWorker
    service, _ = model_service(dhaka)
    _, outcome = pair(dhaka, service=service)
    job = dhaka.store.create_job(kind="policy_comparison", mode=Mode.LIVE,
        request={"source_id": outcome.source_id})
    worker = OfficeWorker(store=dhaka.store, settings=service.settings, signer=dhaka.signer,
                          transport=service.live._transport)
    result = worker.process_job(job)
    assert result.ok and dhaka.store.get_job(job.job_id).status == "succeeded"


def test_message_without_a_policy_reports_missing_reference(dhaka):
    service, _ = model_service(dhaka)
    outcome = ingest(dhaka, MESSAGE, manifest("team_message", source_type="slack"), service=service)
    assert "policy_reference_missing" in outcome.review_reasons


def test_general_policy_evaluation_corpus_runs_the_real_pipeline_offline(tmp_path):
    from scripts.evaluate_general_policy import CORPUS, evaluate_case
    for case in json.loads(CORPUS.read_text())["cases"]:
        result = evaluate_case(case, tmp_path / case["id"])
        assert result["passed"], result


def test_wrapped_deadlines_are_not_parsed_as_section_headings():
    from meridian.ingestion.pdf import parse_pdf_bytes
    text = "Employees must submit overseas travel expenses within\n60 days."
    document = parse_pdf_bytes(pdf(text))
    assert len(document.clauses) == 1
    assert document.clauses[0].section is None
    assert "within\n60 days." in document.clauses[0].text


def test_failed_general_extraction_does_not_hide_its_job_behind_a_missing_source(dhaka):
    from meridian.ingestion.pipeline import IngestionOutcome
    from meridian.ingestion.worker import OfficeWorker
    job = dhaka.store.create_job(kind="pdf", mode=Mode.LIVE,
        request={"manifest": manifest().model_dump(mode="json")})
    outcome = IngestionOutcome(source_id="not_committed", error_code="missing_credentials")
    worker = OfficeWorker(store=dhaka.store, settings=dhaka.settings, signer=dhaka.signer)
    worker._finalise(job, outcome)
    stored = dhaka.store.get_job(job.job_id)
    assert stored.status == "failed" and stored.source_id is None


def test_multiple_review_claims_in_one_passage_have_distinct_signed_ids(dhaka, monkeypatch):
    statements = [
        "Employees must submit travel claims within 30 days.",
        "Overseas staff may use the deadline in Appendix C.",
        "Remote staff may use the allowance in Appendix D.",
    ]
    source_manifest = manifest("review_identity_regression")
    source = prepared("\n".join(statements), source_manifest)
    assert len(source.parsed.clauses) == 1
    rules = []
    for i, statement in enumerate(statements):
        data = proposal(statement, source_manifest.scope.model_dump()).rules[0].model_dump(mode="json")
        if i:
            data.update(ambiguous=True, ambiguous_reason="The referenced appendix was not supplied.")
        rules.append(data)
    output = ExtractionProposal.model_validate({"rules": rules})
    monkeypatch.setattr(dhaka.service, "extract", lambda request: ProviderResult(
        mode=Mode.REPLAY, provider="offline-regression", proposal=output))
    result = ingest_prepared(dhaka.store, source, mode=Mode.REPLAY, service=dhaka.service,
                             signer=dhaka.signer, now=NOW)
    assert result.ok, result.error_detail
    claims = dhaka.store.claims_for_source(result.source_id)
    assert len(claims) == 3
    assert len({c.payload.revision_id for c in claims}) == 3
    assert len({c.payload.claim_id for c in claims}) == 3
    assert len({c.payload.source_clause_id for c in claims}) == 1
    assert sorted(c.payload.status.value for c in claims) == ["accepted", "needs_review", "needs_review"]
    assert {c.payload.evidence.quote for c in claims} == set(statements)
    from meridian.integrity.canonical import canonical_json_bytes
    from meridian.integrity.signing import verify_signature
    for claim in claims:
        assert verify_signature(canonical_json_bytes(claim.payload), claim.signature, dhaka.signer.public_key_hex)
    with dhaka.store.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM claim_reviews WHERE source_id=? AND reason_code='ambiguous_proposal'", (result.source_id,)).fetchone()[0] == 2
    duplicate = ingest_prepared(dhaka.store, source, mode=Mode.REPLAY, service=dhaka.service,
                                signer=dhaka.signer, now=NOW)
    assert duplicate.duplicate and duplicate.source_id == result.source_id
    assert len(dhaka.store.claims_for_source(result.source_id)) == 3


@pytest.mark.parametrize("relationship", ["consistent", "unrelated"])
def test_clearly_different_actions_do_not_create_spurious_context_reviews(dhaka, relationship):
    service, _ = model_service(dhaka, relationship=relationship, comparison_changes={
        "same_action": False, "scope_overlap": None, "time_overlap": None,
        "exceptions_resolved": False, "evidence_sufficient": True,
    })
    _, outcome = pair(dhaka, service=service,
        policy="Visitors must wear identification badges inside the office.",
        message="Employees must use passwords of at least 12 characters.")
    assert dhaka.store.list_findings() == []
    assert "insufficient_context" not in outcome.review_reasons


def test_consistency_with_unknown_exception_still_requires_review(dhaka):
    service, _ = model_service(dhaka, relationship="consistent", comparison_changes={
        "same_action": True, "exceptions_resolved": False,
    })
    _, outcome = pair(dhaka, service=service)
    assert "insufficient_context" in outcome.review_reasons
    assert dhaka.store.list_findings()[0].payload.finding_type.value == "needs_review"
