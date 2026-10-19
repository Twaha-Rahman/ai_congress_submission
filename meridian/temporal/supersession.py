"""Explicit, authorised, scoped replacement of superseded policies.

Only a manifest relationship establishes supersession: matching policy family,
matching applicable scope, explicit replaced clause IDs and a replacement date.
When such a relationship is learned, the prior knowledge revision's system interval
is closed once with an append-only signed closure event, and *new* revisions carrying
the corrected effective history (valid until the replacement date) are inserted with
new IDs and signatures.  The original revision's content is never mutated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from ..contracts.claims import ClaimRevision, ClaimRevisionRecord, RevisionClosure
from ..contracts.common import ClosureKind, utc_now
from ..contracts.manifest import SourceManifest
from ..integrity.bundles import claim_hash
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..rules.intervals import scope_intersection
from ..storage.store import OfficeStore, new_id
from ..integrity.signing import Signer


@dataclass
class SupersessionOutcome:
    closures: list[RevisionClosure] = field(default_factory=list)
    closed_revision_ids: list[str] = field(default_factory=list)
    carried_forward_revisions: list[ClaimRevisionRecord] = field(default_factory=list)
    review_items: list[tuple[str, str]] = field(default_factory=list)
    #: A declared replacement that did not validate completely.  The old policy stays
    #: current, but the pending state is persisted so queries must not present it as
    #: definitely current.
    pending: bool = False
    pending_revision_ids: list[str] = field(default_factory=list)
    pending_missing_clause_ids: list[str] = field(default_factory=list)
    replacement_source_id: str | None = None
    target_source_id: str | None = None


def apply_manifest_supersession(
    connection: sqlite3.Connection,
    store: OfficeStore,
    *,
    manifest: SourceManifest,
    new_source_id: str,
    new_revisions: list[ClaimRevisionRecord],
    signer: Signer,
    now: datetime | None = None,
) -> SupersessionOutcome:
    """Apply the manifest's declared replacement relationship, if any."""

    outcome = SupersessionOutcome()
    if manifest.supersedes is None:
        return outcome
    moment = now or utc_now()

    target = store.find_source_version(
        manifest.supersedes.supersedes_source_identity,
        manifest.supersedes.supersedes_version_label,
    )
    if target is None:
        outcome.review_items.append(
            (
                "unsupported_replacement",
                "declared supersession target "
                f"{manifest.supersedes.supersedes_source_identity}/"
                f"{manifest.supersedes.supersedes_version_label} is not present in this office "
                "store; the replacement was not applied",
            )
        )
        return outcome
    outcome.target_source_id = target.source_id
    if target.policy_family != manifest.policy_family:
        outcome.review_items.append(
            (
                "unsupported_replacement",
                "policy family mismatch between the replacement and the superseded source",
            )
        )
        return outcome
    if target.subject != manifest.subject:
        outcome.review_items.append(
            ("unsupported_replacement", "subject mismatch between replacement and superseded source")
        )
        return outcome

    overlap = scope_intersection(manifest.supersedes.replaced_scope, manifest.scope)
    if overlap != manifest.scope:
        outcome.review_items.append(
            (
                "unsupported_replacement",
                "the replacement scope is not fully covered by the declared replaced scope; "
                "partial replacements are quarantined for review rather than retiring a policy",
            )
        )
        return outcome

    target_clauses = {clause.clause_id for clause in store.clauses_for_source(target.source_id)}
    missing = [item for item in manifest.supersedes.replaced_clause_ids if item not in target_clauses]
    if missing:
        outcome.review_items.append(
            (
                "unsupported_replacement",
                "declared replaced clause IDs are not present in the superseded source: "
                + ", ".join(missing),
            )
        )
        return outcome

    new_revision_ids = [record.payload.revision_id for record in new_revisions]

    target_records = [
        record
        for record in store.claims_for_source(target.source_id, connection=connection)
        if record.system_to is None
        and record.payload.source_clause_id in manifest.supersedes.replaced_clause_ids
        and scope_intersection(
            manifest.supersedes.replaced_scope, record.payload.scope
        )
        == record.payload.scope
    ]
    if target_records:
        # A replacement is complete only when the accepted new rules cover every
        # replaced clause position.  Clause ids include the version label, so compare
        # the parser-assigned positions inside each signed source rather than ids.
        new_indexes: set[int] = set()
        for record in new_revisions:
            clause_row = store.get_clause(
                record.payload.evidence.clause_id, connection=connection
            )
            if clause_row is not None:
                new_indexes.add(clause_row.clause_index)
        missing_replacement_ids: list[str] = []
        for record in target_records:
            target_clause = store.get_clause(
                record.payload.source_clause_id, connection=connection
            )
            if target_clause is None or target_clause.clause_index not in new_indexes:
                missing_replacement_ids.append(record.payload.source_clause_id)
        missing_replacement_ids = sorted(set(missing_replacement_ids))
        if not new_revisions or missing_replacement_ids:
            affected = [record.payload.revision_id for record in target_records]
            missing_text = (
                ", ".join(missing_replacement_ids)
                if missing_replacement_ids
                else "all declared replaced clauses"
            )
            detail = (
                "declared replacement produced no validated rules covering "
                f"{missing_text}; the prior validated policy remains current and the "
                "replacement is pending review rather than being silently applied"
            )
            outcome.review_items.append(("pending_replacement", detail))
            outcome.pending = True
            outcome.pending_revision_ids = affected
            outcome.pending_missing_clause_ids = missing_replacement_ids
            outcome.replacement_source_id = new_source_id
            return outcome

    for record in target_records:
        revision = record.payload
        carried = _carry_forward(
            revision,
            signer=signer,
            system_from=moment,
            valid_to=manifest.supersedes.effective_from,
        )
        closure = RevisionClosure(
            tenant_id=store.tenant_id,
            region=manifest.region,
            closure_id=new_id("closure"),
            revision_id=revision.revision_id,
            closure_kind=ClosureKind.SUPERSESSION,
            system_to=moment,
            policy_family=manifest.policy_family,
            superseding_source_id=new_source_id,
            replaced_clause_ids=list(manifest.supersedes.replaced_clause_ids),
            replacement_revision_ids=new_revision_ids,
            carried_forward_revision_ids=[carried.payload.revision_id],
            effective_from=manifest.supersedes.effective_from,
            created_at=moment,
        )
        closure_bytes = canonical_json_bytes(closure)
        store.insert_closure(
            connection, closure, signature=signer.sign(closure_bytes), key_id=signer.key_id
        )
        store.insert_claim(connection, carried)

        store.upsert_edge(
            connection,
            edge_type="SUPERSEDES",
            from_node_id=f"source:{new_source_id}",
            to_node_id=f"revision:{revision.revision_id}",
            attributes={"effective_from": closure.effective_from.isoformat() if closure.effective_from else ""},
        )
        store.upsert_edge(
            connection,
            edge_type="SUPERSEDES",
            from_node_id=f"revision:{carried.payload.revision_id}",
            to_node_id=f"revision:{revision.revision_id}",
            attributes={"carried_forward": "true"},
        )
        store.upsert_edge(
            connection,
            edge_type="IN_VERSION",
            from_node_id=f"revision:{carried.payload.revision_id}",
            to_node_id=f"source:{target.source_id}",
            attributes={"carried_forward": "true"},
        )
        outcome.closures.append(closure)
        outcome.closed_revision_ids.append(revision.revision_id)
        outcome.carried_forward_revisions.append(carried)

    return outcome


