"""Source Q&A integration checks. Model doubles test grounding, not model accuracy."""
import asyncio
import json
import re
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from meridian.api_common import ApiError
from meridian.contracts.common import CheckStatus, Mode
from meridian.contracts.qa import QueryRequest
from meridian.integrity.bundles import verify_bundle
from meridian.queries.evidence import build_bundle
from meridian.queries.general import GeneralQuestionEngine, SourceAnswerProvider, quote_span, PROMPT_VERSION
from meridian.queries.lineage import lineage_for_node
from test_general_policy import NOW, POLICY, ingest, manifest, model_service


def seed(office, text=POLICY, *, source_manifest=None, no_claims=False):
    def uncertain(output):
        for rule in output["rules"]:
            rule.update(ambiguous=True, ambiguous_reason="Applicability needs human review")
    service, _ = model_service(office, extraction_change=uncertain if no_claims else None)
    if source_manifest and not source_manifest.permissions.hosted_model:
        service.settings = replace(service.settings, llm_local_endpoint_approved=True, llm_base_url="http://127.0.0.1:9000/v1")
    result = ingest(office, text, source_manifest or manifest(), service=service)
    assert result.ok
    return result.source_id


def engine(office, responder=None, **changes):
    calls = []
    def transport(request):
        body = json.loads(request.content); calls.append(body)
        user = body["messages"][1]["content"]
        quote = re.search(r"\[P1 \|[^\n]+\]\n(.*?)(?=\n\n\[P|\n--- END)", user, re.S).group(1)
        result = responder(body, quote) if responder else {
            "status": "answered", "statements": [{"text": "Submit travel expenses within 30 days.",
                "citations": [{"passage_id": "P1", "quote": quote}]}], "limitations": []}
        return httpx.Response(200, json={"model": "offline-question-model", "usage": {"total_tokens": 25},
            "choices": [{"message": {"content": json.dumps(result)}}]})
    settings = replace(office.settings, llm_model="offline-question-model", llm_api_key="test-only", **changes)
    provider = SourceAnswerProvider(base_url=settings.llm_base_url, model=settings.llm_model, api_key=settings.llm_api_key,
        transport=httpx.MockTransport(transport), sleep=lambda _: None)
    return GeneralQuestionEngine(store=office.store, signer=office.signer, settings=settings, provider=provider), calls


def question(**changes):
    return QueryRequest(question="When should employees submit travel expenses?", valid_at=NOW, known_at=NOW + timedelta(days=1), **changes)


def verify(office, bundle):
    return verify_bundle(bundle, registry=office.registry, tenant_id=office.store.tenant_id)


def test_pdf_wrap_normalization_preserves_verbatim_citations_and_rejects_changed_words(dhaka):
    text = "The procurement team reviews open orders every Monday and publishes a monthly spend\nsummary for budget owners."
    quote = text.replace("\n", " ")
    span = quote_span(text, quote)
    assert text[slice(*span)] == text
    assert quote_span(text, quote.replace("Monday", "Friday")) is None
    assert quote_span("same phrase\nsame phrase", "same phrase") is None
    seed(dhaka, text)
    qa, _ = engine(dhaka, lambda body, actual: {"status": "answered", "statements": [{"text": "The team reviews orders every Monday.",
        "citations": [{"passage_id": "P1", "quote": re.sub(r"\s+", " ", actual)}]}], "limitations": []})
    answer = qa.answer(question())
    assert answer.payload.status.value == "answered"
    citation = answer.payload.citations[0]
    assert citation.quote in dhaka.store.get_clause(citation.clause_id).text
    assert not verify(dhaka, build_bundle(dhaka.store, answer)).any_failed()


def test_arbitrary_source_question_uses_original_passages_without_extracted_claims(dhaka):
    source_id = seed(dhaka, no_claims=True)
    assert not dhaka.store.claim_rows()
    qa, calls = engine(dhaka)
    answer = qa.answer(question(source_ids=[source_id]))
    assert answer.payload.status.value == "answered"
    assert "30 days" in answer.payload.answer_text
    citation = answer.payload.citations[0]
    assert citation.claim_revision_id is None and citation.claim_payload_hash is None
    clause = dhaka.store.get_clause(citation.clause_id)
    assert clause.text[citation.start_char:citation.end_char] == citation.quote
    assert calls[0]["response_format"]["json_schema"]["name"] == "source_answer"
    assert question().question in calls[0]["messages"][1]["content"]
    graph = lineage_for_node(dhaka.store, f"answer:{answer.payload.answer_id}", allowed_restricted=False)
    assert any(edge.to_node_id == f"clause:{citation.clause_id}" for edge in graph.edges)
    assert dhaka.store.get_answer(answer.payload.answer_id).payload == answer.payload
    with dhaka.store.db.reader() as connection:
        assert connection.execute("select count(*) from model_calls where prompt_version=?", (PROMPT_VERSION,)).fetchone()[0] == 1
    assert dhaka.store.egress_events()[0].payload_type == "source_question"


