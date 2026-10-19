"""Knowledge snapshots over the two time axes.

A snapshot at ``(valid_at, known_at)`` contains revisions where

    valid_from  <= valid_at  < valid_to      (effective interval)
    system_from <= known_at  < system_to     (knowledge interval)

Closed revisions remain queryable for ``known_at`` values inside their knowledge
interval; nothing about them is rewritten when a replacement is learned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from ..contracts.common import Subject, ensure_utc
from ..rules.compare import ClaimView


def in_snapshot(
    view: ClaimView,
    *,
    valid_at: datetime,
    known_at: datetime,
    include_remote: bool = True,
) -> bool:
    if not include_remote and view.revision.origin.value == "remote":
        return False
    valid_at = ensure_utc(valid_at)
    known_at = ensure_utc(known_at)
    revision = view.revision
    if revision.valid_from is not None and valid_at < revision.valid_from:
        return False
    if revision.valid_to is not None and valid_at >= revision.valid_to:
        return False
    if known_at < revision.system_from:
        return False
    if view.system_to is not None and known_at >= view.system_to:
        return False
    return True


def select_snapshot(
    views: Sequence[ClaimView],
    *,
    valid_at: datetime,
    known_at: datetime,
    subject: Subject | None = None,
) -> list[ClaimView]:
    return [
        view
        for view in views
        if (subject is None or view.revision.subject is subject)
        and in_snapshot(view, valid_at=valid_at, known_at=known_at)
    ]


def select_current(
    views: Sequence[ClaimView], *, known_at: datetime, subject: Subject | None = None
) -> list[ClaimView]:
    """Revisions the system currently holds as knowledge at ``known_at``."""

    return [
        view
        for view in views
        if (subject is None or view.revision.subject is subject)
        and view.system_to is None
        and view.revision.system_from <= ensure_utc(known_at)
    ]


def knowledge_checkpoints(views: Sequence[ClaimView]) -> list[datetime]:
    """Real ingestion checkpoints available for ``known_at`` demonstrations."""

    moments = {view.revision.system_from for view in views}
    for view in views:
        if view.system_to is not None:
            moments.add(view.system_to)
    return sorted(moments)
