import { ArrowDown, ArrowRight, BookOpen, CircleDot, FileText, GitBranch, LockKeyhole, MessageSquare, Network, ShieldQuestion } from "lucide-react";
import type { LineageGraph, LineageNode } from "./types";
import { humanize } from "./presentation";
import { lineageGroups, lineageNodeTitle } from "./verification";

const relationLabels: Record<string, string> = { CITES: "Cites", FINDS_BETWEEN: "Compares", EXTRACTED_FROM: "Extracted from", IN_VERSION: "Belongs to", SUPERSEDES: "Replaces" };
export function nodeIcon(type: string) {
  return type === "message" ? MessageSquare : ["version", "source", "document"].includes(type) ? FileText : type === "finding" || type === "answer" ? GitBranch : type === "remote_reference" ? LockKeyhole : BookOpen;
}
export default function Lineage({ graph, nodeId, search, onSelect, onInspect, onCheckSource, onFinding, supplied = false }: {
  graph: LineageGraph; nodeId: string; search: string; onSelect: (id: string) => void;
  onInspect: (node: LineageNode) => void; onCheckSource: (id: string) => void;
  onFinding: (id: string) => void; supplied?: boolean;
}) {
  const selectedId = nodeId || graph.root_id;
  const selected = graph.nodes.find(node => node.node_id === selectedId);
  const query = search.trim().toLowerCase();
  const visible = graph.nodes.filter(node => !query || `${lineageNodeTitle(node)} ${node.node_id} ${Object.values(node.attributes).join(" ")}`.toLowerCase().includes(query));
  const related = graph.edges.filter(edge => edge.from_node_id === selectedId || edge.to_node_id === selectedId);
  const sourceId = selected?.attributes.source_id;
  function recordLink(node: LineageNode) {
    return <button onClick={() => onSelect(node.node_id)}><span>{lineageNodeTitle(node)}</span>
      {node.attributes.version_label && <span className="source-version">{node.attributes.version_label}</span>}
      {node.node_type === "finding" && <span className="lineage-finding-tag">#{node.node_id.slice(-8).toUpperCase()}</span>}
      {node.attributes.quote && <span className="lineage-relation-excerpt">{node.attributes.quote}</span>}
    </button>;
  }
  return <>
    {supplied && <p className="lineage-supplied"><ShieldQuestion size={15} />Connections shown here come from the supplied bundle. Check the results above before relying on them.</p>}
    {graph.truncated && <div className="notice warning" role="status">This trace reached its display limit. Some connections are not shown.</div>}
    <div className="lineage-map" aria-label="Evidence connections">
      {lineageGroups.map((group, index) => {
        const nodes = visible.filter(node => group.types.includes(node.node_type));
        return <section className="lineage-lane" key={group.label} aria-label={group.label}>
          <h3><span>{group.label}</span><span>{nodes.length}</span>{index < 3 && <ArrowRight size={14} aria-hidden="true" />}</h3>
          <ul>{nodes.map(node => {
            const Icon = nodeIcon(node.node_type); const connected = related.some(edge => edge.from_node_id === node.node_id || edge.to_node_id === node.node_id);
            return <li key={node.node_id}><button type="button" data-lineage-node={node.node_id} className={`lineage-node ${selectedId === node.node_id ? "selected" : connected ? "connected" : ""}`} aria-pressed={selectedId === node.node_id} onClick={() => onSelect(node.node_id)}>
              <span className="lineage-node-type"><Icon size={14} />{({ claim_revision: "Statement", revision: "Statement", version: "Source version", clause: "Passage", message: "Slack message", remote_reference: "Remote reference" } as Record<string, string>)[node.node_type] || humanize(node.node_type)}{node.node_id === graph.root_id && <span className="lineage-root">Start</span>}</span>
              <strong>{lineageNodeTitle(node)}</strong>
              {node.node_type === "finding" && <span className="lineage-finding-tag">#{node.node_id.slice(-8).toUpperCase()}</span>}
              {node.attributes.version_label && <span className="source-version">{node.attributes.version_label}</span>}
              {node.attributes.quote && !["answer"].includes(node.node_type) && <span className="lineage-excerpt">{node.attributes.quote}</span>}
              {node.attributes.page && <span className="lineage-locator">Page {node.attributes.page}{node.attributes.section ? ` · § ${node.attributes.section}` : ""}</span>}
            </button></li>;
          })}</ul>
          {!nodes.length && <p className="lineage-lane-empty">{query ? "No matches" : "None in this trace"}</p>}
        </section>;
      })}
    </div>
    <section className="lineage-inspector" aria-labelledby="lineage-inspector-title">
      {selected ? <>
        <div className="lineage-inspector-heading"><div><span className="eyebrow">{humanize(selected.node_type)}</span><h3 id="lineage-inspector-title">{lineageNodeTitle(selected)}</h3>{selected.attributes.version_label && <span className="source-version">{selected.attributes.version_label}</span>}</div><span className="integrity-unchecked"><CircleDot size={13} />Recorded provenance</span></div>
        {selected.attributes.quote && <blockquote>{selected.attributes.quote}</blockquote>}
        <div className="lineage-inspector-actions">
          {!supplied && sourceId && <><button className="button secondary" onClick={() => onInspect(selected)}><FileText size={15} />Inspect source</button><button className="text-button" onClick={() => onCheckSource(sourceId)}>Check source copy<ArrowRight size={14} /></button></>}
          {!supplied && selected.node_type === "finding" && <button className="text-button" onClick={() => onFinding(selected.node_id.slice("finding:".length))}>Open finding<ArrowRight size={14} /></button>}
        </div>
        <div className="lineage-relations"><h4>Direct connections <span>{related.length}</span></h4>{related.length ? <ul>{related.map(edge => {
          const from = graph.nodes.find(node => node.node_id === edge.from_node_id)!; const to = graph.nodes.find(node => node.node_id === edge.to_node_id)!;
          return <li key={edge.edge_id}>{recordLink(from)}<span><ArrowDown size={12} />{relationLabels[edge.edge_type] || humanize(edge.edge_type)}</span>{recordLink(to)}</li>;
        })}</ul> : <p>No direct connections were returned for this node.</p>}</div>
        <details className="lineage-technical"><summary>Record details</summary><dl><dt>Node</dt><dd>{selected.node_id}</dd>{Object.entries(selected.attributes).filter(([key]) => !["quote", "source_identity", "version_label"].includes(key)).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value || "Not recorded"}</dd></div>)}</dl></details>
      </> : <div className="lineage-unavailable"><Network size={22} /><h3 id="lineage-inspector-title">Node unavailable</h3><p>The linked node is not part of this authorized trace.</p><button className="button secondary" onClick={() => onSelect(graph.root_id)}>Return to the start</button></div>}
    </section>
  </>;
}
