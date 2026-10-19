"""Strict typed federation: signed exports, pinned-key verification and import.

Only allowlisted enums, numbers, opaque identifiers, commitments and signatures cross
the office boundary.  Exports are signed by the source office and verified by the
recipient against pinned public keys.  Imported claims live in a separate provenance
namespace: they are never local source documents and their clause text is not
disclosed, so remote clause inclusion stays ``not_checked``.
"""

from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Sequence

from ..contracts.claims import ClaimRevision
from ..contracts.common import (
    ClaimOrigin,
    ErrorCode,
    OfficeRegion,
    RuleKind,
    Sensitivity,
    Subject,
    TimeInterval,
    utc_now,
)
from ..contracts.extraction import ExtractionProvenance, VerifiedEvidence
from ..contracts.federation import (
    ExportClaim,
    FederationExport,
    FederationExportPayload,
    FederationSubquery,
    LoanTarget,
    RecordTarget,
)
from ..contracts.qa import TargetFacts
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..integrity.signing import PinnedKeyRegistry, verify_with_registry
from ..rules.compare import ClaimView
from ..rules.intervals import scope_matches_target
from ..rules.values import REQUIREMENT_KINDS
from ..storage.store import OfficeStore
from ..temporal.snapshots import select_snapshot

REMOTE_NAMESPACE = "remote"
REMOTE_CLAUSE_PLACEHOLDER = "not_disclosed"