def test_direct_passage_bundles_verify_and_reject_tampered_text_locators_and_authority(dhaka):
    seed(dhaka)
    qa, _ = engine(dhaka)
    bundle = build_bundle(dhaka.store, qa.answer(question()))
    report = verify(dhaka, bundle)
    assert not report.any_failed(), report
    assert report.summary()["answer_binding"] == "passed"
    assert report.summary()["clause_inclusion"] == "passed"
    assert report.summary()["claim_binding"] == "not_checked"  # no invented extraction claim
    for field, value in [("quote", "invented"), ("page", 9), ("authority", "informal"), ("start_char", 999), ("remote", True)]:
        changed = bundle.model_copy(deep=True)
        setattr(changed.answer.citations[0], field, value)
        assert verify(dhaka, changed).summary()["answer_binding"] == "failed", field
    changed = bundle.model_copy(deep=True)
    changed.manifests[0].clauses[0].text += "tampered"
    assert verify(dhaka, changed).summary()["clause_inclusion"] == "failed"
    changed = bundle.model_copy(deep=True)
    changed.manifests[0].clauses = []
    assert verify(dhaka, changed).summary()["answer_binding"] == "not_checked"


@pytest.mark.parametrize("reference", [{"passage_id": "foreign", "quote": POLICY}, {"passage_id": "P1", "quote": "You have 90 days."}])
def test_unknown_or_hallucinated_evidence_discards_the_answer(dhaka, reference):
    seed(dhaka)
    qa, _ = engine(dhaka, lambda body, quote: {"status": "answered", "statements": [{"text": "You have 90 days.", "citations": [reference]}], "limitations": []})
    result = qa.answer(question()).payload
    assert result.status.value == "abstained" and not result.citations
    assert "90 days" not in result.answer_text
    assert "discarded" in result.warnings[0].message


def test_reader_access_hosted_permissions_and_source_filters_precede_retrieval(dhaka):
    public = seed(dhaka)
    secret = seed(dhaka, "The classified vault code is ZEBRA77. Only the security team may disclose this information.", source_manifest=manifest("secret", sensitivity="restricted"))
    blocked = seed(dhaka, "Software purchases need procurement approval.", source_manifest=manifest("local_only", permissions={"office_export": False, "hosted_model": False}))
    qa, calls = engine(dhaka)
    result = qa.answer(question())
    assert POLICY in calls[0]["messages"][1]["content"]
    assert "ZEBRA77" not in str(calls) and "classified" not in str(calls)
    assert "Software purchases" not in str(calls)
    assert result.payload.status.value == "partial"
    for invalid in [secret, "src_missing"]:
        with pytest.raises(ApiError) as error:
            qa.answer(question(source_ids=[invalid]))
        assert error.value.code.value == "not_found"
    calls.clear()
    empty = qa.answer(question(source_ids=[blocked]))
    assert empty.payload.status.value == "abstained" and not calls
    selected = qa.answer(question(source_ids=[public]))
    assert {citation.source_id for citation in selected.payload.citations} == {public}
    local, local_calls = engine(dhaka, llm_local_endpoint_approved=True, llm_base_url="http://127.0.0.1:9000/v1")
    local.answer(question(source_ids=[blocked]), allowed_restricted=True)
    assert "Software purchases" in str(local_calls)


def test_dates_exclude_unavailable_sources_without_a_model_call(dhaka):
    seed(dhaka)
    qa, calls = engine(dhaka)
    request = QueryRequest(question="Expenses?", valid_at=NOW - timedelta(days=30), known_at=NOW + timedelta(days=1))
    assert qa.answer(request).payload.status.value == "abstained"
    request = QueryRequest(question="Expenses?", valid_at=NOW, known_at=NOW - timedelta(days=1))
    assert qa.answer(request).payload.status.value == "abstained"
    assert not calls
    with pytest.raises(ApiError, match="no live fallback"):
        qa.answer(question(mode=Mode.REPLAY))


