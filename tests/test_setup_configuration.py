"""Fresh setup and Compose must preserve the selected model route and modes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from meridian.config import OfficeSettings
from meridian.extraction.openrouter import OpenRouterExtractionProvider
from scripts import setup

ROOT = Path(__file__).resolve().parents[1]
MODEL = "deepseek/deepseek-v4.1-flash-1017"
PROVIDERS = "only=deepseek,cloudflare,order=deepseek,cloudflare,require_parameters=true"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("LLM_", "DHAKA_", "FRANKFURT_", "DEMO_TOKEN_")) or key in {
            "TENANT_ID", "DEFAULT_MODE", "DEMO_EXTRACTION_MODE", "DB_PATH", "SOURCE_DIR",
            "KEY_DIR", "KEY_ID", "REGION", "TRUSTED_KEYS_PATH", "FIXTURES_DIR", "CONFIG_DIR",
        }:
            monkeypatch.delenv(key)


def load_values(monkeypatch, values):
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def assert_preset(settings):
    assert settings.llm_model == MODEL
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.llm_response_format == "json_object"
    assert settings.default_mode == "replay"
    assert settings.llm_api_key is None
    provider = OpenRouterExtractionProvider(
        base_url=settings.llm_base_url, model=settings.llm_model, api_key=None,
        provider_preferences=settings.llm_provider_prefs,
        response_format=settings.llm_response_format,
    )
    assert provider._provider_routing() == {
        "only": ["deepseek", "cloudflare"], "order": ["deepseek", "cloudflare"],
        "require_parameters": True,
    }


def test_fresh_setup_writes_route_and_modes_without_changing_keys_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/demo_plan.json").write_text("{}")
    assert setup.main() == 0
    env_path = tmp_path / ".env"
    values = setup.read_env(env_path)
    assert values["LLM_PROVIDER_PREFS"] == PROVIDERS
    assert values["DEMO_EXTRACTION_MODE"] == "replay"
    load_values(monkeypatch, values)
    for office in setup.REGIONS:
        assert_preset(OfficeSettings.from_env(office))
    before_env = env_path.read_bytes()
    before_keys = {path: path.read_bytes() for path in (tmp_path / "runtime/keys").rglob("*") if path.is_file()}
    assert before_keys
    assert setup.main() == 0
    assert env_path.read_bytes() == before_env
    assert all(path.read_bytes() == content for path, content in before_keys.items())


def test_existing_operator_settings_and_secrets_survive_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/demo_plan.json").write_text("{}")
    custom = {
        "LLM_MODEL": "custom/model", "LLM_API_KEY": "test-only-secret",
        "LLM_PROVIDER_PREFS": "only=custom", "LLM_RESPONSE_FORMAT": "json_schema",
        "DEFAULT_MODE": "live", "DEMO_EXTRACTION_MODE": "cached",
        "DHAKA_LLM_MODEL": "", "FRANKFURT_LLM_MODEL": "office/model",
        "FRANKFURT_DEFAULT_MODE": "cached", "DEMO_TOKEN_DHAKA_READER": "test-reader-token",
    }
    (tmp_path / ".env").write_text("\n".join(f"{key}={value}" for key, value in custom.items()))
    assert setup.main() == 0
    values = setup.read_env(tmp_path / ".env")
    assert {key: values[key] for key in custom} == custom


def test_example_and_generated_configs_resolve_the_same_preset(tmp_path, monkeypatch):
    setup.write_env(tmp_path / ".env", {})
    generated = setup.read_env(tmp_path / ".env")
    example = setup.read_env(ROOT / ".env.example")
    for key in ["LLM_MODEL", "LLM_PROVIDER_PREFS", "LLM_RESPONSE_FORMAT", "DEFAULT_MODE", "DEMO_EXTRACTION_MODE"]:
        assert generated[key] == example[key]
    load_values(monkeypatch, example)
    for office in setup.REGIONS:
        assert_preset(OfficeSettings.from_env(office))


@pytest.mark.parametrize("overrides", [{}, {
    "LLM_API_KEY": "test-shared-key", "LLM_RESPONSE_FORMAT": "json_schema", "DEFAULT_MODE": "cached",
    "DHAKA_LLM_MODEL": "office/model", "DHAKA_LLM_BASE_URL": "https://office.example/v1",
    "DHAKA_LLM_API_KEY": "test-office-key", "DHAKA_LLM_PROVIDER_PREFS": "only=office-provider",
    "DHAKA_LLM_RESPONSE_FORMAT": "json_object", "DHAKA_DEFAULT_MODE": "live",
}])
def test_compose_resolves_the_same_route_and_modes_as_native(tmp_path, monkeypatch, overrides):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose is not installed")
    version = subprocess.run([docker, "compose", "version"], capture_output=True)
    if version.returncode:
        pytest.skip("Docker Compose is not installed")
    env_path = tmp_path / ".env"
    setup.write_env(env_path, overrides)
    values = setup.read_env(env_path)
    result = subprocess.run([docker, "compose", "--env-file", str(env_path), "config", "--format", "json"],
                            cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, check=True)
    services = json.loads(result.stdout)["services"]
    load_values(monkeypatch, values)
    for office in setup.REGIONS:
        settings = OfficeSettings.from_env(office)
        actual = services[office.lower()]["environment"]
        for key, expected in {
            "LLM_MODEL": settings.llm_model, "LLM_BASE_URL": settings.llm_base_url,
            "LLM_API_KEY": settings.llm_api_key or "", "LLM_RESPONSE_FORMAT": settings.llm_response_format,
            "DEFAULT_MODE": settings.default_mode,
        }.items():
            assert actual[key] == expected
        configured = OpenRouterExtractionProvider(base_url=settings.llm_base_url, model=settings.llm_model,
            api_key=None, provider_preferences=settings.llm_provider_prefs)
        container = OpenRouterExtractionProvider(base_url=actual["LLM_BASE_URL"], model=actual["LLM_MODEL"],
            api_key=None, provider_preferences=actual["LLM_PROVIDER_PREFS"])
        assert container._provider_routing() == configured._provider_routing()
