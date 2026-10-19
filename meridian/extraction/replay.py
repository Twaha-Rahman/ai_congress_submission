"""Versioned synthetic replay fixtures for offline demonstration.

Replay supplies *extraction proposals only*.  Validation, persistence, comparison,
signing and verification all run normally.  A missing or stale fixture fails
visibly; replay never touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts.common import PROMPT_VERSION, SCHEMA_VERSION, ErrorCode, Mode
from ..contracts.extraction import ExtractionProposal
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from .provider import ExtractionRequest, ProviderResult


class ReplayExtractionProvider:
    name = "replay-fixture"

    def __init__(self, replay_dir: str | Path) -> None:
        self.replay_dir = Path(replay_dir)

    def path_for(self, request: ExtractionRequest) -> Path:
        return self.replay_dir / f"{request.source_identity}__{request.version_label}.json"

    def extract(self, request: ExtractionRequest) -> ProviderResult:
        path = self.path_for(request)
        result = ProviderResult(mode=Mode.REPLAY, provider=self.name)
        if not path.exists():
            result.error_code = ErrorCode.REPLAY_FIXTURE_MISSING
            result.error_detail = (
                f"no replay fixture for {request.source_identity}/{request.version_label} "
                f"(expected {path.name})"
            )
            return result
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.error_code = ErrorCode.REPLAY_FIXTURE_MISSING
            result.error_detail = f"replay fixture is unreadable: {exc}"
            return result

        fixture_region = payload.get("region")
        if fixture_region and fixture_region != request.region:
            result.error_code = ErrorCode.REPLAY_FIXTURE_MISSING
            result.error_detail = (
                f"replay fixture belongs to region {fixture_region}, not {request.region}"
            )
            return result
        expected_hash = payload.get("content_sha256")
        if expected_hash and expected_hash != request.content_sha256:
            result.error_code = ErrorCode.REPLAY_FIXTURE_MISSING
            result.error_detail = (
                "replay fixture content_sha256 does not match the ingested source; "
                "regenerate the fixtures instead of silently reusing stale proposals"
            )
            return result
        if payload.get("prompt_version", PROMPT_VERSION) != request.prompt_version:
            result.error_code = ErrorCode.REPLAY_FIXTURE_MISSING
            result.error_detail = "replay fixture prompt version differs from the request"
            return result

        try:
            proposal = ExtractionProposal.model_validate(payload["proposal"])
        except Exception as exc:
            result.error_code = ErrorCode.SCHEMA_VIOLATION
            result.error_detail = f"replay proposal failed schema validation: {exc}"
            return result

        metadata = payload.get("model_metadata") or {}
        result.proposal = proposal
        result.model = metadata.get("model", "synthetic-fixture")
        result.route = metadata.get("route", "offline-replay")
        result.attempts = int(metadata.get("attempts", 1))
        result.latency_ms = metadata.get("latency_ms")
        result.usage = {}
        result.raw_output_sha256 = sha256_hex(canonical_json_bytes(proposal))
        return result
