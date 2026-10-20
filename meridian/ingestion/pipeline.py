"""Ingestion pipeline: preparation, extraction, validation and transactional publication.

One source version is committed in a single SQLite transaction together with its
clauses, accepted claims, review items, lineage edges and derived findings.  Replayed
extraction proposals go through exactly the same validators, engine, persistence and
signers as live ones.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..contracts.claims import ClaimRevision, ClaimRevisionRecord
from ..contracts.common import (
    PARSER_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    ClaimOrigin,
    ClaimStatus,
    ErrorCode,
    Mode,
    Sensitivity,
    SourceType,
    Subject,
    canonical_datetime,
    utc_now,
)
from ..contracts.extraction import ExtractionProvenance, VerifiedEvidence
from ..contracts.manifest import SourceManifest
from ..extraction.provider import ClauseInput, ExtractionRequest, ProviderResult
from ..extraction.service import ModelStageService
from ..extraction.policy import POLICY_EXTRACTION_VERSION
from ..extraction.validate import (
    Rejection,
    ReviewItem,
    ValidationOutcome,
    ValidatorClause,
    VerifiedRule,
    validate_proposal,
    rule_summary,
)
from ..integrity.bundles import SignedManifestPayload, claim_hash, clause_leaf_payload
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..integrity.merkle import build_tree
from ..integrity.signing import Signer
from ..rules.publish import publish_findings, reevaluate_findings_for_revisions
from ..rules.general import prepare_policy_comparisons, publish_policy_batch
from ..storage.store import ClauseRow, OfficeStore, SourceRow, canonical_json_text, new_id
from ..temporal.supersession import apply_manifest_supersession
from .pdf import ParsedDocument, UnsupportedDocument, parse_pdf_bytes
from .slack import parse_slack_payload, slack_to_document


class VersionPayloadMismatch(ValueError):
    """Changed bytes arrived under an immutable version identifier."""

    error_code = ErrorCode.VERSION_PAYLOAD_MISMATCH


class ManifestSourceMismatch(ValueError):
    error_code = ErrorCode.INVALID_INPUT


@dataclass(frozen=True)
class PreparedSource:
    manifest: SourceManifest
    source_type: SourceType
    raw_bytes: bytes
    parsed: ParsedDocument
    source_sha256: str
    content_sha256: str
    file_extension: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestionOutcome:
    source_id: str | None = None
    created: bool = False
    duplicate: bool = False
    error_code: str | None = None
    error_detail: str | None = None
    review_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    claim_revision_ids: list[str] = field(default_factory=list)
    finding_types: list[str] = field(default_factory=list)
    stage_modes: dict[str, str] = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    warnings: list[str] = field(default_factory=list)
    source_sha256: str | None = None
    content_sha256: str | None = None
    merkle_root: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


def content_hash_of(parsed: ParsedDocument) -> str:
    return sha256_hex(parsed.normalized_text().encode("utf-8"))


def prepare_pdf_source(manifest: SourceManifest, raw_bytes: bytes) -> PreparedSource:
    if manifest.source_type is not SourceType.PDF:
        raise ManifestSourceMismatch("manifest source_type does not match a PDF upload")
    parsed = parse_pdf_bytes(raw_bytes)
    return PreparedSource(
        manifest=manifest,
        source_type=SourceType.PDF,
        raw_bytes=raw_bytes,
        parsed=parsed,
        source_sha256=sha256_hex(raw_bytes),
        content_sha256=content_hash_of(parsed),
        file_extension="pdf",
        warnings=list(parsed.warnings),
    )


def prepare_slack_source(manifest: SourceManifest, raw_bytes: bytes) -> PreparedSource:
    if manifest.source_type is not SourceType.SLACK:
        raise ManifestSourceMismatch("manifest source_type does not match a Slack upload")
    messages = parse_slack_payload(raw_bytes)
    parsed = slack_to_document(messages)
    newest = max(message.ts for message in messages)
    if manifest.publication_time is None or manifest.publication_time != newest:
        raise ManifestSourceMismatch(
            "manifest publication_time must equal the newest message timestamp in the saved event"
        )
    return PreparedSource(
        manifest=manifest,
        source_type=SourceType.SLACK,
        raw_bytes=raw_bytes,
        parsed=parsed,
        source_sha256=sha256_hex(raw_bytes),
        content_sha256=content_hash_of(parsed),
        file_extension="json",
        warnings=list(parsed.warnings),
    )


def clause_id_for(manifest: SourceManifest, clause_index: int, section: str | None) -> str:
    """Legacy base ID; use clause_ids_for when preparing a complete source."""
    suffix = section if section else f"p{clause_index + 1}"
    return f"{manifest.source_identity}:{manifest.version_label}:{suffix}"


def clause_ids_for(manifest: SourceManifest, parsed: ParsedDocument) -> list[str]:
    """Preserve existing IDs, disambiguating repeated sections by passage order.

    A section may span pages or appear more than once. Its human-readable section
    remains metadata; every preserved passage needs its own commitment and ID.
    """
    bases = [clause_id_for(manifest, i, clause.section) for i, clause in enumerate(parsed.clauses)]
    reserved = set(bases)
    used: set[str] = set()
    identifiers = []
    for index, base in enumerate(bases):
        identifier = base
        part = index + 1
        while identifier in used or (identifier != base and identifier in reserved):
            identifier = f"{base}:part{part}"
            part += 1
        identifiers.append(identifier)
        used.add(identifier)
    return identifiers


def store_original(source_dir: Path, raw_bytes: bytes, extension: str, region: str) -> Path:
    """Content-addressed immutable original; never overwritten."""

    digest = sha256_hex(raw_bytes)
    directory = source_dir / region.lower()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.{extension}"
    if path.exists():
        if path.read_bytes() != raw_bytes:
            raise VersionPayloadMismatch(
                "a stored original with the same content hash has different bytes"
            )
        return path
    tmp = directory / f".{digest}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(raw_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path


def build_source_version(
    *,
    store: OfficeStore,
    prepared: PreparedSource,
    signer: Signer,
    ingested_at: datetime,
    source_id: str,
) -> tuple[SourceRow, list[ClauseRow], list[bytes], list[str], str]:
    """Build the committed source row, clause rows and Merkle commitments."""

    manifest = prepared.manifest
    clauses: list[ClauseRow] = []
    leaves: list[bytes] = []
    clause_ids = clause_ids_for(manifest, prepared.parsed)
    for index, parsed_clause in enumerate(prepared.parsed.clauses):
        clause_id = clause_ids[index]
        payload = clause_leaf_payload(
            tenant_id=manifest.tenant_id,
            region=manifest.region.value,
            source_id=source_id,
            source_identity=manifest.source_identity,
            version_label=manifest.version_label,
            clause_id=clause_id,
            page=parsed_clause.page,
            section=parsed_clause.section,
            start_char=parsed_clause.start_char,
            end_char=parsed_clause.end_char,
            text=parsed_clause.text,
            source_sha256=prepared.source_sha256,
            parser_version=prepared.parsed.parser_version,
        )
        leaves.append(payload)
    leaf_hashes, root = build_tree(leaves)
    for index, (parsed_clause, payload, leaf_hash) in enumerate(zip(prepared.parsed.clauses, leaves, leaf_hashes)):
        clauses.append(
            ClauseRow(
                clause_id=clause_ids[index],
                source_id=source_id,
                clause_index=index,
                page=parsed_clause.page,
                section=parsed_clause.section,
                text=parsed_clause.text,
                start_char=parsed_clause.start_char,
                end_char=parsed_clause.end_char,
                leaf_hash=leaf_hash.hex(),
                restricted=manifest.sensitivity is Sensitivity.RESTRICTED,
            )
        )

    manifest_payload = SignedManifestPayload(
        tenant_id=manifest.tenant_id,
        region=manifest.region,
        source_id=source_id,
        source_identity=manifest.source_identity,
        version_label=manifest.version_label,
        source_type=manifest.source_type,
        source_sha256=prepared.source_sha256,
        merkle_root=root.hex(),
        tree_size=len(leaves),
        parser_version=prepared.parsed.parser_version,
        contract_schema_version=SCHEMA_VERSION,
        sensitivity=manifest.sensitivity,
        office_export=manifest.permissions.office_export,
        hosted_model=manifest.permissions.hosted_model,
        trusted_metadata=manifest,
        ingested_at=ingested_at,
        signer_key_id=signer.key_id,
    )
    source = SourceRow(
        source_id=source_id,
        tenant_id=manifest.tenant_id,
        region=manifest.region.value,
        source_identity=manifest.source_identity,
        version_label=manifest.version_label,
        source_type=manifest.source_type.value,
        subject=manifest.subject.value,
        policy_family=manifest.policy_family,
        authority=manifest.authority.value,
        sensitivity=manifest.sensitivity.value,
        office_export=manifest.permissions.office_export,
        hosted_model=manifest.permissions.hosted_model,
        content_sha256=prepared.content_sha256,
        source_sha256=prepared.source_sha256,
        merkle_root=root.hex(),
        tree_size=len(leaves),
        manifest=manifest,
        manifest_payload=manifest_payload.model_dump(mode="json"),
        manifest_hash=sha256_hex(canonical_json_bytes(manifest_payload)),
        manifest_signature=signer.sign(canonical_json_bytes(manifest_payload)),
        manifest_key_id=signer.key_id,
        parser_version=prepared.parsed.parser_version,
        publication_time=manifest.publication_time,
        effective_from=manifest.effective_from,
        effective_to=manifest.effective_to,
        status="accepted",
        supersedes=manifest.supersedes.model_dump(mode="json") if manifest.supersedes else None,
        ingested_at=ingested_at,
    )
    return source, clauses, leaves, clause_ids, root.hex()


def _claim_ids(manifest: SourceManifest, clause_id: str, index: int) -> tuple[str, str]:
    seed = (
        f"{manifest.tenant_id}|{manifest.region.value}|{manifest.source_identity}|"
        f"{manifest.version_label}|{clause_id}|{index}"
    )
    claim_id = f"claim_{sha256_hex(seed.encode('utf-8'))[:24]}"
    revision_id = f"rev_{sha256_hex((claim_id + '|1').encode('utf-8'))[:24]}"
    return claim_id, revision_id


def _build_claim(
    *,
    store: OfficeStore,
    manifest: SourceManifest,
    source: SourceRow,
    rule: VerifiedRule,
    index: int,
    signer: Signer,
    extraction: ExtractionProvenance,
    status: ClaimStatus = ClaimStatus.ACCEPTED,
    revision_id: str | None = None,
) -> ClaimRevisionRecord:
    claim_id, default_revision_id = _claim_ids(manifest, rule.evidence.clause_id, index)
    revision = ClaimRevision(
        tenant_id=manifest.tenant_id,
        region=manifest.region,
        claim_id=claim_id,
        revision_id=revision_id or default_revision_id,
        subject=rule.proposed.subject,
        scope=rule.proposed.scope,
        rule=rule.proposed.rule,
        authority=manifest.authority,
        policy_family=manifest.policy_family,
        source_id=source.source_id,
        source_identity=manifest.source_identity,
        source_version_label=manifest.version_label,
        source_clause_id=rule.evidence.clause_id,
        valid_from=manifest.effective_from,
        valid_to=manifest.effective_to,
        system_from=source.ingested_at,
        evidence=rule.evidence,
        extraction=extraction,
        status=status,
    )
    return ClaimRevisionRecord(
        payload=revision,
        payload_hash=claim_hash(revision),
        signature=signer.sign(canonical_json_bytes(revision)),
        key_id=signer.key_id,
    )


def _extraction_provenance(
    result: ProviderResult, *, notes: list[str], request: ExtractionRequest, validator_version: str
) -> ExtractionProvenance:
    return ExtractionProvenance(
        mode=result.mode.value,
        provider=result.provider,
        model=result.model,
        prompt_version=request.prompt_version,
        schema_version=request.schema_version,
        cache_key=result.cache_key,
        attempts=result.attempts,
        latency_ms=result.latency_ms,
        usage={k: v for k, v in result.usage.items() if isinstance(v, int)},
        raw_output_sha256=result.raw_output_sha256,
        validator_version=validator_version,
        notes=notes,
    )


def ingest_prepared(
    store: OfficeStore,
    prepared: PreparedSource,
    *,
    mode: Mode,
    service: ModelStageService,
    signer: Signer,
    now: datetime | None = None,
    request_id: str | None = None,
    clause_extension_max: int = 200,
    source_dir: Path | None = None,
) -> IngestionOutcome:
    """Run the full pipeline for one prepared source version."""

    manifest = prepared.manifest
    moment = now or utc_now()
    outcome = IngestionOutcome(stage_modes={"extraction": mode.value})

    if manifest.tenant_id != store.tenant_id:
        raise ManifestSourceMismatch("manifest tenant does not match the authenticated tenant")
    if manifest.region.value != store.region:
        raise ManifestSourceMismatch("manifest region does not match this office")

    existing = store.find_source_version(manifest.source_identity, manifest.version_label)
    if existing is not None:
        # Immutable-version identity covers the exact original bytes and the complete
        # canonical trusted manifest (including effective dates and permissions), not
        # merely the normalized text.  A changed file or changed trusted metadata
        # under the same identifier is rejected so callers cannot believe a new
        # artifact was accepted while the stored commitment still names the old one.
        if existing.source_sha256 != prepared.source_sha256:
            raise VersionPayloadMismatch(
                f"source {manifest.source_identity}/{manifest.version_label} was already ingested "
                "with different original bytes; use a new version identifier"
            )
        existing_manifest_hash = sha256_hex(canonical_json_bytes(existing.manifest))
        incoming_manifest_hash = sha256_hex(canonical_json_bytes(manifest))
        if existing_manifest_hash != incoming_manifest_hash:
            raise VersionPayloadMismatch(
                f"source {manifest.source_identity}/{manifest.version_label} was already ingested "
                "with different trusted manifest metadata; use a new version identifier"
            )
        if existing.content_sha256 != prepared.content_sha256:
            raise VersionPayloadMismatch(
                f"source {manifest.source_identity}/{manifest.version_label} was already ingested "
                "with different content; use a new version identifier"
            )
        outcome.source_id = existing.source_id
        outcome.duplicate = True
        outcome.source_sha256 = existing.source_sha256
        outcome.content_sha256 = existing.content_sha256
        outcome.merkle_root = existing.merkle_root
        outcome.claim_revision_ids = [
            record.payload.revision_id for record in store.claims_for_source(existing.source_id)
        ]
        outcome.warnings.append("duplicate delivery; no new source version was created")
        return outcome

    source_id = new_id("src")
    if source_dir is not None:
        # Keep the immutable original before any database row references it.
        store_original(
            source_dir,
            prepared.raw_bytes,
            prepared.file_extension,
            manifest.region.value,
        )
    source, clauses, leaves, _clause_ids, root_hex = build_source_version(
        store=store, prepared=prepared, signer=signer, ingested_at=moment, source_id=source_id
    )
    outcome.source_id = source_id
    outcome.source_sha256 = prepared.source_sha256
    outcome.content_sha256 = prepared.content_sha256
    outcome.merkle_root = root_hex
    outcome.warnings.extend(prepared.warnings)

    # ------------------------------------------------------------------ extraction
    clause_inputs = [
        ClauseInput(
            clause_id=clause.clause_id,
            page=clause.page,
            section=clause.section,
            text=clause.text,
        )
        for clause in clauses[:clause_extension_max]
    ]
    request = ExtractionRequest(
        tenant_id=manifest.tenant_id,
        region=manifest.region.value,
        source_identity=manifest.source_identity,
        version_label=manifest.version_label,
        source_type=manifest.source_type,
        subject=manifest.subject,
        authority=manifest.authority.value,
        content_sha256=prepared.content_sha256,
        manifest_scope_summary=manifest.scope.model_dump_json(),
        clauses=clause_inputs,
        mode=mode,
        prompt_version=POLICY_EXTRACTION_VERSION if manifest.subject is Subject.GENERAL_POLICY else PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        request_id=request_id or new_id("req"),
        hosted_model_allowed=manifest.permissions.hosted_model,
    )
    result = service.extract(request)
    outcome.provider = result.provider
    outcome.model = result.model
    if result.error_code is not None and result.proposal is None:
        outcome.error_code = result.error_code.value
        outcome.error_detail = result.error_detail
        return outcome

    validation = validate_proposal(
        result.proposal,
        manifest=manifest,
        clauses=[
            ValidatorClause(
                clause_id=clause.clause_id,
                page=clause.page,
                section=clause.section,
                text=clause.text,
                leaf_hash=clause.leaf_hash,
            )
            for clause in clauses
        ],
        manifest_root=root_hex,
    )

    provenance = _extraction_provenance(
        result,
        notes=list(outcome.warnings),
        request=request,
        validator_version=validation.validator_version,
    )

    accepted_records: list[ClaimRevisionRecord] = []
    review_records: list[ClaimRevisionRecord] = []
    for index, verified in enumerate(validation.accepted):
        accepted_records.append(
            _build_claim(
                store=store,
                manifest=manifest,
                source=source,
                rule=verified,
                index=index,
                signer=signer,
                extraction=provenance,
            )
        )

    clause_lookup = {clause.clause_id: clause for clause in clauses}
    review_detail: list[tuple[str, str]] = []
    for review_index, review in enumerate(validation.reviews):
        review_detail.append((review.reason_code, review.detail))
        record = _review_claim(
            store=store,
            manifest=manifest,
            source=source,
            review=review,
            signer=signer,
            extraction=provenance,
            clause_lookup=clause_lookup,
            index=len(accepted_records) + review_index,
        )
        if record is not None:
            review_records.append(record)
    outcome.review_reasons = [reason for reason, _ in review_detail]
    outcome.rejection_reasons = [item.reason_code for item in validation.rejections]

    if manifest.subject is Subject.GENERAL_POLICY and manifest.source_type is SourceType.SLACK:
        # A saved batch may span many timestamps. Bind each extracted statement to
        # its own message time rather than treating every message as the newest.
        messages = parse_slack_payload(prepared.raw_bytes)
        times = {clause.clause_id: message.ts for clause, message in zip(clauses, messages)}
        for record in accepted_records + review_records:
            if manifest.effective_from is None:
                revision = record.payload.model_copy(update={
                    "valid_from": times[record.payload.source_clause_id],
                })
                # Revalidate intervals before signing the corrected immutable claim.
                record.payload = ClaimRevision.model_validate(revision.model_dump())
                record.payload_hash = claim_hash(record.payload)
                record.signature = signer.sign(canonical_json_bytes(record.payload))

    policy_batch = prepare_policy_comparisons(
        store, new_revisions=[record.payload for record in accepted_records],
        new_clauses=clauses, manifest=manifest, service=service, mode=mode,
        request_id=request.request_id,
    )
    if manifest.subject is Subject.GENERAL_POLICY:
        outcome.stage_modes["policy_comparison"] = mode.value
        if len(clauses) > clause_extension_max:
            policy_batch.reviews.append(("policy_extraction_limit", "Not all source clauses were extracted; coverage is incomplete."))
    outcome.review_reasons.extend(code for code, _ in policy_batch.reviews)

    if (
        not accepted_records
        and not validation.reviews
        and not validation.rejections
        and manifest.supersedes is None
    ):
        outcome.error_code = ErrorCode.EXTRACTION_FAILED.value
        outcome.error_detail = "the model returned no rules for this source"
        return outcome

    # ------------------------------------------------------ transactional commit
    with store.db.transaction() as connection:
        store.insert_source(connection, source=source)
        store.insert_clauses(connection, clauses)
        store.upsert_node(
            connection,
            node_id=f"document:{manifest.source_identity}",
            node_type="document",
            label=manifest.source_identity,
            attributes={"source_type": manifest.source_type.value, "region": manifest.region.value},
            restricted=source.restricted,
        )
        store.upsert_node(
            connection,
            node_id=f"source:{source_id}",
            node_type="version",
            label=f"{manifest.source_identity} {manifest.version_label}",
            attributes={
                "effective_from": canonical_datetime(manifest.effective_from)
                if manifest.effective_from
                else "",
                "authority": manifest.authority.value,
                "policy_family": manifest.policy_family,
                "sensitivity": manifest.sensitivity.value,
            },
            restricted=source.restricted,
        )
        store.upsert_edge(
            connection,
            edge_type="IN_VERSION",
            from_node_id=f"source:{source_id}",
            to_node_id=f"document:{manifest.source_identity}",
        )
        for clause in clauses:
            node_id = f"clause:{clause.clause_id}"
            store.upsert_node(
                connection,
                node_id=node_id,
                node_type="clause" if manifest.source_type is SourceType.PDF else "message",
                label=clause.section or f"message {clause.clause_index + 1}",
                attributes={"page": str(clause.page), "leaf_hash": clause.leaf_hash},
                restricted=clause.restricted,
            )
            store.upsert_edge(
                connection,
                edge_type="IN_VERSION",
                from_node_id=node_id,
                to_node_id=f"source:{source_id}",
            )
        for record in accepted_records + review_records:
            store.insert_claim(connection, record)
            payload = record.payload
            store.upsert_node(
                connection,
                node_id=f"revision:{payload.revision_id}",
                node_type="claim_revision",
                label=f"{payload.subject.value}: {rule_summary(payload.rule)}",
                attributes={
                    "claim_id": payload.claim_id,
                    "authority": payload.authority.value,
                    "status": payload.status.value,
                    "payload_hash": record.payload_hash,
                    "policy_family": payload.policy_family,
                },
                restricted=source.restricted,
            )
            store.upsert_edge(
                connection,
                edge_type="EXTRACTED_FROM",
                from_node_id=f"revision:{payload.revision_id}",
                to_node_id=f"clause:{payload.evidence.clause_id}",
            )
            store.upsert_edge(
                connection,
                edge_type="IN_VERSION",
                from_node_id=f"revision:{payload.revision_id}",
                to_node_id=f"source:{source_id}",
            )
        for review in validation.reviews:
            store.insert_claim_review(
                source_id=source_id,
                reason_code=review.reason_code,
                detail={
                    "detail": review.detail,
                    "clause_id": review.clause_id or "",
                    "quote": review.quote or "",
                },
                subject=review.subject.value if review.subject else None,
                connection=connection,
                created_at=moment,
            )
        for code, detail in policy_batch.reviews:
            store.insert_claim_review(
                source_id=source_id, reason_code=code, detail={"detail": detail},
                subject=manifest.subject.value, connection=connection, created_at=moment,
            )

        supersession = apply_manifest_supersession(
            connection,
            store,
            manifest=manifest,
            new_source_id=source_id,
            new_revisions=accepted_records,
            signer=signer,
            now=moment,
        )
        outcome.warnings.extend(detail for _code, detail in supersession.review_items)
        outcome.review_reasons.extend(code for code, _detail in supersession.review_items)
        for code, detail in supersession.review_items:
            review_detail: dict[str, Any] = {"detail": detail}
            if code == "pending_replacement":
                review_detail.update(
                    {
                        "target_source_id": supersession.target_source_id,
                        "replacement_source_id": supersession.replacement_source_id,
                        "affected_revision_ids": supersession.pending_revision_ids,
                        "missing_clause_ids": supersession.pending_missing_clause_ids,
                        "effective_from": canonical_datetime(
                            manifest.supersedes.effective_from
                        ),
                        "replacement_scope": manifest.supersedes.replaced_scope.model_dump(
                            mode="json"
                        ),
                    }
                )
            store.insert_claim_review(
                source_id=source_id,
                reason_code=code,
                detail=review_detail,
                subject=manifest.subject.value,
                connection=connection,
                created_at=moment,
            )

        finding_types = publish_findings(
            connection,
            store,
            new_revisions=[record.payload for record in accepted_records],
            signer=signer,
            now=moment,
        )
        finding_types.extend(publish_policy_batch(
            connection, store, policy_batch, signer=signer, now=moment,
        ))
        if supersession.closed_revision_ids:
            finding_types.extend(
                reevaluate_findings_for_revisions(
                    connection,
                    store,
                    closed_revision_ids=supersession.closed_revision_ids,
                    signer=signer,
                    now=moment,
                )
            )
        outcome.finding_types = finding_types
        store.record_model_call(
            connection,
            call_id=new_id("call"),
            job_id=None,
            source_id=source_id,
            mode=result.mode.value,
            provider=result.provider,
            route=result.route,
            model=result.model,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            attempts=result.attempts,
            latency_ms=result.latency_ms,
            usage={k: v for k, v in result.usage.items() if isinstance(v, int)},
            status="succeeded" if result.ok else (result.error_code.value if result.error_code else "failed"),
            error_code=result.error_code.value if result.error_code else None,
            cache_key=result.cache_key,
            raw_output_sha256=result.raw_output_sha256,
        )
        for comparison_request, comparison_result in policy_batch.calls:
            store.record_model_call(
                connection, call_id=new_id("call"), job_id=None, source_id=source_id,
                mode=comparison_result.mode.value, provider=comparison_result.provider,
                route=comparison_result.route, model=comparison_result.model,
                prompt_version=comparison_request.prompt_version,
                schema_version=comparison_request.schema_version,
                attempts=comparison_result.attempts, latency_ms=comparison_result.latency_ms,
                usage=comparison_result.usage,
                status="succeeded" if comparison_result.ok else "failed",
                error_code=comparison_result.error_code.value if comparison_result.error_code else None,
                cache_key=comparison_result.cache_key,
                raw_output_sha256=comparison_result.raw_output_sha256,
            )

    outcome.created = True
    outcome.claim_revision_ids = [
        record.payload.revision_id for record in accepted_records + review_records
    ]
    return outcome


def _review_claim(
    *,
    store: OfficeStore,
    manifest: SourceManifest,
    source: SourceRow,
    review: ReviewItem,
    signer: Signer,
    extraction: ExtractionProvenance,
    clause_lookup: dict[str, ClauseRow],
    index: int,
) -> ClaimRevisionRecord | None:
    """Persist a signed ``needs_review`` claim when evidence is resolvable."""

    if review.proposed is None or review.quote is None:
        return None
    clause = clause_lookup.get(review.clause_id or "")
    if clause is None:
        matches = [item for item in clause_lookup.values() if review.quote in item.text]
        if len(matches) != 1:
            return None
        clause = matches[0]
    offset = clause.text.find(review.quote)
    if offset < 0:
        return None
    evidence = VerifiedEvidence(
        clause_id=clause.clause_id,
        page=clause.page,
        section=clause.section,
        quote=review.quote,
        start_char=offset,
        end_char=offset + len(review.quote),
        leaf_hash=clause.leaf_hash,
        manifest_root=source.merkle_root,
    )
    rule = VerifiedRule(proposed=review.proposed, evidence=evidence, clause=None)  # type: ignore[arg-type]
    record = _build_claim(
        store=store,
        manifest=manifest,
        source=source,
        rule=rule,
        # Each review proposal needs its own slot, including multiple statements
        # with the same reason and passage. Accepted slots precede review slots.
        index=index,
        signer=signer,
        extraction=extraction,
        status=ClaimStatus.NEEDS_REVIEW,
    )
    return record
