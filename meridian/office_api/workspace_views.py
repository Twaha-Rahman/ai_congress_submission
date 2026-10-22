"""Read-only projections for activity and deterministic source-version comparisons."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit
from datetime import timezone

from cryptography.fernet import InvalidToken

from ..api_common import ApiError
from ..contracts.common import ErrorCode, canonical_datetime
from .job_reviews import source_review_summaries, job_review_state


def _invalid(message):
    raise ApiError(ErrorCode.INVALID_INPUT, message)


def compare_source_text(store, before, after):
    """Compare preserved parser clauses, never generated statements or PDF bytes."""
    left = store.clauses_for_source(before.source_id)
    right = store.clauses_for_source(after.source_id)
    if len(left) + len(right) > 10000 or sum(len(c.text) for c in [*left, *right]) > 2_000_000:
        _invalid("These versions are too large for an inline comparison. Download the originals to compare them.")

    def passage(clause):
        return {"clause_id": clause.clause_id, "page": clause.page, "section": clause.section, "text": clause.text}

    def tokens(a, b):
        a, b = re.findall(r"\s+|\w+|[^\w\s]", a), re.findall(r"\s+|\w+|[^\w\s]", b)
        # Bound pathological token matching, retaining complete literal text.
        if len(a) + len(b) > 20000:
            return [{"kind": "removed", "text": "".join(a)}, {"kind": "added", "text": "".join(b)}]
        chunks = []
        for tag, i, j, k, l in SequenceMatcher(None, a, b, autojunk=True).get_opcodes():
            if tag == "equal":
                chunks.append({"kind": "unchanged", "text": "".join(a[i:j])})
            else:
                if i < j:
                    chunks.append({"kind": "removed", "text": "".join(a[i:j])})
                if k < l:
                    chunks.append({"kind": "added", "text": "".join(b[k:l])})
        return chunks

    rows = []
    for tag, i, j, k, l in SequenceMatcher(None, [c.text for c in left], [c.text for c in right], autojunk=False).get_opcodes():
        if tag == "equal":
            rows.extend({"kind": "unchanged", "before": passage(a), "after": passage(b), "chunks": []} for a, b in zip(left[i:j], right[k:l]))
        else:
            # Exact passages anchor the alignment. Replacements pair in document order.
            for n in range(max(j - i, l - k)):
                a = left[i + n] if i + n < j else None
                b = right[k + n] if k + n < l else None
                rows.append({"kind": "changed" if a and b else "removed" if a else "added",
                             "before": passage(a) if a else None, "after": passage(b) if b else None,
                             "chunks": tokens(a.text, b.text) if a and b else []})
    fields = ["source_type", "subject", "policy_family", "authority", "scope", "sensitivity", "permissions", "publication_time", "effective_from", "effective_to", "supersedes", "declared_conditions", "rationale"]
    a, b = before.manifest.model_dump(mode="json"), after.manifest.model_dump(mode="json")
    return {"passages": rows, "counts": {kind: sum(row["kind"] == kind for row in rows) for kind in ["added", "removed", "changed", "unchanged"]},
            "metadata": [{"field": key, "before": a.get(key), "after": b.get(key)} for key in fields if a.get(key) != b.get(key)],
            "same_file": before.source_sha256 == after.source_sha256,
            "same_text": before.content_sha256 == after.content_sha256,
            "explicit_replacement": bool(after.supersedes and after.supersedes.get("supersedes_source_identity") == before.source_identity and after.supersedes.get("supersedes_version_label") == before.version_label)}


TABLES = {"transfer": ("egress_events", "event_id", "created_at"), "processing": ("jobs", "job_id", "updated_at"),
          "review": ("review_events", "event_id", "created_at"), "source": ("sources", "source_id", "ingested_at"),
          "withdrawal": ("source_withdrawals", "source_id", "withdrawn_at")}


def _destination(value):
    """Do not expose URL credentials, query strings or fragments in the viewer."""
    try:
        url = urlsplit(value)
        if url.scheme and url.netloc:
            return urlunsplit((url.scheme, url.netloc.split("@")[-1], url.path, "", ""))
    except ValueError:
        return "Unavailable"
    return value


def activity_record(store, category, identifier, *, source_readable, job_readable, finding_readable):
    if category not in TABLES:
        return None
    table, key, time = TABLES[category]
    with store.db.reader() as connection:
        row = connection.execute(f"SELECT * FROM {table} WHERE tenant_id = ? AND region = ? AND {key} = ?", (store.tenant_id, store.region, identifier)).fetchone()
    if not row:
        return None
    row = dict(row)
    base = {"id": f"{category}:{identifier}", "category": category, "created_at": row[time], "target_id": identifier, "details": {}}
    if category == "source":
        source = store.get_source(identifier)
        if not source_readable(source):
            return None
        base.update(title=(source.manifest.rationale if source.source_identity.startswith("slack:") else None) or source.source_identity,
                    outcome="published", description=source.version_label, details={"source_type": source.source_type, "authority": source.authority, "version": source.version_label, "status": source.status, "file_sha256": source.source_sha256})
    elif category == "withdrawal":
        source = store.get_source(identifier)
        if not source_readable(source):
            return None
        payload = json.loads(row["payload_json"])
        base.update(title=(source.manifest.rationale if source.source_identity.startswith("slack:") else None) or source.source_identity,
                    outcome="withdrawn", description=payload.get("reason", "Source withdrawn"),
                    details={"version": source.version_label, "reason": payload.get("reason"), "actor": payload.get("actor"), "scope": payload.get("scope"), "payload_hash": row["payload_hash"], "key_id": row["key_id"]})
    elif category == "processing":
        job = store.get_job(identifier)
        if not job_readable(job):
            return None
        manifest = job.request.get("manifest") or {}
        review = source_review_summaries(store, [job.source_id], finding_readable=finding_readable).get(job.source_id)
        base.update(title=(manifest.get("rationale") if job.request.get("slack") else None) or manifest.get("source_identity") or "Source processing",
                    outcome=job_review_state(job, review), description=f"{job.kind} · {job.mode}", details={"finding_review": review, "original_processing_status": job.status, "kind": job.kind, "mode": job.mode, "attempts": job.attempts, "stage": job.progress.get("current_stage"), "submitted": canonical_datetime(job.created_at), "started": canonical_datetime(job.started_at) if job.started_at else None, "finished": canonical_datetime(job.finished_at) if job.finished_at else None, "error": job.error_code, "reason": job.review_reason, "source_id": job.source_id, "version": manifest.get("version_label"), "request_id": job.request.get("request_id")})
    elif category == "review":
        finding = store.get_finding(row["finding_id"])
        if not finding or not finding_readable(finding):
            return None
        base.update(title=f"Finding {row['new_state']}", outcome=row["new_state"], description=row["reason"], target_id=row["finding_id"],
                    details={key: row[key] for key in ["actor", "action", "reason", "prior_state", "new_state", "snapshot_id", "payload_hash", "key_id"]})
    else:
        metadata = json.loads(row["model_metadata_json"]) if row["model_metadata_json"] else None
        base.update(title="Model request" if row["channel"] == "hosted_model" else "Office transfer", outcome=row["outcome"], description=_destination(row["destination"]),
                    details={**{key: row[key] for key in ["channel", "request_id", "payload_type", "payload_bytes", "raw_source_bytes", "payload_sha256", "error_code"]}, "destination": _destination(row["destination"]), "model": metadata})
    return base


def activity_page(store, *, cursor_cipher, limit=40, cursor="", category="all", outcome="all", query="", since=None, until=None, **access):
    if category not in ["all", *TABLES]:
        _invalid("Choose a valid activity type.")
    anchor = None
    if cursor:
        try:
            if len(cursor) > 1024:
                raise ValueError
            anchor = json.loads(cursor_cipher.decrypt(cursor.encode("ascii")))
            if not isinstance(anchor, list) or len(anchor) != 2 or not all(isinstance(v, str) and v for v in anchor):
                raise ValueError
        except (ValueError, TypeError, InvalidToken):
            _invalid("This activity page link is invalid. Refresh the list.")
    parts = [f"SELECT '{kind}' AS category, {key} AS identifier, CASE WHEN substr({time},20,1) = 'Z' THEN substr({time},1,19) || '.000000Z' ELSE {time} END AS stamp, '{kind}:' || {key} AS event_key FROM {table} WHERE tenant_id = ? AND region = ?" for kind, (table, key, time) in TABLES.items() if category in ["all", kind]]
    params = [value for _ in parts for value in (store.tenant_id, store.region)]
    sql = "SELECT * FROM (" + " UNION ALL ".join(parts) + ") WHERE 1=1"
    if anchor:
        sql += " AND (stamp < ? OR (stamp = ? AND event_key < ?))"
        params.extend([anchor[0], anchor[0], anchor[1]])
    for operator, value in [(">=", since), ("<=", until)]:
        if value:
            sql += f" AND stamp {operator} ?"
            params.append(value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
    sql += " ORDER BY stamp DESC, event_key DESC LIMIT 1001"
    with store.db.reader() as connection:
        rows = connection.execute(sql, params).fetchall()
    events, scanned = [], 0
    for row in rows[:1000]:
        scanned += 1
        event = activity_record(store, row["category"], row["identifier"], **access)
        if event and (outcome == "all" or event["outcome"] == outcome) and (not query.strip() or query.strip().casefold() in json.dumps(event, ensure_ascii=False).casefold()):
            events.append(event)
        if len(events) == limit:
            break
    next_cursor = ""
    if scanned and scanned < len(rows):
        last = rows[scanned - 1]
        next_cursor = cursor_cipher.encrypt(json.dumps([last["stamp"], last["event_key"]]).encode()).decode("ascii")
    return {"events": events, "next_cursor": next_cursor}
