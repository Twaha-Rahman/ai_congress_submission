"""Evidence bundles and independent source-copy verification.

A bundle is assembled from stored, already-signed records only: nothing is
re-serialised from model output and nothing is fabricated for components the caller
is not allowed to read.  Restricted clause text is withheld while the commitment
proof is still carried, so a verifier reports ``not_checked`` instead of inventing a
result.
"""

from __future__ import annotations

from datetime import datetime

from ..contracts.claims import ClaimRevision
from ..contracts.common import (
    CheckStatus,
    Sensitivity,
    SourceType,
    utc_now,
)
from ..contracts.qa import AnswerRecord
from ..contracts.verification import (
    CheckResult,
    ClaimBundleEntry,
    ClauseProof,
    EvidenceBundle,
    ManifestBundleEntry,
    VerificationReport,
)
from ..ingestion.pdf import parse_pdf_bytes
from ..ingestion.slack import parse_slack_payload, slack_to_document
from ..integrity.bundles import (
    BundleClause,
    build_clause_proof,
    clause_leaf_payload,
)
from ..integrity.canonical import sha256_hex
from ..integrity.merkle import build_tree, inclusion_path
from ..storage.store import OfficeStore, new_id


def _check(name: str, status: CheckStatus, reason: str | None = None, **detail: str) -> CheckResult:
    return CheckResult(check=name, status=status, reason=reason, detail=detail)


def _leaf_hashes_for_source(
    store: OfficeStore, source_id: str, *, tenant_id: str
) -> tuple[list[str], str]:
    """Recompute the clause leaves in commitment order from stored rows."""

    source = store.get_source(source_id)
    assert source is not None
    leaves: list[bytes] = []
    for clause in store.clauses_for_source(source_id):
        leaves.append(
            clause_leaf_payload(
                tenant_id=tenant_id,
                region=source.region,
                source_id=source.source_id,
                source_identity=source.source_identity,
                version_label=source.version_label,
                clause_id=clause.clause_id,
                page=clause.page,
                section=clause.section,
                start_char=clause.start_char,
                end_char=clause.end_char,
                text=clause.text,
                source_sha256=source.source_sha256,
                parser_version=source.parser_version,
            )
        )
    leaf_hashes, root = build_tree(leaves)
    return [item.hex() for item in leaf_hashes], root.hex()


