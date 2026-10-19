"""Transactional persistence for one office store.

Signed payloads are stored as the exact canonical JSON bytes that were signed, so
that ``sha256(payload_json) == payload_hash`` holds for every stored record and
independent verification never needs to re-serialise.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Iterator, Sequence

from ..contracts.claims import ClaimRevision, ClaimRevisionRecord, RevisionClosure
from ..contracts.common import (
    ClaimOrigin,
    ClaimStatus,
    ClosureKind,
    EgressChannel,
    EgressOutcome,
    JobStatus,
    Mode,
    Region,
    ReviewState,
    Severity,
    canonical_datetime,
    ensure_utc,
    utc_now,
)
from ..contracts.federation import EgressEvent, EgressSummary
from ..contracts.findings import FindingPayload, FindingRecord, ReviewEvent
from ..contracts.manifest import SourceManifest
from ..contracts.qa import AnswerPayload, AnswerRecord
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..rules.compare import ClaimView
from .db import Database


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def canonical_json_text(model: Any) -> str:
    return canonical_json_bytes(model).decode("utf-8")


def _hash(text: str) -> str:
    return sha256_hex(text.encode("utf-8"))


def _iso(value: datetime | None) -> str | None:
    return canonical_datetime(value) if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(text))


@dataclass(frozen=True)
class SourceRow:
    source_id: str
    tenant_id: str
    region: str
    source_identity: str
    version_label: str
    source_type: str
    subject: str
    policy_family: str
    authority: str
    sensitivity: str
    office_export: bool
    hosted_model: bool
    content_sha256: str
    source_sha256: str
    merkle_root: str
    tree_size: int
    manifest: SourceManifest
    manifest_payload: dict
    manifest_hash: str
    manifest_signature: str
    manifest_key_id: str
    parser_version: str
    publication_time: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    status: str
    supersedes: dict | None
    ingested_at: datetime

    @property
    def restricted(self) -> bool:
        return self.sensitivity == "restricted"


@dataclass(frozen=True)
class ClauseRow:
    clause_id: str
    source_id: str
    clause_index: int
    page: int
    section: str | None
    text: str
    start_char: int
    end_char: int
    leaf_hash: str
    restricted: bool


@dataclass(frozen=True)
class JobRow:
    job_id: str
    tenant_id: str
    region: str
    kind: str
    status: str
    mode: str
    stage_modes: dict
    attempts: int
    max_attempts: int
    error_code: str | None
    review_reason: str | None
    source_id: str | None
    request: dict
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class OfficeStore:
    """All persistence for a single office (tenant + region) database."""

    def __init__(self, db: Database, *, tenant_id: str, region: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.region = region
        self.db.migrate()

    @contextmanager
    def _read(self, connection: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
        """Read through an in-flight transaction connection when supplied."""

        if connection is not None:
            yield connection
        else:
            with self.db.reader() as opened:
                yield opened

    # ------------------------------------------------------------------- sources
    def insert_source(
        self,
        connection: sqlite3.Connection,
        *,
        source: SourceRow,
    ) -> None:
        connection.execute(
            """
            INSERT INTO sources (
                source_id, tenant_id, region, source_identity, version_label, source_type,
                subject, policy_family, authority, sensitivity, office_export, hosted_model,
                content_sha256, source_sha256, merkle_root, tree_size, manifest_json,
                manifest_payload_json, manifest_hash, manifest_signature, manifest_key_id,
                parser_version, contract_schema_version, publication_time, effective_from,
                effective_to, status, supersedes_json, ingested_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source.source_id,
                source.tenant_id,
                source.region,
                source.source_identity,
                source.version_label,
                source.source_type,
                source.subject,
                source.policy_family,
                source.authority,
                source.sensitivity,
                int(source.office_export),
                int(source.hosted_model),
                source.content_sha256,
                source.source_sha256,
                source.merkle_root,
                source.tree_size,
                canonical_json_text(source.manifest),
                canonical_json_text(source.manifest_payload),
                source.manifest_hash,
                source.manifest_signature,
                source.manifest_key_id,
                source.parser_version,
                "1",
                _iso(source.publication_time),
                _iso(source.effective_from),
                _iso(source.effective_to),
                source.status,
                canonical_json_text(source.supersedes) if source.supersedes else None,
                _iso(source.ingested_at),
            ),
        )

    def insert_clauses(
        self, connection: sqlite3.Connection, clauses: Sequence[ClauseRow]
    ) -> None:
        for clause in clauses:
            connection.execute(
                """
                INSERT INTO clauses (
                    clause_id, tenant_id, region, source_id, clause_index, page, section,
                    text, start_char, end_char, leaf_hash, restricted
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    clause.clause_id,
                    self.tenant_id,
                    self.region,
                    clause.source_id,
                    clause.clause_index,
                    clause.page,
                    clause.section,
                    clause.text,
                    clause.start_char,
                    clause.end_char,
                    clause.leaf_hash,
                    int(clause.restricted),
                ),
            )
            connection.execute(
                "INSERT INTO clause_fts (text, clause_id, source_id, tenant_id, region) "
                "VALUES (?,?,?,?,?)",
                (clause.text, clause.clause_id, clause.source_id, self.tenant_id, self.region),
            )

    def get_source(
        self, source_id: str, *, connection: sqlite3.Connection | None = None
    ) -> SourceRow | None:
        with self._read(connection) as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE source_id = ? AND tenant_id = ? AND region = ?",
                (source_id, self.tenant_id, self.region),
            ).fetchone()
        return self._source_from_row(row) if row else None

    def find_source_version(self, source_identity: str, version_label: str) -> SourceRow | None:
        with self.db.reader() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE tenant_id = ? AND region = ? "
                "AND source_identity = ? AND version_label = ?",
                (self.tenant_id, self.region, source_identity, version_label),
            ).fetchone()
        return self._source_from_row(row) if row else None

    def list_sources(self, *, limit: int = 100) -> list[SourceRow]:
        with self.db.reader() as connection:
            rows = connection.execute(
                "SELECT * FROM sources WHERE tenant_id = ? AND region = ? "
                "ORDER BY ingested_at ASC LIMIT ?",
                (self.tenant_id, self.region, limit),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def _source_from_row(self, row: sqlite3.Row) -> SourceRow:
        return SourceRow(
            source_id=row["source_id"],
            tenant_id=row["tenant_id"],
            region=row["region"],
            source_identity=row["source_identity"],
            version_label=row["version_label"],
            source_type=row["source_type"],
            subject=row["subject"],
            policy_family=row["policy_family"],
            authority=row["authority"],
            sensitivity=row["sensitivity"],
            office_export=bool(row["office_export"]),
            hosted_model=bool(row["hosted_model"]),
            content_sha256=row["content_sha256"],
            source_sha256=row["source_sha256"],
            merkle_root=row["merkle_root"],
            tree_size=row["tree_size"],
            manifest=SourceManifest.model_validate_json(row["manifest_json"]),
            manifest_payload=json.loads(row["manifest_payload_json"]),
            manifest_hash=row["manifest_hash"],
            manifest_signature=row["manifest_signature"],
            manifest_key_id=row["manifest_key_id"],
            parser_version=row["parser_version"],
            publication_time=_parse_dt(row["publication_time"]),
            effective_from=_parse_dt(row["effective_from"]),
            effective_to=_parse_dt(row["effective_to"]),
            status=row["status"],
            supersedes=json.loads(row["supersedes_json"]) if row["supersedes_json"] else None,
            ingested_at=_parse_dt(row["ingested_at"]),
        )

    # ------------------------------------------------------------------- clauses
    def clauses_for_source(
        self, source_id: str, *, connection: sqlite3.Connection | None = None
    ) -> list[ClauseRow]:
        with self._read(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM clauses WHERE source_id = ? AND tenant_id = ? AND region = ? "
                "ORDER BY clause_index ASC",
                (source_id, self.tenant_id, self.region),
            ).fetchall()
        return [self._clause_from_row(row) for row in rows]

    def get_clause(
        self, clause_id: str, *, connection: sqlite3.Connection | None = None
    ) -> ClauseRow | None:
        with self._read(connection) as conn:
            row = conn.execute(
                "SELECT * FROM clauses WHERE clause_id = ? AND tenant_id = ? AND region = ?",
                (clause_id, self.tenant_id, self.region),
            ).fetchone()
        return self._clause_from_row(row) if row else None

    def _clause_from_row(self, row: sqlite3.Row) -> ClauseRow:
        return ClauseRow(
            clause_id=row["clause_id"],
            source_id=row["source_id"],
            clause_index=row["clause_index"],
            page=row["page"],
            section=row["section"],
            text=row["text"],
            start_char=row["start_char"],
            end_char=row["end_char"],
            leaf_hash=row["leaf_hash"],
            restricted=bool(row["restricted"]),
        )

    def search_clauses(self, query: str, *, limit: int = 20) -> list[tuple[str, str]]:
        """FTS5 lexical retrieval of clause text (returns clause_id, snippet)."""

        tokens = [token for token in query.replace('"', " ").split() if token]
        if not tokens:
            return []
        match = " OR ".join(f'"{token}"' for token in tokens[:12])
        with self.db.reader() as connection:
            rows = connection.execute(
                "SELECT clause_id, snippet(clause_fts, 0, '[', ']', ' ... ', 12) AS snip "
                "FROM clause_fts WHERE clause_fts MATCH ? AND tenant_id = ? AND region = ? "
                "LIMIT ?",
                (match, self.tenant_id, self.region, limit),
            ).fetchall()
        return [(row["clause_id"], row["snip"]) for row in rows]

    # ---------------------------------------------------------------------- jobs
    def create_job(
        self,
        *,
        kind: str,
        mode: Mode,
        request: dict,
        max_attempts: int = 3,
    ) -> JobRow:
        job_id = new_id("job")
        now = utc_now()
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO jobs (job_id, tenant_id, region, kind, status, mode, stage_modes_json,
                    attempts, max_attempts, source_id, request_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    self.tenant_id,
                    self.region,
                    kind,
                    JobStatus.QUEUED.value,
                    mode.value,
                    canonical_json_text({"ingestion": mode}),
                    0,
                    max_attempts,
                    None,
                    canonical_json_text(request),
                    _iso(now),
                    _iso(now),
                ),
            )
        job = self.get_job(job_id)
        assert job is not None
        return job

    def get_job(self, job_id: str) -> JobRow | None:
        with self.db.reader() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ? AND tenant_id = ? AND region = ?",
                (job_id, self.tenant_id, self.region),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, *, limit: int = 50) -> list[JobRow]:
        with self.db.reader() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE tenant_id = ? AND region = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (self.tenant_id, self.region, limit),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def _job_from_row(self, row: sqlite3.Row) -> JobRow:
        return JobRow(
            job_id=row["job_id"],
            tenant_id=row["tenant_id"],
            region=row["region"],
            kind=row["kind"],
            status=row["status"],
            mode=row["mode"],
            stage_modes=json.loads(row["stage_modes_json"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            error_code=row["error_code"],
            review_reason=row["review_reason"],
            source_id=row["source_id"],
            request=json.loads(row["request_json"]),
            created_at=_parse_dt(row["created_at"]),
            started_at=_parse_dt(row["started_at"]),
            finished_at=_parse_dt(row["finished_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    def claim_next_job(self) -> JobRow | None:
        """Atomically move one queued job to ``running``."""

        now = utc_now()
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT job_id FROM jobs WHERE tenant_id = ? AND region = ? AND status = ? "
                "ORDER BY created_at ASC LIMIT 1",
                (self.tenant_id, self.region, JobStatus.QUEUED.value),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE jobs SET status = ?, attempts = attempts + 1, started_at = ?, "
                "updated_at = ? WHERE job_id = ?",
                (JobStatus.RUNNING.value, _iso(now), _iso(now), row["job_id"]),
            )
        return self.get_job(row["job_id"])

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        error_code: str | None = None,
        review_reason: str | None = None,
        source_id: str | None = None,
        stage_modes: dict | None = None,
        finished: bool = False,
    ) -> None:
        now = _iso(utc_now())
        sets = ["updated_at = ?"]
        params: list[Any] = [now]
        if status is not None:
            sets.append("status = ?")
            params.append(status.value)
        if error_code is not None:
            sets.append("error_code = ?")
            params.append(error_code)
        if review_reason is not None:
            sets.append("review_reason = ?")
            params.append(review_reason)
        if source_id is not None:
            sets.append("source_id = ?")
            params.append(source_id)
        if stage_modes is not None:
            sets.append("stage_modes_json = ?")
            params.append(canonical_json_text(stage_modes))
        if finished:
            sets.append("finished_at = ?")
            params.append(now)
        params.append(job_id)
        with self.db.transaction() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ? AND tenant_id = ? AND region = ?",
                (*params, self.tenant_id, self.region),
            )

    def requeue_unfinished_jobs(self) -> int:
        """Restart recovery: running jobs return to the queue, bounded by attempts."""

        now = _iso(utc_now())
        with self.db.transaction() as connection:
            rows = connection.execute(
                "SELECT job_id, attempts, max_attempts FROM jobs "
                "WHERE tenant_id = ? AND region = ? AND status = ?",
                (self.tenant_id, self.region, JobStatus.RUNNING.value),
            ).fetchall()
            requeued = 0
            for row in rows:
                if row["attempts"] >= row["max_attempts"]:
                    connection.execute(
                        "UPDATE jobs SET status = ?, error_code = ?, finished_at = ?, updated_at = ? "
                        "WHERE job_id = ?",
                        (
                            JobStatus.FAILED.value,
                            "interrupted_attempts_exhausted",
                            now,
                            now,
                            row["job_id"],
                        ),
                    )
                    continue
                connection.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                    (JobStatus.QUEUED.value, now, row["job_id"]),
                )
                requeued += 1
        return requeued

    # --------------------------------------------------------------------- claims
    def insert_claim(self, connection: sqlite3.Connection, record: ClaimRevisionRecord) -> None:
        payload = record.payload
        payload_json = canonical_json_text(payload)
        connection.execute(
            """
            INSERT INTO claim_revisions (
                revision_id, tenant_id, region, claim_id, subject, scope_json, rule_json,
                authority, policy_family, valid_from, valid_to, system_from, source_id,
                source_clause_id, evidence_json, extraction_json, payload_json, payload_hash,
                signature, key_id, origin, remote_request_id, status, review_state, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.revision_id,
                payload.tenant_id,
                payload.region.value,
                payload.claim_id,
                payload.subject.value,
                canonical_json_text(payload.scope),
                canonical_json_text(payload.rule),
                payload.authority.value,
                payload.policy_family,
                _iso(payload.valid_from),
                _iso(payload.valid_to),
                _iso(payload.system_from),
                payload.source_id,
                payload.source_clause_id,
                canonical_json_text(payload.evidence),
                canonical_json_text(payload.extraction),
                payload_json,
                record.payload_hash,
                record.signature,
                record.key_id,
                record.origin.value,
                record.remote_request_id,
                payload.status.value,
                record.review_state,
                _iso(utc_now()),
            ),
        )

    def claim_rows(
        self,
        *,
        subject: str | None = None,
        include_review: bool = False,
        limit: int = 1000,
        connection: sqlite3.Connection | None = None,
    ) -> list[ClaimRevisionRecord]:
        sql = "SELECT * FROM claim_revisions WHERE tenant_id = ? AND region = ?"
        params: list[Any] = [self.tenant_id, self.region]
        if subject is not None:
            sql += " AND subject = ?"
            params.append(subject)
        if not include_review:
            sql += " AND status = ?"
            params.append(ClaimStatus.ACCEPTED.value)
        sql += " ORDER BY system_from ASC LIMIT ?"
        params.append(limit)
        with self._read(connection) as conn:
            rows = conn.execute(sql, params).fetchall()
            closures = {
                row["revision_id"]: row
                for row in conn.execute(
                    "SELECT * FROM revision_closures WHERE tenant_id = ? AND region = ?",
                    (self.tenant_id, self.region),
                )
            }
        return [self._claim_from_row(row, closures.get(row["revision_id"])) for row in rows]

    def claims_for_source(
        self, source_id: str, *, connection: sqlite3.Connection | None = None
    ) -> list[ClaimRevisionRecord]:
        with self._read(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM claim_revisions WHERE source_id = ? AND tenant_id = ? AND region = ? "
                "ORDER BY created_at ASC",
                (source_id, self.tenant_id, self.region),
            ).fetchall()
            closures = {
                row["revision_id"]: row
                for row in conn.execute(
                    "SELECT * FROM revision_closures WHERE tenant_id = ? AND region = ?",
                    (self.tenant_id, self.region),
                )
            }
        return [self._claim_from_row(row, closures.get(row["revision_id"])) for row in rows]

    def get_claim(
        self, revision_id: str, *, connection: sqlite3.Connection | None = None
    ) -> ClaimRevisionRecord | None:
        with self._read(connection) as conn:
            row = conn.execute(
                "SELECT * FROM claim_revisions WHERE revision_id = ? AND tenant_id = ? AND region = ?",
                (revision_id, self.tenant_id, self.region),
            ).fetchone()
            closure = None
            if row is not None:
                closure = conn.execute(
                    "SELECT * FROM revision_closures WHERE revision_id = ?",
                    (revision_id,),
                ).fetchone()
        return self._claim_from_row(row, closure) if row else None

    def _claim_from_row(
        self, row: sqlite3.Row, closure: sqlite3.Row | None
    ) -> ClaimRevisionRecord:
        payload = ClaimRevision.model_validate_json(row["payload_json"])
        return ClaimRevisionRecord(
            payload=payload,
            payload_hash=row["payload_hash"],
            signature=row["signature"],
            key_id=row["key_id"],
            origin=ClaimOrigin(row["origin"]),
            remote_request_id=row["remote_request_id"],
            system_to=_parse_dt(closure["system_to"]) if closure else None,
            closed_by_closure_id=closure["closure_id"] if closure else None,
            review_state=row["review_state"],
        )

    def claim_views(
        self,
        *,
        subject: str | None = None,
        include_remote: bool = True,
        connection: sqlite3.Connection | None = None,
    ) -> list[ClaimView]:
        views: list[ClaimView] = []
        with self._read(connection) as conn:
            closures = {
                row["revision_id"]: row
                for row in conn.execute(
                    "SELECT * FROM revision_closures WHERE tenant_id = ? AND region = ?",
                    (self.tenant_id, self.region),
                )
            }
        carried_forward_ids: set[str] = set()
        for row in closures.values():
            try:
                carried_forward_ids.update(json.loads(row["carried_forward_revision_ids_json"]))
            except (TypeError, ValueError):
                continue
        for record in self.claim_rows(subject=subject, include_review=False, connection=connection):
            if not include_remote and record.origin is ClaimOrigin.REMOTE:
                continue
            closure = closures.get(record.payload.revision_id)
            views.append(
                ClaimView(
                    revision=record.payload,
                    system_to=record.system_to,
                    closure_kind=ClosureKind(closure["closure_kind"]) if closure else None,
                    superseding_source_id=closure["superseding_source_id"] if closure else None,
                    supersession_effective_from=(
                        _parse_dt(closure["effective_from"]) if closure else None
                    ),
                    carried_forward=record.payload.revision_id in carried_forward_ids,
                )
            )
        return views

    def insert_closure(self, connection: sqlite3.Connection, closure: RevisionClosure, *, signature: str, key_id: str) -> None:
        payload_json = canonical_json_text(closure)
        connection.execute(
            """
            INSERT INTO revision_closures (
                closure_id, tenant_id, region, revision_id, closure_kind, system_to,
                policy_family, superseding_source_id, replaced_clause_ids_json,
                replacement_revision_ids_json, carried_forward_revision_ids_json,
                effective_from, payload_json, payload_hash, signature, key_id, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                closure.closure_id,
                closure.tenant_id,
                closure.region.value,
                closure.revision_id,
                closure.closure_kind.value,
                _iso(closure.system_to),
                closure.policy_family,
                closure.superseding_source_id,
                canonical_json_text(closure.replaced_clause_ids),
                canonical_json_text(closure.replacement_revision_ids),
                canonical_json_text(closure.carried_forward_revision_ids),
                _iso(closure.effective_from),
                payload_json,
                _hash(payload_json),
                signature,
                key_id,
                _iso(closure.created_at),
            ),
        )

    def get_closure(self, closure_id: str) -> tuple[RevisionClosure, str, str, str] | None:
        with self.db.reader() as connection:
            row = connection.execute(
                "SELECT * FROM revision_closures WHERE closure_id = ? AND tenant_id = ? AND region = ?",
                (closure_id, self.tenant_id, self.region),
            ).fetchone()
        if row is None:
            return None
        return (
            RevisionClosure.model_validate_json(row["payload_json"]),
            row["payload_hash"],
            row["signature"],
            row["key_id"],
        )

    def closures_for_source(self, source_id: str) -> list[RevisionClosure]:
        with self.db.reader() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM revision_closures WHERE superseding_source_id = ?",
                (source_id,),
            ).fetchall()
        return [RevisionClosure.model_validate_json(row["payload_json"]) for row in rows]

    # -------------------------------------------------------------- review queue
    def insert_claim_review(
        self,
        *,
        source_id: str,
        reason_code: str,
        detail: dict,
        subject: str | None = None,
        connection: sqlite3.Connection | None = None,
        created_at: datetime | None = None,
    ) -> str:
        review_id = new_id("review")
        with self._read(connection) as conn:
            conn.execute(
                "INSERT INTO claim_reviews (review_id, tenant_id, region, source_id, subject, "
                "reason_code, detail_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    review_id,
                    self.tenant_id,
                    self.region,
                    source_id,
                    subject,
                    reason_code,
                    canonical_json_text(detail),
                    _iso(created_at or utc_now()),
                ),
            )
        return review_id

    def list_claim_reviews(self, *, source_id: str | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM claim_reviews WHERE tenant_id = ? AND region = ?"
        params: list[Any] = [self.tenant_id, self.region]
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.db.reader() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            {
                "review_id": row["review_id"],
                "source_id": row["source_id"],
                "subject": row["subject"],
                "reason_code": row["reason_code"],
                "detail": json.loads(row["detail_json"]),
                "created_at": row["created_at"],
                "resolved": bool(row["resolved"]),
            }
            for row in rows
        ]

    def pending_replacements(
        self,
        *,
        subject: str | None = None,
        known_at: datetime | None = None,
    ) -> list[dict]:
        """Pending markers active at a historical recipient knowledge cutoff."""

        moment = _iso(known_at or utc_now())
        sql = (
            "SELECT * FROM claim_reviews WHERE tenant_id = ? AND region = ? "
            "AND reason_code = 'pending_replacement' AND created_at <= ? "
            "AND (resolved = 0 OR (resolved_at IS NOT NULL AND resolved_at > ?))"
        )
        params: list[Any] = [self.tenant_id, self.region, moment, moment]
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        sql += " ORDER BY created_at DESC LIMIT 50"
        with self.db.reader() as connection:
            rows = connection.execute(sql, params).fetchall()
        out: list[dict] = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"])
            except (TypeError, ValueError):
                detail = {}
            out.append(
                {
                    "review_id": row["review_id"],
                    "source_id": row["source_id"],
                    "subject": row["subject"],
                    "reason_code": row["reason_code"],
                    "detail": detail,
                    "created_at": row["created_at"],
                    "resolved_at": row["resolved_at"],
                }
            )
        return out

    def resolve_claim_review(
        self, review_id: str, *, resolved_at: datetime | None = None
    ) -> bool:
        """Resolve one review marker at a recorded knowledge time."""

        moment = _iso(resolved_at or utc_now())
        with self.db.transaction() as connection:
            cursor = connection.execute(
                "UPDATE claim_reviews SET resolved = 1, resolved_at = ? "
                "WHERE review_id = ? AND tenant_id = ? AND region = ? AND resolved = 0",
                (moment, review_id, self.tenant_id, self.region),
            )
        return cursor.rowcount == 1

    # ------------------------------------------------------------------ findings
    def insert_finding_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        payload: FindingPayload,
        signature: str,
        key_id: str,
        alert: bool,
        snapshot_id: str | None = None,
    ) -> str:
        snapshot = snapshot_id or new_id("fsnap")
        payload_json = canonical_json_text(payload)
        connection.execute(
            """
            INSERT INTO finding_snapshots (snapshot_id, tenant_id, region, finding_id,
                finding_key, payload_json, payload_hash, signature, key_id, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot,
                self.tenant_id,
                self.region,
                payload.finding_id,
                payload.finding_key,
                payload_json,
                _hash(payload_json),
                signature,
                key_id,
                _iso(payload.created_at),
            ),
        )
        existing = connection.execute(
            "SELECT finding_id, review_state, current_snapshot_id FROM findings WHERE "
            "tenant_id = ? AND region = ? AND finding_key = ?",
            (self.tenant_id, self.region, payload.finding_key),
        ).fetchone()
        now = _iso(utc_now())
        if existing is None:
            connection.execute(
                """
                INSERT INTO findings (finding_id, tenant_id, region, finding_key, finding_type,
                    severity, subject, alert, claim_revision_ids_json, current_snapshot_id,
                    review_state, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload.finding_id,
                    self.tenant_id,
                    self.region,
                    payload.finding_key,
                    payload.finding_type.value,
                    payload.severity.value,
                    payload.subject.value,
                    int(alert),
                    canonical_json_text(payload.claim_revision_ids),
                    snapshot,
                    ReviewState.OPEN.value,
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                "UPDATE findings SET current_snapshot_id = ?, finding_type = ?, severity = ?, "
                "alert = ?, claim_revision_ids_json = ?, updated_at = ? WHERE finding_id = ?",
                (
                    snapshot,
                    payload.finding_type.value,
                    payload.severity.value,
                    int(alert),
                    canonical_json_text(payload.claim_revision_ids),
                    now,
                    payload.finding_id,
                ),
            )
            connection.execute(
                "UPDATE finding_snapshots SET superseded_by = ? WHERE snapshot_id = ?",
                (snapshot, existing["current_snapshot_id"]),
            )
        return snapshot

    def finding_keys(self, *, connection: sqlite3.Connection | None = None) -> set[str]:
        with self._read(connection) as conn:
            rows = conn.execute(
                "SELECT finding_key FROM findings WHERE tenant_id = ? AND region = ?",
                (self.tenant_id, self.region),
            ).fetchall()
        return {row["finding_key"] for row in rows}

    def list_findings(
        self,
        *,
        finding_type: str | None = None,
        alert: bool | None = None,
        review_state: str | None = None,
        revision_id: str | None = None,
        limit: int = 200,
        connection: sqlite3.Connection | None = None,
    ) -> list[FindingRecord]:
        sql = (
            "SELECT f.*, s.payload_json AS snap_json, s.payload_hash AS snap_hash, "
            "s.signature AS snap_sig, s.key_id AS snap_key, s.superseded_by AS snap_superseded "
            "FROM findings f JOIN finding_snapshots s ON f.current_snapshot_id = s.snapshot_id "
            "WHERE f.tenant_id = ? AND f.region = ?"
        )
        params: list[Any] = [self.tenant_id, self.region]
        if finding_type:
            sql += " AND f.finding_type = ?"
            params.append(finding_type)
        if alert is not None:
            sql += " AND f.alert = ?"
            params.append(int(alert))
        if review_state:
            sql += " AND f.review_state = ?"
            params.append(review_state)
        sql += " ORDER BY f.created_at ASC LIMIT ?"
        params.append(limit)
        with self._read(connection) as conn:
            rows = conn.execute(sql, params).fetchall()
        records: list[FindingRecord] = []
        for row in rows:
            payload = FindingPayload.model_validate_json(row["snap_json"])
            if revision_id and revision_id not in payload.claim_revision_ids:
                continue
            records.append(
                FindingRecord(
                    payload=payload,
                    snapshot_id=row["current_snapshot_id"],
                    snapshot_hash=row["snap_hash"],
                    signature=row["snap_sig"],
                    key_id=row["snap_key"],
                    review_state=ReviewState(row["review_state"]),
                    superseded_by_snapshot_id=row["snap_superseded"],
                )
            )
        return records

    def get_finding(
        self, finding_id: str, *, connection: sqlite3.Connection | None = None
    ) -> FindingRecord | None:
        with self._read(connection) as conn:
            row = conn.execute(
                "SELECT f.*, s.payload_json AS snap_json, s.payload_hash AS snap_hash, "
                "s.signature AS snap_sig, s.key_id AS snap_key, s.superseded_by AS snap_superseded "
                "FROM findings f JOIN finding_snapshots s ON f.current_snapshot_id = s.snapshot_id "
                "WHERE f.finding_id = ? AND f.tenant_id = ? AND f.region = ?",
                (finding_id, self.tenant_id, self.region),
            ).fetchone()
        if row is None:
            return None
        return FindingRecord(
            payload=FindingPayload.model_validate_json(row["snap_json"]),
            snapshot_id=row["current_snapshot_id"],
            snapshot_hash=row["snap_hash"],
            signature=row["snap_sig"],
            key_id=row["snap_key"],
            review_state=ReviewState(row["review_state"]),
            superseded_by_snapshot_id=row["snap_superseded"],
        )

    def finding_snapshots(
        self, finding_id: str, *, connection: sqlite3.Connection | None = None
    ) -> list[dict]:
        with self._read(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM finding_snapshots WHERE finding_id = ? ORDER BY created_at ASC",
                (finding_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_review_event(
        self,
        connection: sqlite3.Connection,
        event: ReviewEvent,
        *,
        signature: str,
        key_id: str,
    ) -> None:
        payload_json = canonical_json_text(event)
        prev = connection.execute(
            "SELECT payload_hash FROM review_events WHERE tenant_id = ? AND region = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (self.tenant_id, self.region),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO review_events (event_id, tenant_id, region, finding_id, snapshot_id,
                actor, action, reason, prior_state, new_state, referenced_revision_ids_json,
                payload_json, payload_hash, signature, key_id, prev_hash, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                self.tenant_id,
                self.region,
                event.finding_id,
                event.snapshot_id,
                event.actor,
                event.action.value,
                event.reason,
                event.prior_state.value,
                event.new_state.value,
                canonical_json_text(event.referenced_revision_ids),
                payload_json,
                _hash(payload_json),
                signature,
                key_id,
                prev["payload_hash"] if prev else None,
                _iso(event.created_at),
            ),
        )
        connection.execute(
            "UPDATE findings SET review_state = ?, updated_at = ? WHERE finding_id = ?",
            (event.new_state.value, _iso(event.created_at), event.finding_id),
        )

    def review_events(self, finding_id: str) -> list[ReviewEvent]:
        with self.db.reader() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM review_events WHERE finding_id = ? ORDER BY created_at ASC",
                (finding_id,),
            ).fetchall()
        return [ReviewEvent.model_validate_json(row["payload_json"]) for row in rows]

    # ------------------------------------------------------------------- answers
    def insert_answer(
        self,
        connection: sqlite3.Connection,
        record: AnswerRecord,
    ) -> None:
        payload = record.payload
        payload_json = canonical_json_text(payload)
        connection.execute(
            """
            INSERT INTO answers (answer_id, tenant_id, region, status, question, query_hash,
                answer_text_hash, valid_at, known_at, payload_json, payload_hash, signature,
                key_id, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.answer_id,
                self.tenant_id,
                self.region,
                payload.status.value,
                payload.question,
                payload.query_hash,
                payload.answer_text_hash,
                _iso(payload.valid_at),
                _iso(payload.known_at),
                payload_json,
                record.payload_hash,
                record.signature,
                record.key_id,
                _iso(payload.created_at),
            ),
        )

    def get_answer(self, answer_id: str) -> AnswerRecord | None:
        with self.db.reader() as connection:
            row = connection.execute(
                "SELECT * FROM answers WHERE answer_id = ? AND tenant_id = ? AND region = ?",
                (answer_id, self.tenant_id, self.region),
            ).fetchone()
        if row is None:
            return None
        payload = AnswerPayload.model_validate_json(row["payload_json"])
        return AnswerRecord(
            payload=payload,
            payload_hash=row["payload_hash"],
            signature=row["signature"],
            key_id=row["key_id"],
            answer_text_hash=row["answer_text_hash"],
        )

    # ---------------------------------------------------------------- graph
    def upsert_node(
        self,
        connection: sqlite3.Connection,
        *,
        node_id: str,
        node_type: str,
        label: str,
        attributes: dict | None = None,
        restricted: bool = False,
    ) -> None:
        connection.execute(
            "INSERT INTO nodes (node_id, tenant_id, region, node_type, label, attributes_json, "
            "restricted) VALUES (?,?,?,?,?,?,?) ON CONFLICT (node_id) DO UPDATE SET "
            "label = excluded.label, attributes_json = excluded.attributes_json",
            (
                node_id,
                self.tenant_id,
                self.region,
                node_type,
                label,
                canonical_json_text(attributes or {}),
                int(restricted),
            ),
        )

    def upsert_edge(
        self,
        connection: sqlite3.Connection,
        *,
        edge_type: str,
        from_node_id: str,
        to_node_id: str,
        attributes: dict | None = None,
    ) -> None:
        edge_id = f"edge_{edge_type}_{from_node_id}_{to_node_id}"[:120]
        connection.execute(
            "INSERT OR IGNORE INTO edges (edge_id, tenant_id, region, edge_type, from_node_id, "
            "to_node_id, attributes_json) VALUES (?,?,?,?,?,?,?)",
            (
                edge_id,
                self.tenant_id,
                self.region,
                edge_type,
                from_node_id,
                to_node_id,
                canonical_json_text(attributes or {}),
            ),
        )

    def nodes_for(self, node_ids: Iterable[str]) -> list[dict]:
        ids = list(dict.fromkeys(node_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.db.reader() as connection:
            rows = connection.execute(
                f"SELECT * FROM nodes WHERE node_id IN ({placeholders}) AND tenant_id = ? "
                "AND region = ?",
                (*ids, self.tenant_id, self.region),
            ).fetchall()
        return [dict(row) for row in rows]

    def edges_touching(self, node_ids: Iterable[str]) -> list[dict]:
        ids = list(dict.fromkeys(node_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.db.reader() as connection:
            rows = connection.execute(
                f"SELECT * FROM edges WHERE (from_node_id IN ({placeholders}) "
                f"OR to_node_id IN ({placeholders})) AND tenant_id = ? AND region = ?",
                (*ids, *ids, self.tenant_id, self.region),
            ).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------- egress
    def record_egress(
        self,
        connection: sqlite3.Connection,
        event: EgressEvent,
    ) -> None:
        payload_json = canonical_json_text(event)
        prev = connection.execute(
            "SELECT payload_sha256 FROM egress_events WHERE tenant_id = ? AND region = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (self.tenant_id, self.region),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO egress_events (event_id, tenant_id, region, channel, destination,
                request_id, payload_type, payload_bytes, payload_sha256, raw_source_bytes,
                outcome, error_code, model_metadata_json, prev_hash, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.event_id,
                self.tenant_id,
                self.region,
                event.channel.value,
                event.destination,
                event.request_id,
                event.payload_type,
                event.payload_bytes,
                event.payload_sha256,
                event.raw_source_bytes,
                event.outcome.value,
                event.error_code,
                canonical_json_text(event.model_metadata) if event.model_metadata else None,
                prev["payload_sha256"] if prev else None,
                _iso(event.created_at),
            ),
        )

    def summarize_egress(self) -> EgressSummary:
        with self.db.reader() as connection:
            row = connection.execute(
                """
                SELECT
                  SUM(CASE WHEN channel = ? THEN 1 ELSE 0 END) AS o2o_events,
                  SUM(CASE WHEN channel = ? THEN payload_bytes ELSE 0 END) AS o2o_bytes,
                  SUM(CASE WHEN channel = ? THEN raw_source_bytes ELSE 0 END) AS raw_bytes,
                  SUM(CASE WHEN channel = ? THEN 1 ELSE 0 END) AS model_events,
                  SUM(CASE WHEN channel = ? THEN payload_bytes ELSE 0 END) AS model_bytes,
                  SUM(CASE WHEN outcome = ? THEN 1 ELSE 0 END) AS blocked,
                  SUM(CASE WHEN outcome IN (?, ?) THEN 1 ELSE 0 END) AS failed
                FROM egress_events WHERE tenant_id = ? AND region = ?
                """,
                (
                    EgressChannel.OFFICE_TO_OFFICE.value,
                    EgressChannel.OFFICE_TO_OFFICE.value,
                    EgressChannel.OFFICE_TO_OFFICE.value,
                    EgressChannel.HOSTED_MODEL.value,
                    EgressChannel.HOSTED_MODEL.value,
                    EgressOutcome.BLOCKED.value,
                    EgressOutcome.FAILED.value,
                    EgressOutcome.TIMEOUT.value,
                    self.tenant_id,
                    self.region,
                ),
            ).fetchone()
        return EgressSummary(
            region=Region(self.region),
            office_to_office_events=row["o2o_events"] or 0,
            office_to_office_bytes=row["o2o_bytes"] or 0,
            hosted_model_events=row["model_events"] or 0,
            hosted_model_request_bytes=row["model_bytes"] or 0,
            raw_source_text_bytes_between_offices=row["raw_bytes"] or 0,
            blocked_exports=row["blocked"] or 0,
            failed_transfers=row["failed"] or 0,
            generated_at=utc_now(),
        )

    def egress_events(self, *, limit: int = 100) -> list[EgressEvent]:
        with self.db.reader() as connection:
            rows = connection.execute(
                "SELECT * FROM egress_events WHERE tenant_id = ? AND region = ? "
                "ORDER BY rowid DESC LIMIT ?",
                (self.tenant_id, self.region, limit),
            ).fetchall()
        events = []
        for row in rows:
            events.append(
                EgressEvent(
                    event_id=row["event_id"],
                    tenant_id=row["tenant_id"],
                    region=Region(row["region"]),
                    channel=EgressChannel(row["channel"]),
                    destination=row["destination"],
                    request_id=row["request_id"],
                    payload_type=row["payload_type"],
                    payload_bytes=row["payload_bytes"],
                    payload_sha256=row["payload_sha256"],
                    raw_source_bytes=row["raw_source_bytes"],
                    outcome=EgressOutcome(row["outcome"]),
                    error_code=row["error_code"],
                    model_metadata=(
                        json.loads(row["model_metadata_json"]) if row["model_metadata_json"] else None
                    ),
                    created_at=_parse_dt(row["created_at"]),
                    prev_hash=row["prev_hash"],
                )
            )
        return events

    # --------------------------------------------------------------- model calls
    def record_model_call(
        self,
        connection: sqlite3.Connection,
        *,
        call_id: str,
        job_id: str | None,
        source_id: str | None,
        mode: str,
        provider: str,
        route: str | None,
        model: str | None,
        prompt_version: str,
        schema_version: str,
        attempts: int,
        latency_ms: int | None,
        usage: dict,
        status: str,
        error_code: str | None,
        cache_key: str | None,
        raw_output_sha256: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO model_calls (call_id, tenant_id, region, job_id, source_id, mode,
                provider, route, model, prompt_version, schema_version, attempts, latency_ms,
                usage_json, status, error_code, cache_key, raw_output_sha256, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                call_id,
                self.tenant_id,
                self.region,
                job_id,
                source_id,
                mode,
                provider,
                route,
                model,
                prompt_version,
                schema_version,
                attempts,
                latency_ms,
                canonical_json_text(usage or {}),
                status,
                error_code,
                cache_key,
                raw_output_sha256,
                _iso(utc_now()),
            ),
        )

    def model_call_stats(self) -> dict:
        with self.db.reader() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS calls, SUM(attempts) AS attempts FROM model_calls "
                "WHERE tenant_id = ? AND region = ?",
                (self.tenant_id, self.region),
            ).fetchone()
            usage_rows = connection.execute(
                "SELECT usage_json FROM model_calls WHERE tenant_id = ? AND region = ?",
                (self.tenant_id, self.region),
            ).fetchall()
        totals: dict[str, int] = {}
        for item in usage_rows:
            for key, value in json.loads(item["usage_json"]).items():
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
        return {
            "calls": row["calls"] or 0,
            "attempts": row["attempts"] or 0,
            "usage_totals": totals,
        }

    # ------------------------------------------------------------------- hygiene
    def counts(self, *, connection: sqlite3.Connection | None = None) -> dict[str, int]:
        tables = [
            "sources",
            "clauses",
            "claim_revisions",
            "revision_closures",
            "findings",
            "finding_snapshots",
            "answers",
            "jobs",
            "claim_reviews",
            "egress_events",
            "model_calls",
        ]
        out: dict[str, int] = {}
        with self._read(connection) as conn:
            for table in tables:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = ? AND region = ?",
                    (self.tenant_id, self.region),
                ).fetchone()
                out[table] = row["n"] if row else 0
        return out