class ExportDenied(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


class RemoteClaimConflict(ValueError):
    """An imported revision already exists with different signed claim content."""


class UnknownRemoteSnapshot(ValueError):
    """A caller-supplied export snapshot id is not known at this office."""


class StaleRemoteSnapshot(ValueError):
    """A caller-supplied export snapshot is not the latest one known at ``known_at``."""


def target_fingerprint(target) -> str:
    """Canonical fingerprint binding an export to one exact typed target."""

    return sha256_hex(canonical_json_bytes(target))


def target_fingerprint_for_facts(target: TargetFacts) -> str:
    """Fingerprint a query API target using the canonical federation contract."""

    if target.subject is Subject.LOAN_APPROVAL:
        typed = LoanTarget(
            loan_type=target.loan_type,
            currency=target.currency,
            origin_office=target.origin_office,
            amount_minor=target.amount_minor,
        )
    else:
        typed = RecordTarget(
            record_class=target.record_class,
            origin_office=target.origin_office or OfficeRegion.DHAKA,
            processing_office=target.processing_office or OfficeRegion.DHAKA,
            product=target.product,
            starting_event=target.starting_event,
        )
    return target_fingerprint(typed)


def _target_facts(query: FederationSubquery) -> TargetFacts:
    target = query.target
    if isinstance(target, LoanTarget):
        return TargetFacts(
            subject=Subject.LOAN_APPROVAL,
            amount_minor=target.amount_minor,
            currency=target.currency,
            loan_type=target.loan_type,
            origin_office=target.origin_office,
        )
    assert isinstance(target, RecordTarget)
    return TargetFacts(
        subject=Subject.RECORD_RETENTION,
        record_class=target.record_class,
        origin_office=target.origin_office,
        processing_office=target.processing_office,
        product=target.product,
        starting_event=target.starting_event,
    )


def build_export(
    store: OfficeStore,
    *,
    query: FederationSubquery,
    signer,
    now: datetime | None = None,
) -> FederationExport:
    """Apply this office's own export policy, then serialize signed typed claims."""

    moment = now or utc_now()
    views = store.claim_views(subject=query.subject.value)
    snapshot = select_snapshot(
        views, valid_at=query.valid_at, known_at=query.known_at, subject=query.subject
    )
    facts = _target_facts(query)
    applicable = [
        view for view in snapshot if scope_matches_target(view.revision.scope, facts)
    ]

    exported: list[ExportClaim] = []
    commitments: set[str] = set()
    withheld = 0
    reasons: set[str] = set()
    for view in applicable:
        revision = view.revision
        source = store.get_source(revision.source_id)
        if source is None:
            withheld += 1
            reasons.add("source_metadata_unavailable")
            continue
        if source.restricted or not source.office_export:
            withheld += 1
            reasons.add(
                "egress_denied_restricted_source"
                if source.restricted
                else "egress_denied_source_permission"
            )
            continue
        record = store.get_claim(revision.revision_id)
        payload_hash = record.payload_hash if record else ""
        exported.append(
            ExportClaim(
                claim_revision_id=revision.revision_id,
                claim_id=revision.claim_id,
                subject=revision.subject,
                scope=revision.scope,
                rule=revision.rule,
                authority=revision.authority,
                policy_family=revision.policy_family,
                valid_from=revision.valid_from,
                valid_to=revision.valid_to,
                system_from=revision.system_from,
                system_to=view.system_to,
                claim_payload_hash=payload_hash,
                manifest_root=revision.evidence.manifest_root,
                source_ref=revision.source_id,
                source_kind=source.source_type,
            )
        )
        commitments.add(revision.evidence.manifest_root)
        commitments.add(payload_hash)

    payload = FederationExportPayload(
        tenant_id=store.tenant_id,
        origin_region=OfficeRegion(store.region),
        request_id=query.request_id,
        subject=query.subject,
        valid_at=query.valid_at,
        known_at=query.known_at,
        target_fingerprint=target_fingerprint(query.target),
        claims=exported,
        commitments=sorted(item for item in commitments if item),
        withheld_restricted=withheld,
        not_checked=["clause_inclusion"],
        reason_codes=sorted(reasons),
        complete=True,
        signer_key_id=signer.key_id,
        generated_at=moment,
    )
    payload_bytes = canonical_json_bytes(payload)
    return FederationExport(
        payload=payload,
        payload_hash=sha256_hex(payload_bytes),
        signature=signer.sign(payload_bytes),
        key_id=signer.key_id,
    )


def verify_export(
    export: FederationExport,
    *,
    registry: PinnedKeyRegistry,
    tenant_id: str,
    expected_origin: str | None = None,
    expected_request_id: str | None = None,
    expected_target_fingerprint: str | None = None,
    expected_valid_at: datetime | None = None,
    expected_known_at: datetime | None = None,
) -> tuple[FederationExportPayload | None, list[str]]:
    """Re-validate the received schema and signature against pinned keys.

    Optional expected values bind the signed export to the exact request that was
    made: request id, canonical target fingerprint, and the two time snapshots.
    Any mismatch makes the whole export unusable for that request.
    """

    errors: list[str] = []
    payload = export.payload
    payload_bytes = canonical_json_bytes(payload)
    if sha256_hex(payload_bytes) != export.payload_hash:
        errors.append("export payload hash does not match the serialized payload")
    ok, reason = verify_with_registry(
        payload_bytes, export.signature, export.key_id, registry
    )
    if not ok:
        errors.append(reason or "export signature verification failed")
    if payload.signer_key_id != export.key_id:
        errors.append("export key id mismatch between payload and envelope")
    if payload.tenant_id != tenant_id:
        errors.append("export tenant does not match the receiving tenant")
    if expected_origin is not None and payload.origin_region.value != expected_origin:
        errors.append(
            f"export origin {payload.origin_region.value} does not match the expected "
            f"origin {expected_origin}"
        )
    pinned = registry.get(export.key_id)
    if pinned is not None and expected_origin is not None:
        if pinned.region.upper() != expected_origin.upper():
            errors.append(
                f"pinned key {export.key_id!r} belongs to region {pinned.region}, not "
                f"{expected_origin}"
            )
    if expected_request_id is not None and payload.request_id != expected_request_id:
        errors.append(
            f"export request id {payload.request_id!r} does not match the requested "
            f"request id {expected_request_id!r}"
        )
    if (
        expected_target_fingerprint is not None
        and payload.target_fingerprint != expected_target_fingerprint
    ):
        errors.append("export target fingerprint does not match the requested target")
    if expected_valid_at is not None and payload.valid_at != expected_valid_at:
        errors.append("export valid_at does not match the requested valid_at")
    if expected_known_at is not None and payload.known_at != expected_known_at:
        errors.append("export known_at does not match the requested known_at")
    return (payload if not errors else None), errors


def snapshot_id_for(payload: FederationExportPayload, export_hash: str) -> str:
    """Deterministic recipient-side snapshot id for one verified export."""

    return f"rsnap_{payload.origin_region.value.lower()}_{payload.request_id}_{export_hash[:12]}"


def import_export(
    store: OfficeStore,
    *,
    export: FederationExport,
    payload: FederationExportPayload,
    received_at: datetime | None = None,
) -> int:
    """Store remote claims and the exact export snapshot that carried them.

    The snapshot is what later queries select from: claims absent from the latest
    complete snapshot are never treated as current merely because they were imported
    earlier.
    """

    moment = received_at or utc_now()
    imported = 0
    snapshot_id = snapshot_id_for(payload, export.payload_hash)
    with store.db.transaction() as connection:
        existing_snapshot = connection.execute(
            "SELECT snapshot_id, export_payload_hash FROM remote_export_snapshots "
            "WHERE tenant_id = ? AND region = ? AND export_payload_hash = ?",
            (store.tenant_id, store.region, export.payload_hash),
        ).fetchone()
        if existing_snapshot is None:
            connection.execute(
                """
                INSERT INTO remote_export_snapshots (
                    snapshot_id, tenant_id, region, origin_region, request_id, subject,
                    target_fingerprint, valid_at, known_at, export_payload_hash,
                    export_signature, export_key_id, complete, claim_revision_ids_json,
                    claim_payload_hashes_json, received_at, imported_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    snapshot_id,
                    store.tenant_id,
                    store.region,
                    payload.origin_region.value,
                    payload.request_id,
                    payload.subject.value,
                    payload.target_fingerprint,
                    _iso(payload.valid_at),
                    _iso(payload.known_at),
                    export.payload_hash,
                    export.signature,
                    export.key_id,
                    int(payload.complete),
                    canonical_json_bytes(
                        [claim.claim_revision_id for claim in payload.claims]
                    ).decode("utf-8"),
                    canonical_json_bytes(
                        [claim.claim_payload_hash for claim in payload.claims]
                    ).decode("utf-8"),
                    _iso(moment),
                    _iso(moment),
                ),
            )
        else:
            snapshot_id = existing_snapshot["snapshot_id"]
        for claim in payload.claims:
            remote_claim_id = (
                f"remote_{payload.origin_region.value.lower()}_{claim.claim_revision_id}"
            )
            connection.execute(
                "INSERT OR IGNORE INTO remote_snapshot_claims (snapshot_id, remote_claim_id) "
                "VALUES (?, ?)",
                (snapshot_id, remote_claim_id),
            )
            existing = connection.execute(
                "SELECT remote_claim_id, claim_payload_hash FROM remote_claims "
                "WHERE remote_claim_id = ?",
                (remote_claim_id,),
            ).fetchone()
            if existing is not None:
                if existing["claim_payload_hash"] != claim.claim_payload_hash:
                    raise RemoteClaimConflict(
                        f"remote revision {claim.claim_revision_id} was already imported "
                        "with a different signed payload hash"
                    )
                # Re-export of the same immutable claim under a new request id: keep
                # the original audit record and do not duplicate derived facts.
                continue
            connection.execute(
                """
                INSERT INTO remote_claims (
                    remote_claim_id, tenant_id, region, origin_region, request_id, claim_id,
                    revision_id, subject, scope_json, rule_json, authority, policy_family,
                    valid_from, valid_to, system_from, system_to, source_ref, source_kind,
                    claim_payload_hash, manifest_root, export_payload_hash, export_signature,
                    export_key_id, not_checked_json, received_at, imported_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"remote_{payload.origin_region.value.lower()}_{claim.claim_revision_id}",
                    store.tenant_id,
                    store.region,
                    payload.origin_region.value,
                    payload.request_id,
                    claim.claim_id,
                    claim.claim_revision_id,
                    claim.subject.value,
                    claim.scope.model_dump_json(),
                    claim.rule.model_dump_json(),
                    claim.authority.value,
                    claim.policy_family,
                    _iso(claim.valid_from),
                    _iso(claim.valid_to),
                    _iso(claim.system_from),
                    _iso(claim.system_to),
                    claim.source_ref,
                    claim.source_kind,
                    claim.claim_payload_hash,
                    claim.manifest_root,
                    export.payload_hash,
                    export.signature,
                    export.key_id,
                    canonical_json_bytes(payload.not_checked).decode("utf-8"),
                    _iso(moment),
                    _iso(moment),
                ),
            )
            store.upsert_node(
                connection,
                node_id=f"remote_claim:{claim.claim_revision_id}",
                node_type="remote_claim",
                label=f"{claim.subject.value} from {payload.origin_region.value}",
                attributes={
                    "authority": claim.authority.value,
                    "claim_payload_hash": claim.claim_payload_hash,
                    "request_id": payload.request_id,
                    "signer_key_id": export.key_id,
                },
            )
            store.upsert_node(
                connection,
                node_id=f"office:{payload.origin_region.value}",
                node_type="office",
                label=payload.origin_region.value,
                attributes={"role": "remote_office"},
            )
            store.upsert_edge(
                connection,
                edge_type="IN_VERSION",
                from_node_id=f"remote_claim:{claim.claim_revision_id}",
                to_node_id=f"office:{payload.origin_region.value}",
                attributes={"opaque_source_ref": claim.source_ref},
            )
            imported += 1
    return imported


def _iso(value: datetime | None) -> str | None:
    from ..contracts.common import canonical_datetime

    return canonical_datetime(value) if value is not None else None


def _latest_snapshot_by_origin(
    rows: Sequence[dict[str, object]],
    *,
    known_at: datetime | None,
    target_fingerprint_value: str,
    valid_at: datetime,
    source_known_at: datetime | None,
) -> dict[str, dict[str, object]]:
    """Newest eligible snapshot per origin within the same query context.

    Source-office ``known_at`` and recipient receipt time are distinct axes. A late
    import of an older source snapshot cannot supersede a newer source snapshot, and
    a response for another target/effective date belongs to another snapshot series.
    """

    eligible: list[dict[str, object]] = []
    for row in rows:
        if int(row["complete"]) != 1:
            continue
        if str(row["target_fingerprint"]) != target_fingerprint_value:
            continue
        if _parse(str(row["valid_at"])) != valid_at:
            continue
        source_time = _parse(str(row["known_at"]))
        if source_known_at is not None and source_time != source_known_at:
            continue
        if known_at is not None:
            receipt = _parse(str(row["received_at"]))
            if receipt is not None and receipt > known_at:
                continue
            if source_time is not None and source_time > known_at:
                continue
        eligible.append(row)
    ordered = sorted(
        eligible,
        key=lambda row: (
            str(row["known_at"]),
            str(row["received_at"]),
            str(row["imported_at"]),
            str(row["snapshot_id"]),
        ),
    )
    latest: dict[str, dict[str, object]] = {}
    for row in ordered:
        latest[str(row["origin_region"])] = row
    return latest


def select_remote_snapshots(
    store: OfficeStore,
    *,
    subject: str,
    known_at: datetime | None = None,
    snapshot_ids: Sequence[str] | None = None,
    target_fingerprint_value: str,
    valid_at: datetime,
    source_known_at: datetime | None = None,
) -> list[dict[str, object]]:
    """Resolve the exact export snapshots eligible for one query.

    Without explicit ids the latest complete snapshot per origin is selected.
    Explicit ids from the gateway must identify exactly those latest snapshots:
    unknown, incomplete, future or superseded ids are rejected instead of replayed.
    """

    with store.db.reader() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM remote_export_snapshots WHERE tenant_id = ? AND region = ? "
                "AND subject = ? ORDER BY received_at ASC, imported_at ASC",
                (store.tenant_id, store.region, subject),
            ).fetchall()
        ]
    latest = _latest_snapshot_by_origin(
        rows,
        known_at=known_at,
        target_fingerprint_value=target_fingerprint_value,
        valid_at=valid_at,
        source_known_at=source_known_at,
    )
    if not snapshot_ids:
        return list(latest.values())

    by_id = {str(row["snapshot_id"]): row for row in rows}
    selected: dict[str, dict[str, object]] = {}
    for raw_id in dict.fromkeys(str(item) for item in snapshot_ids):
        row = by_id.get(raw_id)
        if row is None:
            raise UnknownRemoteSnapshot(f"remote snapshot {raw_id!r} is not known at this office")
        origin = str(row["origin_region"])
        if int(row["complete"]) != 1:
            raise StaleRemoteSnapshot(f"remote snapshot {raw_id!r} is not a complete export")
        if str(row["target_fingerprint"]) != target_fingerprint_value:
            raise StaleRemoteSnapshot(f"remote snapshot {raw_id!r} belongs to another target")
        if _parse(str(row["valid_at"])) != valid_at:
            raise StaleRemoteSnapshot(f"remote snapshot {raw_id!r} belongs to another valid_at")
        if source_known_at is not None and _parse(str(row["known_at"])) != source_known_at:
            raise StaleRemoteSnapshot(
                f"remote snapshot {raw_id!r} belongs to another source known_at"
            )
        moment = _parse(str(row["received_at"]))
        if known_at is not None and moment > known_at:
            raise StaleRemoteSnapshot(
                f"remote snapshot {raw_id!r} was received after the requested known_at"
            )
        current = latest.get(origin)
        if current is None or str(current["snapshot_id"]) != raw_id:
            raise StaleRemoteSnapshot(
                f"remote snapshot {raw_id!r} is not the latest complete snapshot for "
                f"origin {origin} at the requested known_at"
            )
        selected[origin] = row
    return list(selected.values())