def build_bundle(
    store: OfficeStore,
    answer: AnswerRecord,
    *,
    now: datetime | None = None,
) -> EvidenceBundle:
    """Assemble a self-contained bundle for one stored answer."""

    moment = now or utc_now()
    manifest_entries: dict[str, ManifestBundleEntry] = {}
    leaf_hashes_by_source: dict[str, list[str]] = {}
    claim_entries: list[ClaimBundleEntry] = []
    remote_references: list[str] = []
    seen_revisions: set[str] = set()

    for citation in answer.payload.citations:
        revision_id = citation.claim_revision_id
        if revision_id in seen_revisions:
            continue
        seen_revisions.add(revision_id)
        if citation.remote:
            remote_references.append(revision_id)
            continue
        record = store.get_claim(revision_id)
        if record is None:
            raise ValueError(
                f"local citation {revision_id} has no stored claim; refusing to fabricate a "
                "bundle entry"
            )
        payload: ClaimRevision = record.payload
        source = store.get_source(payload.source_id)
        if source is None:
            raise ValueError(
                f"local citation {revision_id} references a source that is not stored"
            )

        if source.source_id not in manifest_entries:
            leaf_hashes, root_hex = _leaf_hashes_for_source(
                store, source.source_id, tenant_id=store.tenant_id
            )
            if root_hex != source.merkle_root:  # pragma: no cover - defensive
                raise ValueError(
                    f"recomputed Merkle root for source {source.source_id} does not match the "
                    "committed root; refusing to build a bundle from inconsistent storage"
                )
            leaf_hashes_by_source[source.source_id] = leaf_hashes
            manifest_entries[source.source_id] = ManifestBundleEntry(
                source_id=source.source_id,
                region=source.manifest.region,
                source_identity=source.source_identity,
                version_label=source.version_label,
                source_sha256=source.source_sha256,
                merkle_root=source.merkle_root,
                tree_size=source.tree_size,
                manifest_payload=source.manifest_payload,
                manifest_hash=source.manifest_hash,
                signature=source.manifest_signature,
                key_id=source.manifest_key_id,
                clause_proofs=[],
                clauses=[],
                clauses_disclosed=source.sensitivity != Sensitivity.RESTRICTED.value,
                sensitivity=source.sensitivity,
                office_export=source.office_export,
            )

        entry = manifest_entries[payload.source_id]
        leaf_hashes = leaf_hashes_by_source[payload.source_id]
        clause_row = store.get_clause(payload.evidence.clause_id)
        if clause_row is None:
            raise ValueError(
                f"claim {payload.revision_id} cites clause {payload.evidence.clause_id} "
                "whose evidence is not stored; refusing to emit a placeholder proof"
            )
        if clause_row.clause_id != payload.evidence.clause_id:
            raise ValueError("stored clause id does not match the claim evidence locator")
        if not (0 <= clause_row.clause_index < len(leaf_hashes)):
            raise ValueError("stored clause index is outside the committed tree")
        if leaf_hashes[clause_row.clause_index] != payload.evidence.leaf_hash:
            raise ValueError(
                f"claim {payload.revision_id} evidence leaf hash does not match the "
                "recomputed clause commitment"
            )
        if source.merkle_root != payload.evidence.manifest_root:
            raise ValueError(
                f"claim {payload.revision_id} evidence root does not match the signed "
                "source manifest root"
            )
        if not (
            0 <= payload.evidence.start_char <= payload.evidence.end_char <= len(clause_row.text)
        ):
            raise ValueError("claim evidence offsets are outside the stored clause text")
        if clause_row.text[payload.evidence.start_char : payload.evidence.end_char] != (
            payload.evidence.quote
        ):
            raise ValueError(
                "claim evidence quote does not match the stored clause text at the recorded offsets"
            )
        index = clause_row.clause_index
        siblings = [
            item.hex()
            for item in inclusion_path([bytes.fromhex(h) for h in leaf_hashes], index)
        ]
        proof = build_clause_proof(
            clause_id=clause_row.clause_id,
            leaf_hash_hex=leaf_hashes[index],
            index=index,
            tree_size=len(leaf_hashes),
            siblings_hex=siblings,
            merkle_root=source.merkle_root,
        )
        entry.clause_proofs.append(proof)
        clause_disclosed = False
        if entry.clauses_disclosed:
            entry.clauses.append(
                BundleClause(
                    clause_id=clause_row.clause_id,
                    page=clause_row.page,
                    section=clause_row.section,
                    start_char=clause_row.start_char,
                    end_char=clause_row.end_char,
                    text=clause_row.text,
                )
            )
            clause_disclosed = True

        claim_entries.append(
            ClaimBundleEntry(
                claim=payload,
                claim_hash=record.payload_hash,
                signature=record.signature,
                key_id=record.key_id,
                extraction=payload.extraction,
                clause_proof=proof,
                clause_disclosed=clause_disclosed,
            )
        )

    manifests = list(manifest_entries.values())

    return EvidenceBundle(
        bundle_id=new_id("bundle"),
        tenant_id=store.tenant_id,
        region=store.region,  # type: ignore[arg-type]
        answer=answer.payload,
        answer_hash=answer.payload_hash,
        answer_signature=answer.signature,
        answer_key_id=answer.key_id,
        manifests=manifests,
        claims=claim_entries,
        remote_references=sorted(remote_references),
        created_at=moment,
    )


