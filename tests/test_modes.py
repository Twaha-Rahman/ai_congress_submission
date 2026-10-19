"""Explicit stage modes: missing credentials, cache misses and missing replay data."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx

from meridian.contracts.common import Mode, PROMPT_VERSION, SCHEMA_VERSION
from meridian.contracts.extraction import ExtractionProposal
from meridian.extraction.cache import CachedExtractionProvider
from meridian.extraction.openrouter import OpenRouterExtractionProvider
from meridian.extraction.provider import (
    ClauseInput,
    ExtractionRequest,
    ProviderPrerequisiteError,
)
from meridian.extraction.replay import ReplayExtractionProvider
from meridian.extraction.service import ModelStageService
from meridian.ingestion.pipeline import clause_id_for

from conftest import (
    DEMO_POLICY_V3,
    FIXTURES,
    OfficeHarness,
    make_office,
)


def _request(harness: OfficeHarness, *, version_label: str = "v3", mode: Mode = Mode.REPLAY) -> ExtractionRequest:
    prepared = harness.prepare(*DEMO_POLICY_V3)
    manifest = prepared.manifest
    clauses = [
        ClauseInput(
            clause_id=clause_id_for(manifest, index, clause.section),
            page=clause.page,
            section=clause.section,
            text=clause.text,
        )
        for index, clause in enumerate(prepared.parsed.clauses)
    ]
    return ExtractionRequest(
        tenant_id=manifest.tenant_id,
        region=manifest.region.value,
        source_identity=manifest.source_identity,
        version_label=version_label,
        source_type=manifest.source_type,
        subject=manifest.subject,
        authority=manifest.authority.value,
        content_sha256=prepared.content_sha256,
        manifest_scope_summary=manifest.scope.model_dump_json(),
        clauses=clauses,
        mode=mode,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        request_id="req_mode_test",
    )


def test_live_mode_without_credentials_fails_visibly(dhaka: OfficeHarness) -> None:
    request = _request(dhaka, mode=Mode.LIVE)
    result = dhaka.service.extract(request)
    assert result.proposal is None
    assert result.error_code is not None
    assert result.error_code.value == "missing_credentials"
    assert result.mode is Mode.LIVE
    assert "llm_model" in (result.error_detail or "").lower()
    assert "not attempted" in (result.error_detail or "").lower()


def test_missing_replay_fixture_is_reported_not_substituted(dhaka: OfficeHarness) -> None:
    request = _request(dhaka, version_label="v99")
    result = dhaka.service.extract(request)
    assert result.proposal is None
    assert result.error_code is not None
    assert result.error_code.value == "replay_fixture_missing"
    assert "v99" in (result.error_detail or "")


def test_cached_mode_hit_and_miss_are_explicit(
    dhaka: OfficeHarness, tmp_path: Path
) -> None:
    request = _request(dhaka)
    replay = ReplayExtractionProvider(FIXTURES / "replay" / "dhaka").extract(request)
    assert replay.ok

    fixtures_dir = tmp_path / "cached_fixtures"
    cache = CachedExtractionProvider(fixtures_dir / "cache" / "dhaka")
    key = dhaka.service.cache_key_for(request)
    cache.write(
        key,
        replay,
        model_metadata={
            "provider": "synthetic-cache",
            "route": "offline-replay",
            "model": replay.model,
            "attempts": 1,
            "latency_ms": 0,
            "usage": {},
            "note": "test cache entry built from a replay proposal",
        },
        created_at=__import__("datetime").datetime.now().astimezone(),
    )

    cached_office = make_office(tmp_path / "cached_office", fixtures_dir=fixtures_dir)
    cached_request = replace(request, mode=Mode.CACHED)
    hit = cached_office.service.extract(cached_request)
    assert hit.ok
    assert hit.proposal is not None
    assert hit.mode is Mode.CACHED
    assert hit.cache_key == key
    assert hit.provider == "cache"

    miss = cached_office.service.extract(
        replace(request, mode=Mode.CACHED, version_label="v3-uncached")
    )
    assert miss.proposal is None
    assert miss.error_code is not None
    assert miss.error_code.value == "cache_miss"

    # Any runtime configuration change is part of the key: it cannot reuse a hit.
    reconfigured = make_office(
        tmp_path / "reconfigured",
        fixtures_dir=fixtures_dir,
        llm_temperature=0.7,
    )
    assert reconfigured.service.cache_key_for(request) != key
    assert reconfigured.service.extract(cached_request).error_code.value == "cache_miss"


def test_live_result_is_never_written_unless_explicitly_requested(
    dhaka: OfficeHarness,
) -> None:
    service = ModelStageService(dhaka.settings, write_cache=False)
    assert service.write_cache is False


def _valid_proposal(harness: OfficeHarness) -> ExtractionProposal:
    result = ReplayExtractionProvider(FIXTURES / "replay" / "dhaka").extract(
        _request(harness)
    )
    assert result.proposal is not None
    return result.proposal


def _live_provider(handler, *, max_attempts: int = 1) -> OpenRouterExtractionProvider:
    return OpenRouterExtractionProvider(
        base_url="https://openrouter.test/api/v1",
        model="test/model",
        api_key="test-key",
        timeout_seconds=1.0,
        max_attempts=max_attempts,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def _completion(content: str, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "model": "test/model-2026",
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            "choices": [{"message": {"content": content}}],
        },
    )


def test_fake_transport_success_records_model_route_and_usage(
    dhaka: OfficeHarness,
) -> None:
    proposal = _valid_proposal(dhaka)
    provider = _live_provider(
        lambda _request: _completion(proposal.model_dump_json())
    )
    result = provider.extract(_request(dhaka, mode=Mode.LIVE))

    assert result.ok
    assert result.proposal == proposal
    assert result.mode is Mode.LIVE
    assert result.attempts == 1
    assert result.usage == {"prompt_tokens": 11, "completion_tokens": 7}
    assert result.model == "test/model-2026"
    assert result.request_bytes > 0
    assert len(result.raw_output_sha256 or "") == 64


def test_fake_transport_malformed_json_is_a_visible_provider_error(
    dhaka: OfficeHarness,
) -> None:
    provider = _live_provider(
        lambda _request: httpx.Response(200, content=b"this is not json")
    )
    result = provider.extract(_request(dhaka, mode=Mode.LIVE))
    assert result.proposal is None
    assert result.error_code is not None
    assert result.error_code.value == "provider_error"
    assert "not JSON" in (result.error_detail or "")


def test_fake_transport_schema_violation_is_not_silently_accepted(
    dhaka: OfficeHarness,
) -> None:
    invalid = json.dumps({"rules": [{"subject": "loan_approval"}]})
    provider = _live_provider(lambda _request: _completion(invalid))
    result = provider.extract(_request(dhaka, mode=Mode.LIVE))
    assert result.proposal is None
    assert result.error_code is not None
    assert result.error_code.value == "schema_violation"
    assert "did not match the schema" in (result.error_detail or "")


def test_fake_transport_timeout_is_reported(dhaka: OfficeHarness) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _live_provider(handler)
    result = provider.extract(_request(dhaka, mode=Mode.LIVE))
    assert result.proposal is None
    assert result.error_code is not None
    assert result.error_code.value == "provider_timeout"


def test_fake_transport_transient_failure_retries_without_fallback(
    dhaka: OfficeHarness,
) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": "unavailable"})

    provider = _live_provider(handler, max_attempts=2)
    result = provider.extract(_request(dhaka, mode=Mode.LIVE))
    assert result.proposal is None
    assert result.error_code is not None
    assert result.error_code.value == "provider_error"
    assert result.attempts == 2
    assert len(calls) == 2


def test_fake_transport_hallucinated_quote_reaches_the_real_validator(
    dhaka: OfficeHarness,
) -> None:
    proposal = _valid_proposal(dhaka)
    proposal.rules[0].evidence.quote = "An invented sentence that is not in the PDF."
    provider = _live_provider(
        lambda _request: _completion(proposal.model_dump_json())
    )
    result = provider.extract(_request(dhaka, mode=Mode.LIVE))
    assert result.ok  # schema-valid: the adapter does not pretend to validate evidence

    prepared = dhaka.prepare(*DEMO_POLICY_V3)
    # Exercise the same validator the ingestion pipeline calls.
    from meridian.extraction.validate import ValidatorClause, validate_proposal

    validation = validate_proposal(
        proposal,
        manifest=prepared.manifest,
        clauses=[
            ValidatorClause(
                clause_id=f"clause:test:{index}",
                page=clause.page,
                section=clause.section,
                text=clause.text,
                leaf_hash="ab" * 32,
            )
            for index, clause in enumerate(prepared.parsed.clauses)
        ],
        manifest_root="cd" * 32,
    )
    # The invented quote is rejected; the untouched second rule still validates.
    assert len(validation.accepted) == 1
    assert [item.reason_code for item in validation.rejections] == [
        "hallucinated_evidence"
    ]
