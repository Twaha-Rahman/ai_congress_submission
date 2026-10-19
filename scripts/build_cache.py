"""Build the versioned synthetic extraction cache from replay proposals.

This does **not** fabricate a live result: every cache entry is explicitly labelled as
synthetic replay material.  Cache keys include model, endpoint, temperature, provider
preferences, parser/prompt/schema versions and clause hashes, so changing runtime
configuration yields a visible cache miss rather than a silent fallback.

    .venv/bin/python scripts/build_cache.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from meridian.config import OfficeSettings, load_dotenv  # noqa: E402
from meridian.contracts.common import PROMPT_VERSION, SCHEMA_VERSION, Mode  # noqa: E402
from meridian.extraction.cache import CachedExtractionProvider  # noqa: E402
from meridian.extraction.provider import ClauseInput, ExtractionRequest  # noqa: E402
from meridian.extraction.replay import ReplayExtractionProvider  # noqa: E402
from meridian.extraction.service import ModelStageService  # noqa: E402
from meridian.ingestion.pipeline import (  # noqa: E402
    clause_id_for,
    prepare_pdf_source,
    prepare_slack_source,
)
from meridian.contracts.manifest import SourceManifest  # noqa: E402


def main() -> int:
    load_dotenv()
    plan = json.loads((ROOT / "fixtures" / "demo_plan.json").read_text("utf-8"))
    entries = []
    for item in plan["sources"]:
        entries.append((item["region"], item["file"], item["manifest"], item["kind"]))
    slack = plan["demo1_slack"]
    entries.append(("DHAKA", slack["file"], slack["manifest"], "slack"))

    written = 0
    for region, file_name, manifest_name, kind in entries:
        manifest = SourceManifest.model_validate_json(
            (ROOT / "fixtures" / manifest_name).read_text("utf-8")
        )
        settings = OfficeSettings.from_env(region, tenant_id=manifest.tenant_id)
        raw = (ROOT / "fixtures" / file_name).read_bytes()
        prepared = (
            prepare_pdf_source(manifest, raw)
            if kind == "pdf"
            else prepare_slack_source(manifest, raw)
        )
        clauses = []
        # Rebuild clause IDs exactly as the pipeline does.
        for index, clause in enumerate(prepared.parsed.clauses):
            clauses.append(
                ClauseInput(
                    clause_id=clause_id_for(manifest, index, clause.section),
                    page=clause.page,
                    section=clause.section,
                    text=clause.text,
                )
            )
        request = ExtractionRequest(
            tenant_id=manifest.tenant_id,
            region=region,
            source_identity=manifest.source_identity,
            version_label=manifest.version_label,
            source_type=manifest.source_type,
            subject=manifest.subject,
            authority=manifest.authority.value,
            content_sha256=prepared.content_sha256,
            manifest_scope_summary=manifest.scope.model_dump_json(),
            clauses=clauses,
            mode=Mode.CACHED,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            request_id=f"cache_build_{manifest.source_identity}_{manifest.version_label}",
        )
        service = ModelStageService(settings)
        key = service.cache_key_for(request)
        from dataclasses import replace

        replay = ReplayExtractionProvider(settings.replay_dir).extract(
            replace(request, mode=Mode.REPLAY)
        )
        if not replay.ok:
            print(
                f"cannot build cache for {file_name}: {replay.error_code} {replay.error_detail}",
                file=sys.stderr,
            )
            return 1
        cache = CachedExtractionProvider(settings.cache_dir)
        path = cache.write(
            key,
            replay,
            model_metadata={
                "provider": "synthetic-cache",
                "route": "offline-replay",
                "model": replay.model,
                "attempts": replay.attempts,
                "latency_ms": replay.latency_ms,
                "usage": {},
                "status_code": None,
                "note": "generated from replay proposals; not a live model result",
            },
            created_at=__import__("datetime").datetime.now().astimezone(),
        )
        print(f"{region:<9} {file_name:<58} key {key[:16]}… -> {path.relative_to(ROOT)}")
        written += 1
    print(f"\nwrote {written} synthetic cache entr{'y' if written == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
