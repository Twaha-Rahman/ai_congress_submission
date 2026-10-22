"""Transactional source withdrawal; immutable evidence and past decisions survive."""

from __future__ import annotations

import json

from ..api_common import ApiError
from ..contracts.claims import RevisionClosure
from ..contracts.common import ErrorCode, ExplanationCode, Severity, canonical_datetime, utc_now
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..storage.store import new_id


def withdrawal_history(store):
    with store.db.reader() as connection:
        rows = connection.execute(
            "SELECT source_id, payload_json FROM source_withdrawals WHERE tenant_id=? AND region=?",
            (store.tenant_id, store.region),
        ).fetchall()
    return {row["source_id"]: json.loads(row["payload_json"]) for row in rows}


def is_historical_finding(payload):
    return (payload.detail.get("assessment") == "historical"
            or payload.explanation_code == ExplanationCode.REVISION_NOT_CURRENT)


def _plan(store, source_id, scope, connection):
    if not isinstance(scope, str) or scope not in {"version", "all_versions"}:
        raise ApiError(ErrorCode.INVALID_INPUT, "Choose this version or all uploaded versions.")
    source = store.get_source(source_id, connection=connection)
    if source is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Source not found.")
    rows = connection.execute(
        "SELECT source_id, version_label, status, ingested_at FROM sources WHERE tenant_id=? AND region=? AND source_identity=? ORDER BY ingested_at, source_id",
        (store.tenant_id, store.region, source.source_identity),
    ).fetchall()
    selected = [dict(row) for row in rows if scope == "all_versions" or row["source_id"] == source_id]
    active = [row for row in selected if row["status"] != "withdrawn"]
    ids = {row["source_id"] for row in active}
    claims = [claim for key in sorted(ids) for claim in store.claims_for_source(key, connection=connection)]
    revisions = {claim.payload.revision_id for claim in claims}
    findings = [record for record in store.list_findings(limit=None, connection=connection)
                if not is_historical_finding(record.payload) and (
                    revisions.intersection(record.payload.claim_revision_ids)
                    or ids.intersection(e.source_id for e in record.payload.evidence))]
    pending = []
    for row in connection.execute(
        "SELECT job_id, status, source_id, request_json FROM jobs WHERE tenant_id=? AND region=? AND status IN ('queued','running') ORDER BY job_id",
        (store.tenant_id, store.region),
    ):
        body = json.loads(row["request_json"])
        manifest = body.get("manifest") or {}
        if (row["source_id"] in ids or body.get("source_id") in ids
                or (manifest.get("source_identity") == source.source_identity
                    and (scope == "all_versions" or manifest.get("version_label") == source.version_label))):
            pending.append({"job_id": row["job_id"], "status": row["status"]})
    answers = []
    for row in connection.execute("SELECT answer_id, payload_json FROM answers WHERE tenant_id=? AND region=? ORDER BY answer_id", (store.tenant_id, store.region)):
        if ids.intersection(item.get("source_id") for item in json.loads(row["payload_json"]).get("citations", [])):
            answers.append(row["answer_id"])
    state = {"scope": scope, "source_id": source_id, "versions": selected,
             "claims": sorted((claim.payload.revision_id, canonical_datetime(claim.system_to) if claim.system_to else None) for claim in claims),
             "findings": sorted((record.snapshot_id, record.review_state.value) for record in findings), "jobs": pending, "answers": answers}
    preview = {"source_id": source_id, "source_identity": source.source_identity, "scope": scope,
               "versions": selected, "version_count": len(active), "finding_count": len(findings),
               "open_finding_count": sum(record.review_state.value == "open" for record in findings),
               "job_count": len(pending), "answer_count": len(answers),
               "snapshot": sha256_hex(canonical_json_bytes(state))}
    return preview, active, claims, findings, pending


def preview_withdrawal(store, source_id, scope):
    with store.db.transaction(immediate=False) as connection:
        return _plan(store, source_id, scope, connection)[0]


