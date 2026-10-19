"""Shared offline fixtures for the Meridian backend test suite.

Every fixture builds a fresh SQLite office database inside ``tmp_path`` and runs the
real ingestion pipeline against the committed replay proposals.  No network access,
no live credentials and no shared runtime state are used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from meridian.config import OfficeSettings
from meridian.contracts.common import Mode
from meridian.contracts.manifest import SourceManifest
from meridian.contracts.qa import QueryRequest, TargetFacts
from meridian.extraction.service import ModelStageService
from meridian.ingestion.pipeline import (
    IngestionOutcome,
    PreparedSource,
    ingest_prepared,
    prepare_pdf_source,
    prepare_slack_source,
)
from meridian.integrity.signing import PinnedKeyRegistry, Signer
from meridian.queries.engine import QueryEngine
from meridian.storage.db import Database
from meridian.storage.store import OfficeStore

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
TENANT = "meridian_demo"

# Fixed ingestion moments keep knowledge-interval assertions deterministic.
T_RESTRICTED = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
T_POLICY_V2 = datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)
T_POLICY_V3 = datetime(2026, 2, 2, 9, 0, tzinfo=timezone.utc)
T_PROCEDURE = datetime(2026, 2, 3, 9, 0, tzinfo=timezone.utc)
T_FRANKFURT = datetime(2026, 2, 4, 9, 0, tzinfo=timezone.utc)
T_SLACK = datetime(2026, 3, 3, 9, 16, tzinfo=timezone.utc)
T_KNOWN = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
T_VALID = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)

DEMO_RESTRICTED = (
    "documents/dhaka/dhaka_credit_note_restricted_v1.pdf",
    "manifests/dhaka_credit_note_restricted_v1.json",
)
DEMO_POLICY_V2 = (
    "documents/dhaka/dhaka_lending_policy_v2.pdf",
    "manifests/dhaka_lending_policy_v2.json",
)
DEMO_POLICY_V3 = (
    "documents/dhaka/dhaka_lending_policy_v3.pdf",
    "manifests/dhaka_lending_policy_v3.json",
)
DEMO_PROCEDURE = (
    "documents/dhaka/dhaka_records_procedure_v1.pdf",
    "manifests/dhaka_records_procedure_v1.json",
)
DEMO_FRANKFURT = (
    "documents/frankfurt/frankfurt_records_policy_v1.pdf",
    "manifests/frankfurt_records_policy_v1.json",
)
DEMO_SLACK = (
    "slack/dhaka_credit_update_2026_03_03.json",
    "manifests/dhaka_credit_update_2026_03_03.json",
)


def read_manifest(relative_path: str) -> SourceManifest:
    return SourceManifest.model_validate_json(
        (FIXTURES / relative_path).read_text("utf-8")
    )


def settings_for(
    base: Path,
    *,
    region: str = "DHAKA",
    fixtures_dir: Path | None = None,
    **overrides: Any,
) -> OfficeSettings:
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "region": region,
        "db_path": base / "meridian.db",
        "source_dir": base / "sources",
        "key_dir": base / "keys",
        "key_id": f"{region.lower()}-test-key-1",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "llm_model": None,
        "llm_api_key": None,
        "llm_provider_prefs": None,
        "llm_timeout_seconds": 5.0,
        "llm_max_attempts": 1,
        "llm_job_model_budget_seconds": 20.0,
        "llm_temperature": 0.0,
        "trusted_keys_path": base / "trusted_keys.json",
        "fixtures_dir": fixtures_dir or FIXTURES,
        "config_dir": ROOT / "config",
        "allow_paid_live_tests": False,
        "default_mode": "replay",
    }
    values.update(overrides)
    return OfficeSettings(**values)


@dataclass
class OfficeHarness:
    base: Path
    settings: OfficeSettings
    store: OfficeStore
    service: ModelStageService
    signer: Signer
    registry: PinnedKeyRegistry

    def prepare(self, file_rel: str, manifest_rel: str) -> PreparedSource:
        manifest = read_manifest(manifest_rel)
        raw = (FIXTURES / file_rel).read_bytes()
        if manifest.source_type.value == "pdf":
            return prepare_pdf_source(manifest, raw)
        return prepare_slack_source(manifest, raw)

    def ingest(
        self,
        document: tuple[str, str],
        *,
        now: datetime,
        mode: Mode = Mode.REPLAY,
    ) -> IngestionOutcome:
        file_rel, manifest_rel = document
        prepared = self.prepare(file_rel, manifest_rel)
        outcome = ingest_prepared(
            self.store,
            prepared,
            mode=mode,
            service=self.service,
            signer=self.signer,
            now=now,
        )
        assert outcome.ok, (outcome.error_code, outcome.error_detail)
        return outcome

    def query(
        self,
        target: TargetFacts,
        *,
        valid_at: datetime = T_VALID,
        known_at: datetime = T_KNOWN,
        question: str = "What approval rule applies?",
        allowed_restricted: bool = True,
    ):
        request = QueryRequest(
            question=question,
            target=target,
            valid_at=valid_at,
            known_at=known_at,
        )
        engine = QueryEngine(store=self.store, signer=self.signer)
        return engine.answer(
            request,
            known_at=known_at,
            allowed_restricted=allowed_restricted,
        )


def loan_target(amount_minor: int) -> TargetFacts:
    return TargetFacts(
        subject="loan_approval",
        amount_minor=amount_minor,
        currency="USD",
        loan_type="business",
        origin_office="DHAKA",
    )


def record_target() -> TargetFacts:
    return TargetFacts(
        subject="record_retention",
        record_class="loan_records",
        origin_office="DHAKA",
        processing_office="FRANKFURT",
        product="MTF_CROSS_OFFICE",
        starting_event="loan_closure",
    )


def make_office(
    base: Path,
    *,
    region: str = "DHAKA",
    fixtures_dir: Path | None = None,
    **settings_overrides: Any,
) -> OfficeHarness:
    base.mkdir(parents=True, exist_ok=True)
    settings = settings_for(
        base, region=region, fixtures_dir=fixtures_dir, **settings_overrides
    )
    signer = Signer.generate(key_id=settings.key_id, region=region)
    registry = PinnedKeyRegistry([signer.trusted_key()])
    store = OfficeStore(
        Database(settings.db_path), tenant_id=settings.tenant_id, region=region
    )
    service = ModelStageService(settings)
    return OfficeHarness(
        base=base,
        settings=settings,
        store=store,
        service=service,
        signer=signer,
        registry=registry,
    )


@pytest.fixture
def dhaka(tmp_path: Path) -> OfficeHarness:
    return make_office(tmp_path / "dhaka")


@pytest.fixture
def dhaka_restricted_only(tmp_path: Path) -> OfficeHarness:
    office = make_office(tmp_path / "restricted")
    office.ingest(DEMO_RESTRICTED, now=T_RESTRICTED)
    return office


@pytest.fixture
def frankfurt(tmp_path: Path) -> OfficeHarness:
    office = make_office(tmp_path / "frankfurt", region="FRANKFURT")
    office.ingest(DEMO_FRANKFURT, now=T_FRANKFURT)
    return office


@pytest.fixture
def dhaka_seeded(dhaka: OfficeHarness) -> OfficeHarness:
    """Baseline demo corpus without the later Slack guidance message."""
    dhaka.ingest(DEMO_RESTRICTED, now=T_RESTRICTED)
    dhaka.ingest(DEMO_POLICY_V2, now=T_POLICY_V2)
    dhaka.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)
    dhaka.ingest(DEMO_PROCEDURE, now=T_PROCEDURE)
    return dhaka


@pytest.fixture
def dhaka_full(dhaka_seeded: OfficeHarness) -> OfficeHarness:
    dhaka_seeded.ingest(DEMO_SLACK, now=T_SLACK)
    return dhaka_seeded


def revisions(harness: OfficeHarness, *, subject: str = "loan_approval"):
    return harness.store.claim_views(subject=subject)
