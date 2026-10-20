"""Versioned extraction cache: keyed by every input that can change the output."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..contracts.common import (
    Mode,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    ErrorCode,
    canonical_datetime,
)
from ..contracts.extraction import ExtractionProposal
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from .provider import ExtractionRequest, ProviderResult


def compute_cache_key(
    request: ExtractionRequest,
    *,
    model: str | None,
    base_url: str,
    temperature: float,
    provider_preferences: str | None,
    parser_version: str,
) -> str:
    """Cache key over tenant/region, input hashes, parser/model/prompt/schema versions."""

    payload = {
        "tenant_id": request.tenant_id,
        "region": request.region,
        "source_identity": request.source_identity,
        "version_label": request.version_label,
        "content_sha256": request.content_sha256,
        "clause_hashes": [sha256_hex(clause.text.encode("utf-8")) for clause in request.clauses],
        "parser_version": parser_version,
        "prompt_version": request.prompt_version,
        "schema_version": request.schema_version,
        "model": model or "",
        "base_url": base_url,
        "temperature": canonical_decimal(temperature),
        "provider_preferences": provider_preferences or "",
        "subject": request.subject.value,
        "authority": request.authority,
    }
    if request.subject.value == "general_policy":
        payload["manifest_scope_sha256"] = sha256_hex(request.manifest_scope_summary.encode("utf-8"))
    return sha256_hex(canonical_json_bytes(payload))


def canonical_decimal(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


class CachedExtractionProvider:
    """Reuses validated cached model-stage outputs; a miss is a visible error."""

    name = "cache"

    def __init__(self, cache_dir: str | Path, *, proposal_model=ExtractionProposal) -> None:
        self.cache_dir = Path(cache_dir)
        self.proposal_model = proposal_model

    def path_for(self, cache_key: str) -> Path:
        return self.cache_dir / f"{cache_key}.json"

    def extract(self, request: ExtractionRequest) -> ProviderResult:
        raise NotImplementedError  # use extract_with_key

    def extract_with_key(self, request: ExtractionRequest, cache_key: str) -> ProviderResult:
        path = self.path_for(cache_key)
        result = ProviderResult(
            mode=Mode.CACHED,
            provider=self.name,
            cache_key=cache_key,
            model=None,
        )
        if not path.exists():
            result.error_code = ErrorCode.CACHE_MISS
            result.error_detail = (
                f"no cached model output for key {cache_key[:16]}... "
                "(select live mode for an uncached call)"
            )
            return result
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.error_code = ErrorCode.CACHE_MISS
            result.error_detail = f"cached entry is unreadable: {exc}"
            return result
        if payload.get("cache_key") != cache_key:
            result.error_code = ErrorCode.CACHE_MISS
            result.error_detail = "cached entry key does not match the requested key"
            return result
        try:
            proposal = self.proposal_model.model_validate(payload["proposal"])
        except Exception as exc:
            result.error_code = ErrorCode.SCHEMA_VIOLATION
            result.error_detail = f"cached output failed revalidation: {exc}"
            return result
        metadata = payload.get("model_metadata") or {}
        result.proposal = proposal
        result.model = metadata.get("model")
        result.route = metadata.get("route")
        result.attempts = int(metadata.get("attempts", 1))
        result.latency_ms = metadata.get("latency_ms")
        result.usage = {
            key: value
            for key, value in (metadata.get("usage") or {}).items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        result.raw_output_sha256 = sha256_hex(canonical_json_bytes(proposal))
        return result

    def write(
        self,
        cache_key: str,
        result: ProviderResult,
        *,
        model_metadata: dict,
        created_at: datetime,
    ) -> Path:
        """Persist a live result for later cached replay (explicit opt-in only)."""

        if result.proposal is None:
            raise ValueError("refusing to cache a failed extraction")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(cache_key)
        payload = {
            "cache_key": cache_key,
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "created_at": canonical_datetime(created_at),
            "model_metadata": model_metadata,
            "proposal": result.proposal.model_dump(mode="json"),
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path
