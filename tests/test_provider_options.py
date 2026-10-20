"""Routing allowlists and reasoning controls use the same options in every stage."""
from dataclasses import replace

import pytest

from meridian.config import OfficeSettings
from meridian.contracts.common import Mode, Subject
from meridian.extraction.openrouter import OpenRouterExtractionProvider
from meridian.extraction.policy import PolicyComparisonProvider
from meridian.extraction.provider import ClauseInput, ExtractionRequest
from meridian.extraction.service import ModelStageService


def request():
    return ExtractionRequest(
        tenant_id="test", region="DHAKA", source_identity="policy", version_label="v1",
        source_type="pdf", subject=Subject.GENERAL_POLICY, authority="policy",
        content_sha256="0" * 64,
        manifest_scope_summary='{"kind":"policy","description":"All employees","attributes":{}}',
        clauses=[ClauseInput("clause:test", 1, None, "Employees must submit claims within 30 days.")],
        mode=Mode.LIVE, prompt_version="general-extract-v1", schema_version="1", request_id="test",
    )


@pytest.mark.parametrize("preferences,expected", [
    ("order=deepinfra,together", {"order": ["deepinfra", "together"]}),
    ("order=deepseek|cloudflare,allow_fallbacks=false", {"order": ["deepseek", "cloudflare"], "allow_fallbacks": False}),
    ("only=deepseek, cloudflare, order=deepseek,cloudflare,require_parameters=true", {
        "only": ["deepseek", "cloudflare"], "order": ["deepseek", "cloudflare"], "require_parameters": True}),
    ("ignore=deepinfra,together,sort=latency", {"ignore": ["deepinfra", "together"], "sort": "latency"}),
])
def test_provider_lists_preserve_every_provider(preferences, expected):
    provider = OpenRouterExtractionProvider(base_url="https://openrouter.test", model="test", api_key="test",
                                            provider_preferences=preferences)
    assert provider._provider_routing() == expected


def test_reasoning_and_provider_restrictions_reach_every_request():
    options = dict(base_url="https://openrouter.test", model="test", api_key="test",
                   reasoning_effort="none", provider_preferences="only=deepseek,cloudflare,require_parameters=true")
    general = request()
    numeric = replace(general, subject=Subject.LOAN_APPROVAL)
    for provider, req in [(OpenRouterExtractionProvider(**options), numeric),
                          (OpenRouterExtractionProvider(**options), general),
                          (PolicyComparisonProvider(**options), general)]:
        body = provider.build_body(req)
        assert body["reasoning"] == {"effort": "none"}
        assert body["provider"]["only"] == ["deepseek", "cloudflare"]
        assert body["provider"]["require_parameters"] is True


def test_reasoning_configuration_and_cache_identity(dhaka, monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    monkeypatch.setenv("DHAKA_LLM_REASONING_EFFORT", "low")
    assert OfficeSettings.from_env("DHAKA").llm_reasoning_effort == "low"
    assert OfficeSettings.from_env("FRANKFURT").llm_reasoning_effort == "none"
    plain = ModelStageService(replace(dhaka.settings, llm_reasoning_effort=None))
    disabled = ModelStageService(replace(dhaka.settings, llm_reasoning_effort="none"))
    low = ModelStageService(replace(dhaka.settings, llm_reasoning_effort="low"))
    assert "reasoning" not in plain.live.build_body(request())
    assert disabled.live.reasoning_effort == disabled.comparison_live.reasoning_effort == "none"
    assert len({s.cache_key_for(request()) for s in (plain, disabled, low)}) == 3
    with pytest.raises(ValueError, match="LLM_REASONING_EFFORT"):
        ModelStageService(replace(dhaka.settings, llm_reasoning_effort="typo"))


def test_general_policy_schema_cannot_request_numeric_rule_or_scope():
    provider = OpenRouterExtractionProvider(base_url="https://openrouter.test", model="test", api_key="test")
    schema = provider.build_body(request())["response_format"]["json_schema"]["schema"]
    defs = schema["$defs"]
    rule = defs["PolicyTextProposal"]["properties"]
    assert "subject" not in rule and "rule" not in rule
    assert rule["scope"] == {"$ref": "#/$defs/PolicyScope"}
    assert rule["evidence"] == {"$ref": "#/$defs/EvidenceQuote"}
    assert "AmountScope" not in defs and "RecordScope" not in defs


def test_explicit_json_mode_supplies_schema_and_keeps_routing_and_validation(dhaka, monkeypatch):
    import json
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "json_object")
    monkeypatch.setenv("FRANKFURT_LLM_RESPONSE_FORMAT", "json_schema")
    assert OfficeSettings.from_env("DHAKA").llm_response_format == "json_object"
    assert OfficeSettings.from_env("FRANKFURT").llm_response_format == "json_schema"
    json_mode = ModelStageService(replace(dhaka.settings, llm_response_format="json_object",
        llm_provider_prefs="only=deepseek,cloudflare,order=deepseek,cloudflare,require_parameters=true"))
    strict = ModelStageService(dhaka.settings)
    assert json_mode.cache_key_for(request()) != strict.cache_key_for(request())
    for provider, req in [(json_mode.live, request()),
                          (json_mode.live, replace(request(), subject=Subject.LOAN_APPROVAL)),
                          (json_mode.comparison_live, request())]:
        body = provider.build_body(req)
        assert body["response_format"] == {"type": "json_object"}
        assert "additionalProperties" in body["messages"][0]["content"]
        assert body["provider"]["only"] == ["deepseek", "cloudflare"]
        assert "reasoning" not in body
        parsed = provider._parse_response(json.dumps({"choices": [{"message": {
            "content": json.dumps({"invented": "fields"})}}]}).encode())
        assert parsed[-1][0].value == "schema_violation"
    with pytest.raises(ValueError, match="LLM_RESPONSE_FORMAT"):
        ModelStageService(replace(dhaka.settings, llm_response_format="typo"))