def _carry_forward(
    revision: ClaimRevision,
    *,
    signer: Signer,
    system_from: datetime,
    valid_to: datetime,
) -> ClaimRevisionRecord:
    """Build a new revision representing the corrected effective history."""

    seed = f"{revision.revision_id}|{valid_to.isoformat()}|{system_from.isoformat()}"
    revision_id = f"rev_{sha256_hex(seed.encode('utf-8'))[:24]}"
    carried = ClaimRevision(
        schema_version=revision.schema_version,
        tenant_id=revision.tenant_id,
        region=revision.region,
        claim_id=revision.claim_id,
        revision_id=revision_id,
        subject=revision.subject,
        scope=revision.scope,
        rule=revision.rule,
        authority=revision.authority,
        policy_family=revision.policy_family,
        source_id=revision.source_id,
        source_identity=revision.source_identity,
        source_version_label=revision.source_version_label,
        source_clause_id=revision.source_clause_id,
        valid_from=revision.valid_from,
        valid_to=valid_to,
        system_from=system_from,
        evidence=revision.evidence,
        extraction=revision.extraction,
        status=revision.status,
    )
    payload_bytes = canonical_json_bytes(carried)
    return ClaimRevisionRecord(
        payload=carried,
        payload_hash=claim_hash(carried),
        signature=signer.sign(payload_bytes),
        key_id=signer.key_id,
    )
