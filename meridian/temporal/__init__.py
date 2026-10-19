"""Temporal history: knowledge snapshots and explicit scoped supersession."""

from .snapshots import in_snapshot, knowledge_checkpoints, select_current, select_snapshot
from .supersession import SupersessionOutcome, apply_manifest_supersession

__all__ = [
    "SupersessionOutcome",
    "apply_manifest_supersession",
    "in_snapshot",
    "knowledge_checkpoints",
    "select_current",
    "select_snapshot",
]
