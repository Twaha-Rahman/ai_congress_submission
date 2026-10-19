"""SQLite connection handling and migration application."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .migrations import MIGRATIONS

SCHEMA_VERSION = MIGRATIONS[-1][0]


class Database:
    """Thin sqlite3 wrapper: one office database per instance."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._write_lock = threading.RLock()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ connection
    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if str(self.path) != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Serialised write transaction; all publication is transactional."""

        with self._write_lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:  # pragma: no cover - defensive
                    pass
                raise
            finally:
                connection.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------------ migration
    def migrate(self) -> int:
        """Apply pending migrations.

        ``executescript`` implicitly commits any open transaction, so migrations are
        run outside an explicit ``BEGIN`` while holding the process-wide write lock.
        Every migration script is idempotent (``IF NOT EXISTS``), and the version row
        is written immediately after its script.
        """

        with self._write_lock:
            connection = self.connect()
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                applied = {
                    row["version"]
                    for row in connection.execute("SELECT version FROM schema_migrations")
                }
                for version, script in MIGRATIONS:
                    if version in applied:
                        continue
                    connection.executescript(script)
                    connection.execute(
                        "INSERT INTO schema_migrations (version, applied_at) "
                        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                        (version,),
                    )
            finally:
                connection.close()
        return SCHEMA_VERSION

    def has_table(self, name: str) -> bool:
        with self.reader() as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
                (name,),
            ).fetchone()
        return row is not None

    def integrity_check(self) -> str:
        with self.reader() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"
