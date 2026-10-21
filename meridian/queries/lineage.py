"""Graph-shaped lineage for answers, findings and claim revisions.

Lineage is returned as nodes and edges for a future UI.  Restricted nodes are omitted
entirely for principals that are not allowed to read restricted sources, and traversal
does not continue through them, so counts and neighbour names cannot reveal them.
"""

from __future__ import annotations

import json

from ..contracts.common import canonical_datetime
from ..contracts.qa import LineageEdge, LineageGraph, LineageNode
from ..storage.store import OfficeStore

MAX_NODES = 400


def _node_authorized(store: OfficeStore, row: dict, *, allowed_restricted: bool) -> bool:
    """Authorize a graph object from its underlying local source provenance."""

    if bool(row["restricted"]) and not allowed_restricted:
        return False
    node_id = str(row["node_id"])
    node_type = str(row["node_type"])

    def source_allowed(source_id: str | None) -> bool:
        if not source_id:
            return False
        source = store.get_source(source_id)
        return source is not None and (allowed_restricted or not source.restricted)

    if node_type in {"source", "version"}:
        return source_allowed(node_id.removeprefix("source:"))
    if node_type in {"clause", "message"}:
        clause = store.get_clause(node_id.removeprefix("clause:"))
        return (
            clause is not None
            and (allowed_restricted or not clause.restricted)
            and source_allowed(clause.source_id)
        )
    if node_type in {"revision", "claim_revision"}:
        revision_id = node_id.removeprefix("revision:")
        record = store.get_claim(revision_id)
        if record is None:
            # Remote revisions are separately namespaced and contain no source text.
            return False
        return source_allowed(record.payload.source_id)
    if node_type == "document":
        identity = node_id.removeprefix("document:")
        return any(source.source_identity == identity and source_allowed(source.source_id)
                   for source in store.list_sources())
    if node_type == "finding":
        finding = store.get_finding(node_id.removeprefix("finding:"))
        if finding is None:
            return False
        for revision_id in finding.payload.claim_revision_ids:
            claim = store.get_claim(revision_id)
            if claim is None or not source_allowed(claim.payload.source_id):
                return False
        return True
    if node_type == "answer":
        answer = store.get_answer(node_id.removeprefix("answer:"))
        if answer is None:
            return False
        try:
            source_ids = answer.payload.local_source_ids()
        except (ValueError, TypeError):
            return False
        for source_id in source_ids:
            if not source_allowed(source_id):
                return False
        return True
    return True


def lineage_for_node(
    store: OfficeStore,
    root_id: str,
    *,
    allowed_restricted: bool,
    max_nodes: int = MAX_NODES,
) -> LineageGraph:
    nodes: dict[str, LineageNode] = {}
    edges: dict[str, LineageEdge] = {}
    frontier = [root_id]
    seen: set[str] = set()
    truncated = False

    while frontier:
        current = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        if len(nodes) >= max_nodes:
            truncated = True
            break
        current_rows = store.nodes_for([current])
        if not current_rows:
            continue
        row = current_rows[0]
        if not _node_authorized(store, row, allowed_restricted=allowed_restricted):
            # Never traverse out of a derived node whose full provenance cannot be
            # disclosed to this caller, even if its graph row was marked public.
            continue
        attributes = json.loads(row["attributes_json"] or "{}")
        # Only enrich after provenance authorization. These are stored passages,
        # not model-written explanations or verification results.
        node_id = row["node_id"]
        if node_id.startswith("revision:"):
            record = store.get_claim(node_id.removeprefix("revision:"))
            if record:
                claim = record.payload
                attributes.update(source_id=claim.source_id, source_identity=claim.source_identity,
                                  version_label=claim.source_version_label, quote=claim.evidence.quote,
                                  page=claim.evidence.page, section=claim.evidence.section or "",
                                  clause_id=claim.evidence.clause_id,
                                  start_char=claim.evidence.start_char, end_char=claim.evidence.end_char,
                                  extraction_mode=claim.extraction.mode)
        elif node_id.startswith("clause:"):
            clause = store.get_clause(node_id.removeprefix("clause:"))
            if clause:
                attributes.update(source_id=clause.source_id, quote=clause.text,
                                  page=clause.page, section=clause.section or "")
                source = store.get_source(clause.source_id)
                if source:
                    attributes.update(source_identity=source.source_identity,
                                      version_label=source.version_label)
        elif node_id.startswith("source:"):
            source = store.get_source(node_id.removeprefix("source:"))
            if source:
                attributes.update(source_id=source.source_id, source_identity=source.source_identity,
                                  version_label=source.version_label)
        elif node_id.startswith("answer:"):
            record = store.get_answer(node_id.removeprefix("answer:"))
            if record:
                attributes.update(question=record.payload.question,
                                  created_at=canonical_datetime(record.payload.created_at))
        nodes[row["node_id"]] = LineageNode(
            node_id=row["node_id"],
            node_type=row["node_type"],
            label=row["label"],
            attributes={k: str(v) for k, v in attributes.items()},
            restricted=bool(row["restricted"]),
        )
        for row in store.edges_touching([current]):
            other = (
                row["to_node_id"] if row["from_node_id"] == current else row["from_node_id"]
            )
            edges[row["edge_id"]] = LineageEdge(
                edge_id=row["edge_id"],
                edge_type=row["edge_type"],
                from_node_id=row["from_node_id"],
                to_node_id=row["to_node_id"],
                attributes={
                    k: str(v) for k, v in json.loads(row["attributes_json"] or "{}").items()
                },
            )
            if other not in seen:
                frontier.append(other)

    # Everything reachable through the frontier was collected; drop dangling edges.
    valid_ids = set(nodes)
    final_edges = [
        edge
        for edge in edges.values()
        if edge.from_node_id in valid_ids and edge.to_node_id in valid_ids
    ]
    return LineageGraph(
        root_id=root_id,
        nodes=sorted(nodes.values(), key=lambda item: item.node_id),
        edges=sorted(final_edges, key=lambda item: item.edge_id),
        truncated=truncated,
    )