def verify_source_copy(
    store: OfficeStore,
    source_id: str,
    supplied_bytes: bytes,
    *,
    now: datetime | None = None,
) -> VerificationReport:
    """Compare a supplied copy against the committed source; separate checks."""

    moment = now or utc_now()
    checks: list[CheckResult] = []
    source = store.get_source(source_id)
    if source is None:
        return VerificationReport(
            tenant_id=store.tenant_id,
            region=store.region,  # type: ignore[arg-type]
            target_type="source",
            target_id=source_id,
            checks=[
                _check("source_present", CheckStatus.FAILED, "no such source in this office store")
            ],
            generated_at=moment,
        )

    supplied_hash = sha256_hex(supplied_bytes)
    if supplied_hash == source.source_sha256:
        checks.append(_check("source_file_hash", CheckStatus.PASSED))
    else:
        checks.append(
            _check(
                "source_file_hash",
                CheckStatus.FAILED,
                "supplied bytes do not match the committed raw-source hash",
                expected=source.source_sha256,
                computed=supplied_hash,
            )
        )

    try:
        if source.source_type == SourceType.PDF.value:
            parsed = parse_pdf_bytes(supplied_bytes)
            normalized = parsed.normalized_text()
            parser_version = parsed.parser_version
        elif source.source_type == SourceType.SLACK.value:
            parsed = slack_to_document(parse_slack_payload(supplied_bytes))
            normalized = parsed.normalized_text()
            parser_version = parsed.parser_version
        else:  # pragma: no cover - only pdf/slack exist in the MVP
            checks.append(
                _check("content_normalized_text", CheckStatus.NOT_CHECKED, "unknown source type")
            )
            normalized = None
            parser_version = ""
    except Exception as exc:  # noqa: BLE001 - supplied copy may be unparseable
        checks.append(
            _check(
                "content_normalized_text",
                CheckStatus.FAILED,
                f"supplied copy could not be parsed: {type(exc).__name__}",
            )
        )
        normalized = None
        parser_version = ""

    if normalized is not None:
        content_hash = sha256_hex(normalized.encode("utf-8"))
        if content_hash == source.content_sha256:
            checks.append(_check("content_normalized_text", CheckStatus.PASSED))
        else:
            checks.append(
                _check(
                    "content_normalized_text",
                    CheckStatus.FAILED,
                    "normalized text of the supplied copy differs from the committed content",
                    expected=source.content_sha256,
                    computed=content_hash,
                )
            )

    stored_clauses = store.clauses_for_source(source.source_id)
    if normalized is not None:
        check_leaf_payloads: list[bytes] = []
        mismatches = 0
        count_mismatch = len(stored_clauses) != len(parsed.clauses)
        for stored, supplied in zip(stored_clauses, parsed.clauses):
            payload = clause_leaf_payload(
                tenant_id=store.tenant_id,
                region=source.region,
                source_id=source.source_id,
                source_identity=source.source_identity,
                version_label=source.version_label,
                clause_id=stored.clause_id,
                page=supplied.page,
                section=supplied.section,
                start_char=supplied.start_char,
                end_char=supplied.end_char,
                text=supplied.text,
                source_sha256=source.source_sha256,
                parser_version=parser_version,
            )
            check_leaf_payloads.append(payload)
            if supplied.text != stored.text:
                mismatches += 1
        if count_mismatch or mismatches:
            checks.append(
                _check(
                    "clause_text_match",
                    CheckStatus.FAILED,
                    f"{mismatches} clause(s) differ; clause count match: {not count_mismatch}",
                )
            )
        else:
            checks.append(
                _check("clause_text_match", CheckStatus.PASSED, None, checked=str(len(stored_clauses)))
            )
        recomputed_root = build_tree(check_leaf_payloads)[1].hex()
        if recomputed_root == source.merkle_root:
            checks.append(_check("merkle_root_match", CheckStatus.PASSED))
        else:
            checks.append(
                _check(
                    "merkle_root_match",
                    CheckStatus.FAILED,
                    "commitment tree recomputed from the supplied copy does not match the "
                    "committed root",
                )
            )

    return VerificationReport(
        tenant_id=store.tenant_id,
        region=store.region,  # type: ignore[arg-type]
        target_type="source",
        target_id=source_id,
        checks=checks,
        generated_at=moment,
    )


__all__ = ["build_bundle", "verify_source_copy"]