def withdraw_source(store, source_id, *, scope, reason, expected_snapshot, actor, signer):
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
        raise ApiError(ErrorCode.INVALID_INPUT, "Enter a withdrawal reason of up to 1,000 characters.")
    if not isinstance(expected_snapshot, str) or len(expected_snapshot) != 64:
        raise ApiError(ErrorCode.INVALID_INPUT, "Review the withdrawal impact before confirming.")
    reason = reason.strip()
    with store.db.transaction() as connection:
        preview, sources, claims, findings, jobs = _plan(store, source_id, scope, connection)
        if preview["snapshot"] != expected_snapshot:
            raise ApiError(ErrorCode.CONFLICT, "Source activity changed. Review the updated impact and confirm again.")
        if not sources:
            raise ApiError(ErrorCode.CONFLICT, "The selected source versions are already withdrawn.")
        now = utc_now()
        ids = sorted(row["source_id"] for row in sources)
        for key in ids:
            payload = {"source_id": key, "tenant_id": store.tenant_id, "region": store.region,
                       "reason": reason, "actor": actor, "scope": scope, "withdrawn_at": canonical_datetime(now)}
            raw = canonical_json_bytes(payload)
            connection.execute("INSERT INTO source_withdrawals "
                "(source_id, tenant_id, region, withdrawn_at, payload_json, payload_hash, signature, key_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (key, store.tenant_id, store.region, canonical_datetime(now), raw.decode(), sha256_hex(raw), signer.sign(raw), signer.key_id))
            connection.execute("UPDATE sources SET status='withdrawn' WHERE source_id=? AND tenant_id=? AND region=?", (key, store.tenant_id, store.region))
        for claim in claims:
            if claim.system_to is not None:
                continue
            closure = RevisionClosure(tenant_id=store.tenant_id, region=store.region, closure_id=new_id("closure"),
                revision_id=claim.payload.revision_id, closure_kind="retirement", system_to=now,
                policy_family=claim.payload.policy_family, created_at=now)
            store.insert_closure(connection, closure, signature=signer.sign(canonical_json_bytes(closure)), key_id=signer.key_id)
        for record in findings:
            payload = record.payload.model_copy(update={"created_at": now, "severity": Severity.INFO,
                "explanation_code": ExplanationCode.REVISION_NOT_CURRENT,
                "detail": {**record.payload.detail, "assessment": "historical", "withdrawn_source_ids": ",".join(sorted(set(ids).intersection(e.source_id for e in record.payload.evidence))),
                           "explanation": "A cited source was withdrawn. This finding is historical."}})
            snapshot = store.insert_finding_snapshot(connection, payload=payload,
                signature=signer.sign(canonical_json_bytes(payload)), key_id=signer.key_id, alert=False)
            store.upsert_node(connection, node_id=f"finding:{payload.finding_id}", node_type="finding",
                label=f"{payload.finding_type.value} (historical)", attributes={"explanation_code": payload.explanation_code.value, "alert": "False", "snapshot_id": snapshot}, restricted=False)
        for job in jobs:
            row = connection.execute("SELECT progress_json FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()
            progress = json.loads(row["progress_json"] or "{}")
            progress["current_stage"] = None
            for stage in progress.get("stages", []):
                if stage.get("status") == "running":
                    stage.update(status="interrupted", finished_at=canonical_datetime(now))
            connection.execute("UPDATE jobs SET status='failed', error_code='source_withdrawn', review_reason=?, finished_at=?, updated_at=?, progress_json=? WHERE job_id=? AND tenant_id=? AND region=?",
                ("The source was withdrawn before processing finished.", canonical_datetime(now), canonical_datetime(now), json.dumps(progress), job["job_id"], store.tenant_id, store.region))
    return {"withdrawn_source_ids": ids, "withdrawn_at": canonical_datetime(now), "impact": preview}
