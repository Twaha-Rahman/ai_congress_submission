"""Provider selection and per-stage execution modes.

Modes are explicit and per stage.  There is no silent fallback from live inference to
fixtures: a live failure stays a visible failure, a cache miss stays a cache miss, and
replay is only used when it was requested.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from ..config import OfficeSettings, is_local_endpoint
from ..contracts.common import PARSER_VERSION, PROMPT_VERSION, SCHEMA_VERSION, ErrorCode, Mode
from ..contracts.federation import ModelCallMetadata
from ..contracts.extraction import PolicyComparisonProposal
from .cache import CachedExtractionProvider, compute_cache_key
from .openrouter import OpenRouterExtractionProvider
from .provider import (
    ExtractionRequest,
    ProviderPrerequisiteError,
    ProviderResult,
)
from .replay import ReplayExtractionProvider
from .policy import PolicyComparisonProvider, POLICY_COMPARISON_VERSION

#: Callback receiving a dict describing one audited model transport event.
EgressSink = Callable[[dict], None]


class ModelStageService:
    """Runs the extraction stage in the requested mode and records what happened."""

    def __init__(
        self,
        settings: OfficeSettings,
        *,
        transport=None,
        sleep: Callable[[float], None] | None = None,
        write_cache: bool = False,
        egress_sink: EgressSink | None = None,
    ) -> None:
        self.settings = settings
        self.write_cache = write_cache
        self.egress_sink = egress_sink
        self.replay = ReplayExtractionProvider(settings.replay_dir)
        self.cache = CachedExtractionProvider(settings.cache_dir)
        kwargs: dict = {}
        if transport is not None:
            kwargs["transport"] = transport
        if sleep is not None:
            kwargs["sleep"] = sleep
        self.live = OpenRouterExtractionProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            max_attempts=settings.llm_max_attempts,
            job_budget_seconds=settings.llm_job_model_budget_seconds,
            temperature=settings.llm_temperature,
            provider_preferences=settings.llm_provider_prefs,
            reasoning_effort=settings.llm_reasoning_effort,
            **kwargs,
        )
        self.comparison_live = PolicyComparisonProvider(
            base_url=settings.llm_base_url, model=settings.llm_model,
            api_key=settings.llm_api_key, timeout_seconds=settings.llm_timeout_seconds,
            max_attempts=settings.llm_max_attempts,
            job_budget_seconds=settings.llm_job_model_budget_seconds,
            temperature=settings.llm_temperature,
            provider_preferences=settings.llm_provider_prefs,
            reasoning_effort=settings.llm_reasoning_effort, **kwargs,
        )
        self.comparison_cache = CachedExtractionProvider(
            settings.cache_dir / "comparisons", proposal_model=PolicyComparisonProposal,
        )
        self.comparison_replay = ReplayExtractionProvider(
            settings.replay_dir / "comparisons", proposal_model=PolicyComparisonProposal,
        )

    # ------------------------------------------------------------------- helpers
    def cache_key_for(self, request: ExtractionRequest) -> str:
        return compute_cache_key(
            request,
            model=self.settings.llm_model,
            base_url=self.settings.llm_base_url,
            temperature=self.settings.llm_temperature,
            provider_preferences=self.settings.llm_provider_prefs,
            reasoning_effort=self.settings.llm_reasoning_effort,
            parser_version=PARSER_VERSION,
        )

    def _record(
        self,
        request: ExtractionRequest,
        result: ProviderResult,
        *,
        outcome: str,
        raw_source_bytes: int,
    ) -> None:
        if self.egress_sink is None:
            return
        self.egress_sink(
            {
                "request_id": request.request_id,
                "channel": "hosted_model",
                "destination": self.settings.llm_base_url,
                "payload_type": "policy_comparison" if request.prompt_version == POLICY_COMPARISON_VERSION else "extraction_request",
                "payload_bytes": result.request_bytes,
                "payload_sha256": "",
                "raw_source_bytes": raw_source_bytes,
                "outcome": outcome,
                "error_code": result.error_code.value if result.error_code else None,
                "model_metadata": ModelCallMetadata(
                    mode=result.mode.value,
                    provider=result.provider,
                    route=result.route,
                    model=result.model,
                    prompt_version=request.prompt_version,
                    schema_version=request.schema_version,
                    attempts=result.attempts,
                    latency_ms=result.latency_ms,
                    usage={k: v for k, v in result.usage.items() if isinstance(v, int)},
                    status_code=result.status_code,
                    outcome=outcome,
                ),
            }
        )

    def _live_processing_allowed(self, request: ExtractionRequest) -> bool:
        """Hosted processing requires the trusted manifest permission.

        Only an operator-approved loopback/private-network endpoint is treated as
        local processing.  An arbitrary URL is never inferred to be safe from its
        hostname alone.
        """

        if request.hosted_model_allowed:
            return True
        return bool(
            self.settings.llm_local_endpoint_approved
            and is_local_endpoint(self.settings.llm_base_url)
        )

    # -------------------------------------------------------------------- public
    def extract(self, request: ExtractionRequest) -> ProviderResult:
        return self._execute(request)

    def compare_policy(self, request: ExtractionRequest) -> ProviderResult:
        return self._execute(request, comparison=True)

    def _execute(self, request: ExtractionRequest, *, comparison: bool = False) -> ProviderResult:
        live = self.comparison_live if comparison else self.live
        cache = self.comparison_cache if comparison else self.cache
        replay = self.comparison_replay if comparison else self.replay
        raw_source_bytes = sum(len(clause.text.encode("utf-8")) for clause in request.clauses)
        if request.mode is Mode.LIVE:
            if not self._live_processing_allowed(request):
                result = ProviderResult(
                    mode=Mode.LIVE,
                    provider="policy",
                    error_code=ErrorCode.EGRESS_DENIED,
                    error_detail=(
                        "trusted manifest permissions.hosted_model is false; source text "
                        "was not sent to the configured model endpoint or cache"
                    ),
                    model=self.settings.llm_model,
                    request_bytes=0,
                )
                # Audit the blocked attempt with zero transported source bytes.
                self._record(request, result, outcome="blocked", raw_source_bytes=0)
                return result
            try:
                result = live.extract(request)
            except ProviderPrerequisiteError as exc:
                result = ProviderResult(
                    mode=Mode.LIVE,
                    provider=live.name,
                    error_code=exc.error_code,
                    error_detail=exc.detail,
                    model=self.settings.llm_model,
                    request_bytes=0,
                )
                self._record(request, result, outcome="prerequisite_missing", raw_source_bytes=0)
                return result
            if result.ok and self.write_cache:
                key = self.cache_key_for(request)
                metadata = {
                    "provider": result.provider,
                    "model": result.model,
                    "route": result.route,
                    "attempts": result.attempts,
                    "latency_ms": result.latency_ms,
                    "usage": {k: v for k, v in result.usage.items() if isinstance(v, int)},
                    "status_code": result.status_code,
                }
                cache.write(
                    key,
                    result,
                    model_metadata=metadata,
                    created_at=datetime.now().astimezone(),
                )
            self._record(
                request,
                result,
                outcome="ok" if result.ok else "failed",
                raw_source_bytes=raw_source_bytes,
            )
            return result

        if request.mode is Mode.CACHED:
            key = self.cache_key_for(request)
            result = cache.extract_with_key(request, key)
            if result.ok is False:
                # A cache miss is reported to the caller; it never triggers a live call.
                pass
            self._record(
                request,
                result,
                outcome="ok" if result.ok else "cache_miss",
                raw_source_bytes=0,
            )
            return result

        result = replay.extract(request)
        self._record(
            request,
            result,
            outcome="ok" if result.ok else "replay_missing",
            raw_source_bytes=0,
        )
        return result


__all__ = [
    "ErrorCode",
    "ModelStageService",
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
]