def test_general_retrieval_preserves_effective_and_knowledge_time_supersession(dhaka_full):
    from conftest import T_KNOWN, T_VALID, T_POLICY_V2
    qa, calls = engine(dhaka_full)
    old = dhaka_full.store.find_source_version("dhaka_lending_policy", "v2")
    old_rule = dhaka_full.store.claims_for_source(old.source_id)[0].payload.source_clause_id
    current = QueryRequest(question="Which approvals are needed?", source_ids=[old.source_id], valid_at=T_VALID, known_at=T_KNOWN)
    passages, _, _ = qa.retrieve(current, moment=T_KNOWN, allowed_restricted=False)
    assert old_rule not in {passage.clause.clause_id for passage in passages}
    # Before learning the replacement, that same future applicability date used
    # the old knowledge snapshot; do not backdate the later replacement.
    prior = current.model_copy(update={"known_at": T_POLICY_V2 + timedelta(days=1)})
    passages, _, _ = qa.retrieve(prior, moment=prior.known_at, allowed_restricted=False)
    assert old_rule in {passage.clause.clause_id for passage in passages}
    assert not calls


def test_model_abstention_and_timeout_do_not_become_fake_answers(dhaka):
    seed(dhaka)
    qa, _ = engine(dhaka, lambda body, quote: {"status": "abstained", "statements": [], "limitations": ["The source does not name the approver."]})
    result = qa.answer(question()).payload
    assert result.status.value == "abstained" and not result.citations
    assert "does not name" in result.warnings[0].message
    def timeout(request):
        raise httpx.ReadTimeout("offline test timeout", request=request)
    qa.provider._transport = httpx.MockTransport(timeout)
    qa.provider.max_attempts = 1
    with pytest.raises(ApiError) as error:
        qa.answer(question())
    assert error.value.code.value == "provider_timeout"


def test_a_source_note_does_not_demote_an_otherwise_complete_answer(dhaka):
    seed(dhaka)
    qa, _ = engine(dhaka, lambda body, quote: {"status": "answered", "statements": [{"text": "Submit expenses within 30 days.",
        "citations": [{"passage_id": "P1", "quote": quote}]}], "limitations": ["This is stated in the travel procedure."]})
    result = qa.answer(question()).payload
    assert result.status.value == "answered" and result.warnings and not result.partial_reasons


def test_local_query_api_routes_natural_language_and_reauthorizes_saved_answers(dhaka, monkeypatch):
    from meridian.ingestion.worker import OfficeWorker
    from meridian.office_api.main import OfficeRuntime, create_app
    from meridian.security.auth import Principal, PrincipalRegistry, Permission, Role
    public = seed(dhaka, source_manifest=manifest("travel_expenses"))
    secret = seed(dhaka, source_manifest=manifest(sensitivity="restricted"))
    qa, _ = engine(dhaka)
    monkeypatch.setattr("meridian.queries.general.SourceAnswerProvider", lambda **kwargs: qa.provider)
    runtime = OfficeRuntime(settings=qa.settings, registry=PrincipalRegistry.from_file(dhaka.settings.principals_path),
        trusted_keys=dhaka.registry, signer=dhaka.signer, store=dhaka.store,
        worker=OfficeWorker(store=dhaka.store, settings=dhaka.settings, signer=dhaka.signer))
    monkeypatch.setattr("meridian.office_api.main.build_runtime", lambda _settings=None: runtime)
    app = create_app(dhaka.settings)
    route = lambda path: next(r.endpoint for r in app.routes if getattr(r, "path", None) == path)
    reader = Principal("reader", "meridian_demo", "DHAKA", Role.READER, frozenset({Permission.READ_LOCAL, Permission.QUERY_LOCAL}), "Reader")
    reviewer = replace(reader, permissions=reader.permissions | {Permission.READ_RESTRICTED})
    class Request:
        async def json(self):
            return question(source_ids=[public, secret]).model_dump(mode="json")
    response = asyncio.run(route("/v1/queries")(Request(), principal=reviewer))
    assert response["answer"]["target"]["subject"] == "general_policy"
    assert {citation["source_id"] for citation in response["answer"]["citations"]} == {public}
    assert response["lineage"]["nodes"]
    with pytest.raises(ApiError):
        route("/v1/answers/{answer_id}")(response["answer"]["answer_id"], principal=reader)
    assert route("/v1/answers")(limit=50, principal=reader)["answers"] == []
    graph = lineage_for_node(dhaka.store, f"answer:{response['answer']['answer_id']}", allowed_restricted=False)
    assert not graph.nodes
    class PublicRequest:
        async def json(self):
            return question(source_ids=[public]).model_dump(mode="json")
    reader_answer = asyncio.run(route("/v1/queries")(PublicRequest(), principal=reader))
    assert route("/v1/answers/{answer_id}")(reader_answer["answer"]["answer_id"], principal=reader)["answer"]["answer_id"]
