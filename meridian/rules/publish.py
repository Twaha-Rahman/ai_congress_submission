"""Finding publication: classification results become signed, immutable snapshots.

Findings are deduplicated on the ordered pair of claim revisions plus the finding
type.  Alert state (review events) is kept separate from the immutable evidence, and
re-evaluating a finding appends a new snapshot instead of editing the old one.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Sequence

from ..contracts.common import ExplanationCode, FindingType, Subject, utc_now
from ..contracts.claims import ClaimRevision
from ..contracts.findings import FindingEvidenceRef, FindingPayload, ComparisonResult
from ..integrity.bundles import claim_hash
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..integrity.signing import Signer
from ..rules.compare import ClaimView, compare_claims
from ..storage.store import OfficeStore


def finding_key(finding_type: FindingType, left_revision_id: str, right_revision_id: str) -> str:
    a, b = sorted([left_revision_id, right_revision_id])
    return f"{finding_type.value}|{a}|{b}"


def finding_id_for(key: str) -> str:
    return f"find_{sha256_hex(key.encode('utf-8'))[:24]}"


def _should_persist(result: ComparisonResult) -> bool:
    if result.finding_type is FindingType.NOT_COMPARABLE:
        return False
    if (
        result.finding_type is FindingType.COMPATIBLE_DIFFERENCE
        and result.explanation_code is ExplanationCode.ADVICE_ADEQUATE
    ):
        return False
    return True


def _explicit_supersession(left: ClaimView, right: ClaimView) -> bool:
    if left.closure_kind is not None and left.superseding_source_id == right.revision.source_id:
        return True
    if right.closure_kind is not None and right.superseding_source_id == left.revision.source_id:
        return True
    return False


def compare_pair(
    left: ClaimView, right: ClaimView, views: Sequence[ClaimView]
) -> ComparisonResult:
    return compare_claims(
        left,
        right,
        staleness_candidates=views,
        explicit_supersession=_explicit_supersession(left, right),
    )


def build_finding_payload(
    store: OfficeStore,
    result: ComparisonResult,
    views_by_id: dict[str, ClaimView],
    *,
    now: datetime,
) -> FindingPayload:
    key = finding_key(result.finding_type, result.left_revision_id, result.right_revision_id)
    evidence: list[FindingEvidenceRef] = []
    for revision_id in result.claim_revision_ids():
        view = views_by_id.get(revision_id)
        if view is None:
            continue
        revision = view.revision
        evidence.append(
            FindingEvidenceRef(
                claim_revision_id=revision.revision_id,
                clause_id=revision.evidence.clause_id,
                source_id=revision.source_id,
                page=revision.evidence.page,
                section=revision.evidence.section,
                quote=revision.evidence.quote,
                start_char=revision.evidence.start_char,
                end_char=revision.evidence.end_char,
                manifest_root=revision.evidence.manifest_root,
            )
        )
    interval = result.affected_valid_interval
    if interval is None:
        from ..contracts.common import TimeInterval

        interval = TimeInterval(start=None, end=None)
    scope = result.affected_scope
    if scope is None:
        view = views_by_id.get(result.left_revision_id)
        assert view is not None
        scope = view.revision.scope
    return FindingPayload(
        tenant_id=store.tenant_id,
        region=store.region,  # type: ignore[arg-type]
        finding_id=finding_id_for(key),
        finding_key=key,
        finding_type=result.finding_type,
        severity=result.severity,
        explanation_code=result.explanation_code,
        subject=result.subject,
        claim_revision_ids=list(result.claim_revision_ids()),
        affected_scope=scope,
        affected_valid_interval=interval,
        authority_basis=result.authority_basis or "",
        evidence=evidence,
        staleness_link_revision_ids=list(result.staleness_link_revision_ids),
        detail=dict(result.detail),
        created_at=now,
    )


def publish_comparison(
    connection: sqlite3.Connection,
    store: OfficeStore,
    result: ComparisonResult,
    *,
    signer: Signer,
    now: datetime,
    existing_keys: set[str],
    force_snapshot: bool = False,
) -> str | None:
    """Persist one comparison result as a signed finding snapshot."""

    if not _should_persist(result):
        return None
    key = finding_key(result.finding_type, result.left_revision_id, result.right_revision_id)
    if key in existing_keys and not force_snapshot:
        return None
    views = store.claim_views(connection=connection, limit=None)
    views_by_id = {view.revision_id: view for view in views}
    payload = build_finding_payload(store, result, views_by_id, now=now)
    payload_bytes = canonical_json_bytes(payload)
    snapshot_id = store.insert_finding_snapshot(
        connection,
        payload=payload,
        signature=signer.sign(payload_bytes),
        key_id=signer.key_id,
        alert=result.alert,
    )
    if force_snapshot:
        connection.execute(
            "UPDATE finding_snapshots SET superseded_by = ? WHERE finding_id = ? AND "
            "snapshot_id != ? AND superseded_by IS NULL",
            (snapshot_id, payload.finding_id, snapshot_id),
        )
    existing_keys.add(key)
    store.upsert_node(
        connection,
        node_id=f"finding:{payload.finding_id}",
        node_type="finding",
        label=f"{payload.finding_type.value} ({payload.severity.value})",
        attributes={
            "explanation_code": payload.explanation_code.value,
            "alert": str(result.alert),
            "snapshot_id": snapshot_id,
        },
        restricted=False,
    )
    for revision_id in payload.claim_revision_ids:
        store.upsert_edge(
            connection,
            edge_type="FINDS_BETWEEN",
            from_node_id=f"finding:{payload.finding_id}",
            to_node_id=f"revision:{revision_id}",
        )
    return snapshot_id


def publish_findings(
    connection: sqlite3.Connection,
    store: OfficeStore,
    *,
    new_revisions: Sequence[ClaimRevision],
    signer: Signer,
    now: datetime | None = None,
) -> list[str]:
    """Compare every newly accepted revision against existing claims."""

    moment = now or utc_now()
    views = store.claim_views(connection=connection)
    views_by_id = {view.revision_id: view for view in views}
    existing_keys = store.finding_keys(connection=connection)
    created: list[str] = []
    for revision in new_revisions:
        if revision.subject is Subject.GENERAL_POLICY:
            continue  # General comparisons are retrieved and run before the write transaction.
        left = views_by_id.get(revision.revision_id)
        if left is None:
            continue
        for other in views:
            if other.revision_id == revision.revision_id:
                continue
            if other.revision.claim_id == revision.claim_id:
                continue
            if other.carried_forward:
                # A carried revision is the same retired claim under corrected
                # effective history; re-comparing it would republish historical
                # overlaps as new findings.
                continue
            result = compare_pair(left, other, views)
            snapshot = publish_comparison(
                connection,
                store,
                result,
                signer=signer,
                now=moment,
                existing_keys=existing_keys,
            )
            if snapshot is not None:
                created.append(result.finding_type.value)
    return created


def reevaluate_findings_for_revisions(
    connection: sqlite3.Connection,
    store: OfficeStore,
    *,
    closed_revision_ids: Sequence[str],
    signer: Signer,
    now: datetime | None = None,
) -> list[str]:
    """Re-run affected findings when scope or effective history changes."""

    moment = now or utc_now()
    closed = set(closed_revision_ids)
    if not closed:
        return []
    affected = [
        record
        for record in store.list_findings(connection=connection, limit=1000)
        if closed.intersection(record.payload.claim_revision_ids)
    ]
    views = store.claim_views(connection=connection)
    views_by_id = {view.revision_id: view for view in views}
    existing_keys = store.finding_keys(connection=connection)
    updated: list[str] = []
    for record in affected:
        ids = record.payload.claim_revision_ids
        if len(ids) != 2:
            continue
        left = views_by_id.get(ids[0])
        right = views_by_id.get(ids[1])
        if left is None or right is None:
            continue
        if left.revision.subject is Subject.GENERAL_POLICY:
            # Retain the finding identity/reviews while appending a signed snapshot
            # explaining why the old semantic assessment is no longer current.
            from .general import retire_policy_assessment

            retire_policy_assessment(connection, store, record, signer=signer, now=moment)
            continue
        result = compare_pair(left, right, views)
        old_key = record.payload.finding_key
        new_key = finding_key(result.finding_type, result.left_revision_id, result.right_revision_id)
        if new_key == old_key:
            snapshot = publish_comparison(
                connection,
                store,
                result,
                signer=signer,
                now=moment,
                existing_keys=existing_keys,
                force_snapshot=True,
            )
            if snapshot:
                updated.append(result.finding_type.value)
        elif _should_persist(result):
            snapshot = publish_comparison(
                connection,
                store,
                result,
                signer=signer,
                now=moment,
                existing_keys=existing_keys,
            )
            if snapshot:
                store.upsert_edge(
                    connection,
                    edge_type="SUPERSEDES",
                    from_node_id=f"finding:{finding_id_for(new_key)}",
                    to_node_id=f"finding:{record.payload.finding_id}",
                    attributes={"reason": "re-evaluated after effective-history change"},
                )
                updated.append(result.finding_type.value)
    return updated