def remote_claim_views(
    store: OfficeStore,
    *,
    subject: str | None = None,
    snapshot_ids: Sequence[str] | None = None,
    known_at: datetime | None = None,
    target_fingerprint_value: str,
    valid_at: datetime,
    source_known_at: datetime | None = None,
) -> list[ClaimView]:
    """Reconstruct comparable views for imported remote claims.

    Views come only from the selected snapshots.  Recipient knowledge time is the
    receipt time, never the source office's ``system_from``.  The reconstruction never
    fabricates clause text: quotes are empty and the provenance records that the
    clause was not disclosed.
    """

    if subject is None:
        return []
    selected = select_remote_snapshots(
        store,
        subject=subject,
        known_at=known_at,
        snapshot_ids=snapshot_ids,
        target_fingerprint_value=target_fingerprint_value,
        valid_at=valid_at,
        source_known_at=source_known_at,
    )
    ids = [str(row["snapshot_id"]) for row in selected]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with store.db.reader() as connection:
        rows = connection.execute(
            f"SELECT DISTINCT rc.* FROM remote_claims rc "
            f"JOIN remote_snapshot_claims rsc ON rsc.remote_claim_id = rc.remote_claim_id "
            f"WHERE rsc.snapshot_id IN ({placeholders}) AND rc.tenant_id = ? AND rc.region = ?",
            (*ids, store.tenant_id, store.region),
        ).fetchall()
    views: list[ClaimView] = []
    seen: set[str] = set()
    from pydantic import TypeAdapter

    from ..contracts.common import Rule, Scope

    scope_adapter = TypeAdapter(Scope)
    for row in rows:
        if row["revision_id"] in seen:
            continue
        seen.add(row["revision_id"])
        scope = _json.loads(row["scope_json"])
        rule = _json.loads(row["rule_json"])

        revision = ClaimRevision(
            tenant_id=row["tenant_id"],
            region=OfficeRegion(row["region"]),
            claim_id=row["claim_id"],
            revision_id=row["revision_id"],
            subject=Subject(row["subject"]),
            scope=scope_adapter.validate_python(scope),
            rule=Rule.model_validate(rule),
            authority=row["authority"],
            policy_family=row["policy_family"],
            source_id=f"remote_{row['origin_region'].lower()}_{row['source_ref']}",
            source_identity=f"remote:{row['origin_region'].lower()}",
            source_version_label=row["request_id"],
            source_clause_id=f"{REMOTE_NAMESPACE}:{row['source_ref']}",
            valid_from=_parse(row["valid_from"]),
            valid_to=_parse(row["valid_to"]),
            # Recipient knowledge begins when this office received the claim, not
            # when the source office first learned it.
            system_from=_parse(row["received_at"]),
            evidence=VerifiedEvidence(
                clause_id=f"{REMOTE_NAMESPACE}:{row['source_ref']}",
                page=0,
                section=None,
                quote="",
                start_char=0,
                end_char=0,
                leaf_hash=REMOTE_CLAUSE_PLACEHOLDER,
                manifest_root=row["manifest_root"],
            ),
            extraction=ExtractionProvenance(
                mode="remote_export",
                provider=f"remote-office:{row['origin_region'].lower()}",
                model=None,
                validator_version="remote-export-v1",
                notes=["clause text not disclosed; clause inclusion is not_checked locally"],
            ),
            origin=ClaimOrigin.REMOTE,
        )
        views.append(
            ClaimView(
                revision=revision,
                system_to=_parse(row["system_to"]),
                closure_kind=None,
                superseding_source_id=None,
                supersession_effective_from=None,
                payload_hash=row["claim_payload_hash"],
            )
        )
    return views


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def export_summary(export: FederationExport) -> dict[str, object]:
    payload = export.payload
    return {
        "origin_region": payload.origin_region.value,
        "request_id": payload.request_id,
        "claims": len(payload.claims),
        "withheld_restricted": payload.withheld_restricted,
        "payload_bytes": len(canonical_json_bytes(payload)),
        "not_checked": payload.not_checked,
        "reason_codes": payload.reason_codes,
        "key_id": export.key_id,
    }
