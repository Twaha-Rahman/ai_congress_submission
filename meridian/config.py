"""Runtime configuration loaded from environment variables.

No secret is ever hardcoded: credentials, model routes and signing-key locations are
read from the environment (optionally via a local ``.env`` file that is git-ignored).
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES_DIR = REPO_ROOT / "fixtures"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"


def load_dotenv(path: str | Path | None = None) -> None:
    """Minimal ``.env`` loader: existing environment variables always win."""

    env_path = Path(path) if path is not None else REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _get(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value != "":
            return value
    return default


def _get_int(*names: str, default: int) -> int:
    raw = _get(*names)
    if raw is None:
        return default
    return int(raw)


def _get_float(*names: str, default: float) -> float:
    raw = _get(*names)
    if raw is None:
        return default
    return float(raw)


def _get_bool(*names: str, default: bool = False) -> bool:
    raw = _get(*names)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_local_endpoint(url: str) -> bool:
    """Return True only for loopback or private-network HTTP(S) endpoints.

    This is deliberately narrow: it is used to decide whether an operator's
    explicit local-provider approval can apply.  A public host, a non-HTTP scheme,
    a missing hostname or a hostname that cannot be resolved as a literal address
    is not treated as local.
    """

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_unspecified
    )


@dataclass(frozen=True)
class OfficeSettings:
    """Configuration for one office process."""

    tenant_id: str
    region: str
    db_path: Path
    source_dir: Path
    key_dir: Path
    key_id: str
    llm_base_url: str
    llm_model: str | None
    llm_api_key: str | None
    llm_provider_prefs: str | None
    llm_timeout_seconds: float
    llm_max_attempts: int
    llm_job_model_budget_seconds: float
    llm_temperature: float
    trusted_keys_path: Path
    fixtures_dir: Path
    config_dir: Path
    allow_paid_live_tests: bool
    default_mode: str
    #: Explicit operator approval for a loopback/private-network extraction endpoint.
    #: Never inferred from a URL: a public or otherwise non-local endpoint still
    #: requires ``permissions.hosted_model=true`` in the trusted manifest.
    llm_local_endpoint_approved: bool = False
    policy_comparison_top_k: int = 6
    policy_comparison_max_pairs: int = 24

    @property
    def cache_dir(self) -> Path:
        return self.fixtures_dir / "cache" / self.region.lower()

    @property
    def replay_dir(self) -> Path:
        return self.fixtures_dir / "replay" / self.region.lower()

    @property
    def principals_path(self) -> Path:
        return self.config_dir / "principals.json"

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    def as_public_dict(self) -> dict[str, str]:
        """Health/readiness view: never includes credentials."""

        return {
            "tenant_id": self.tenant_id,
            "region": self.region,
            "db_path": str(self.db_path),
            "source_dir": str(self.source_dir),
            "database_present": str(self.db_path.exists()),
            "model_configured": str(self.has_model_credentials),
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model or "",
        }

    @classmethod
    def from_env(cls, region: str | None = None, *, tenant_id: str | None = None) -> "OfficeSettings":
        region_value = (region or _get("REGION") or "DHAKA").upper()
        prefix = f"{region_value}_"
        tenant = tenant_id or _get("TENANT_ID", default="meridian_demo")
        assert tenant is not None
        db_path = Path(
            _get(f"{prefix}DB_PATH", "DB_PATH", default=f"runtime/{region_value.lower()}/meridian.db")
        )
        source_dir = Path(
            _get(
                f"{prefix}SOURCE_DIR",
                "SOURCE_DIR",
                default=f"runtime/{region_value.lower()}/sources",
            )
        )
        key_dir = Path(
            _get(f"{prefix}KEY_DIR", "KEY_DIR", default=f"runtime/keys/{region_value.lower()}")
        )
        key_id = _get(f"{prefix}KEY_ID", "KEY_ID", default=f"{region_value.lower()}-demo-key-1")
        return cls(
            tenant_id=tenant,
            region=region_value,
            db_path=db_path,
            source_dir=source_dir,
            key_dir=key_dir,
            key_id=key_id or f"{region_value.lower()}-demo-key-1",
            llm_base_url=_get(
                f"{prefix}LLM_BASE_URL",
                "LLM_BASE_URL",
                default="https://openrouter.ai/api/v1",
            )
            or "",
            llm_model=_get(f"{prefix}LLM_MODEL", "LLM_MODEL"),
            llm_api_key=_get(f"{prefix}LLM_API_KEY", "LLM_API_KEY"),
            llm_provider_prefs=_get(f"{prefix}LLM_PROVIDER_PREFS", "LLM_PROVIDER_PREFS"),
            llm_timeout_seconds=_get_float(
                f"{prefix}LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS", default=300.0
            ),
            llm_max_attempts=_get_int(f"{prefix}LLM_MAX_ATTEMPTS", "LLM_MAX_ATTEMPTS", default=2),
            llm_job_model_budget_seconds=_get_float(
                f"{prefix}LLM_JOB_MODEL_BUDGET_SECONDS",
                "LLM_JOB_MODEL_BUDGET_SECONDS",
                default=300.0,
            ),
            llm_temperature=_get_float(
                f"{prefix}LLM_TEMPERATURE", "LLM_TEMPERATURE", default=0.0
            ),
            trusted_keys_path=Path(
                _get("TRUSTED_KEYS_PATH", default="runtime/trusted_keys.json") or ""
            ),
            fixtures_dir=Path(_get("FIXTURES_DIR", default=str(DEFAULT_FIXTURES_DIR)) or ""),
            config_dir=Path(_get("CONFIG_DIR", default=str(DEFAULT_CONFIG_DIR)) or ""),
            allow_paid_live_tests=_get_bool("ALLOW_PAID_LIVE_TESTS", default=False),
            default_mode=(_get(f"{prefix}DEFAULT_MODE", "DEFAULT_MODE", default="replay") or "replay").lower(),
            llm_local_endpoint_approved=_get_bool(
                f"{prefix}LLM_LOCAL_ENDPOINT_APPROVED",
                "LLM_LOCAL_ENDPOINT_APPROVED",
                default=False,
            ),
            policy_comparison_top_k=max(1, min(50, _get_int(
                f"{prefix}POLICY_COMPARISON_TOP_K", "POLICY_COMPARISON_TOP_K", default=6,
            ))),
            policy_comparison_max_pairs=max(1, min(200, _get_int(
                f"{prefix}POLICY_COMPARISON_MAX_PAIRS", "POLICY_COMPARISON_MAX_PAIRS", default=24,
            ))),
        )


@dataclass(frozen=True)
class GatewaySettings:
    tenant_id: str
    dhaka_base_url: str
    frankfurt_base_url: str
    trusted_keys_path: Path
    fixtures_dir: Path
    config_dir: Path
    request_timeout_seconds: float
    runtime_dir: Path

    @property
    def principals_path(self) -> Path:
        return self.config_dir / "principals.json"

    @property
    def relay_log_path(self) -> Path:
        return self.runtime_dir / "relay.jsonl"

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        return cls(
            tenant_id=_get("TENANT_ID", default="meridian_demo") or "meridian_demo",
            dhaka_base_url=_get("DHAKA_BASE_URL", default="http://127.0.0.1:8081") or "",
            frankfurt_base_url=_get("FRANKFURT_BASE_URL", default="http://127.0.0.1:8082") or "",
            trusted_keys_path=Path(
                _get("TRUSTED_KEYS_PATH", default="runtime/trusted_keys.json") or ""
            ),
            fixtures_dir=Path(_get("FIXTURES_DIR", default=str(DEFAULT_FIXTURES_DIR)) or ""),
            config_dir=Path(_get("CONFIG_DIR", default=str(DEFAULT_CONFIG_DIR)) or ""),
            request_timeout_seconds=_get_float("GATEWAY_TIMEOUT_SECONDS", default=20.0),
            runtime_dir=Path(_get("GATEWAY_RUNTIME_DIR", default="runtime/gateway") or ""),
        )

    def base_url_for(self, region: str) -> str:
        return self.dhaka_base_url if region.upper() == "DHAKA" else self.frankfurt_base_url
