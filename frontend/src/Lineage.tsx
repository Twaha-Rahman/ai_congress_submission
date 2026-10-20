import { useEffect, useRef, useState, type RefObject } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, BookOpen, CircleDot, FileText, GitBranch, LockKeyhole, MessageSquare, Network, ShieldQuestion } from "lucide-react";
import type { LineageGraph, LineageNode } from "./types";
import { humanize, sourceTitle } from "./presentation";
import { lineageGroups, lineageNodes, lineageNodeTitle } from "./verification";

const relationLabels: Record<string, string> = { CITES: "Cites", FINDS_BETWEEN: "Compares", EXTRACTED_FROM: "Extracted from", IN_VERSION: "Belongs to", SUPERSEDES: "Replaces" };
export function nodeIcon(type: string) {
  return type === "message" ? MessageSquare : ["version", "source", "document"].includes(type) ? FileText : type === "finding" || type === "answer" ? GitBranch : type === "remote_reference" ? LockKeyhole : BookOpen;
}
export default function Lineage({ graph, nodeId, search, group, pane, returnScroll, keyboardFocus, onGroup, onBack, onSelect, onInspect, onCheckSource, onFinding, supplied = false }: {
  graph: LineageGraph; nodeId: string; search: string; group: string; pane: "browse" | "detail";
  returnScroll: RefObject<number>;
  keyboardFocus: RefObject<boolean>;
  onGroup: (group: string) => void; onBack: () => void; onSelect: (id: string) => void;
  onInspect: (node: LineageNode) => void; onCheckSource: (id: string) => void;
  onFinding: (id: string) => void; supplied?: boolean;
}) {
  const selectedId = nodeId || graph.root_id;
  const selected = graph.nodes.find(node => node.node_id === selectedId);
  const visible = lineageNodes(graph, search);
  const activeGroup = group || lineageGroups.find(item => item.types.includes(selected?.node_type || ""))?.label || "Conclusions";
  const nodes = visible.filter(node => lineageGroups.find(item => item.label === activeGroup)?.types.includes(node.node_type));
  const related = graph.edges.filter(edge => edge.from_node_id === selectedId || edge.to_node_id === selectedId);
  const sourceId = selected?.attributes.source_id;
  const [limit, setLimit] = useState(8);
  const [relationLimit, setRelationLimit] = useState(3);
  const inspector = useRef<HTMLElement>(null);
  const browser = useRef<HTMLDivElement>(null);
  const previousPane = useRef("browse");
  const previousNode = useRef(selectedId);
  useEffect(() => { setLimit(8); }, [activeGroup, search, graph.root_id]);
  useEffect(() => { setRelationLimit(3); }, [selectedId]);
  useEffect(() => {
    // Keyboard selection can move beyond the initially rendered page.
    const index = nodes.findIndex(node => node.node_id === selectedId);
    if (index >= limit) setLimit(Math.ceil((index + 1) / 8) * 8);
  }, [selectedId, activeGroup, search, limit, nodes.length]);
  useEffect(() => {
    if (!keyboardFocus.current) return;
    if (window.matchMedia("(max-width: 760px)").matches) { keyboardFocus.current = false; return; }
    const element = [...browser.current?.querySelectorAll<HTMLElement>("[data-lineage-node]") || []].find(node => node.dataset.lineageNode === selectedId);
    if (!element) return; // Pagination renders the selected record on the next commit.
    keyboardFocus.current = false;
    element.focus({ preventScroll: true }); element.scrollIntoView({ block: "nearest" });
  }, [selectedId, activeGroup, limit]);
  useEffect(() => {
    if (window.matchMedia("(max-width: 760px)").matches) {
      if (pane === "detail" && (previousPane.current !== pane || previousNode.current !== selectedId)) {
        requestAnimationFrame(() => { inspector.current?.scrollIntoView({ block: "start" }); inspector.current?.focus({ preventScroll: true }); });
      } else if (pane === "browse" && previousPane.current === "detail") {
        requestAnimationFrame(() => { window.scrollTo({ top: returnScroll.current }); document.querySelector<HTMLElement>("[data-lineage-node][aria-pressed='true']")?.focus({ preventScroll: true }); });
      }
    }
    previousPane.current = pane; previousNode.current = selectedId;
  }, [pane, selectedId]);
  function recordLink(node: LineageNode) {
    return <button onClick={() => onSelect(node.node_id)}><span>{lineageNodeTitle(node)}</span>
      {node.attributes.version_label && <span className="source-version">{node.attributes.version_label}</span>}
      {node.node_type === "finding" && <span className="lineage-finding-tag">#{node.node_id.slice(-8).toUpperCase()}</span>}
      {node.attributes.quote && <span className="lineage-relation-excerpt">{node.attributes.quote}</span>}
    </button>;
  }
  return <>
    {supplied && <p className="lineage-supplied"><ShieldQuestion size={15} />These connections were supplied in the bundle. Run integrity checks before relying on them.</p>}
    {graph.truncated && <div className="notice warning" role="status">This trace reached its display limit. Some connections are not shown.</div>}
    <div className={`lineage-explorer pane-${pane}`}>
      <div className="lineage-browser" ref={browser}>
        <div className="lineage-groups" role="group" aria-label="Evidence groups">{lineageGroups.map(item => <button key={item.label} type="button" aria-pressed={activeGroup === item.label} onClick={() => onGroup(item.label)}>{item.label}<span>{visible.filter(node => item.types.includes(node.node_type)).length}</span></button>)}</div>
        <section className="lineage-records" aria-label={activeGroup}>
          <h3>{activeGroup}<span>{nodes.length} {nodes.length === 1 ? "record" : "records"}</span></h3>
          <ul>{nodes.slice(0, limit).map(node => {
            const Icon = nodeIcon(node.node_type);
            return <li key={node.node_id}><button type="button" data-lineage-node={node.node_id} className={`lineage-node ${selectedId === node.node_id ? "selected" : ""}`} aria-pressed={selectedId === node.node_id} onClick={() => onSelect(node.node_id)}>
              <span className="lineage-node-type"><Icon size={14} />{({ claim_revision: "Statement", revision: "Statement", version: "Source version", clause: "Passage", message: "Slack message", remote_reference: "Remote reference" } as Record<string, string>)[node.node_type] || humanize(node.node_type)}{node.node_id === graph.root_id && <span className="lineage-root">Start</span>}</span>
              <strong>{lineageNodeTitle(node)}</strong>
              {node.node_type === "finding" && <span className="lineage-finding-tag">#{node.node_id.slice(-8).toUpperCase()}</span>}
              {node.attributes.source_identity && !["source", "version", "document"].includes(node.node_type) && <span className="lineage-locator">{sourceTitle({ source_identity: node.attributes.source_identity })}</span>}
              {node.attributes.version_label && <span className="source-version">{node.attributes.version_label}</span>}
              {node.attributes.quote && node.node_type !== "answer" && <span className="lineage-excerpt">{node.attributes.quote}</span>}
              {node.attributes.page && <span className="lineage-locator">Page {node.attributes.page}{node.attributes.section ? ` · § ${node.attributes.section}` : ""}</span>}
            </button></li>;
          })}</ul>
          {!nodes.length && <p className="lineage-lane-empty">{search ? "No matches in this group. Try another group or clear the search." : "No records in this group."}</p>}
          {nodes.length > limit && <button className="button secondary lineage-show-more" onClick={() => setLimit(value => value + 8)}>Show {Math.min(8, nodes.length - limit)} more<span className="muted">{limit} of {nodes.length}</span></button>}
        </section>
      </div>
      <section className="lineage-inspector" ref={inspector} tabIndex={-1} aria-labelledby="lineage-inspector-title">
        <button className="text-button lineage-back" onClick={onBack}><ArrowLeft size={16} />Back to evidence</button>
        {selected ? <>
          <div className="lineage-inspector-heading"><div><span className="eyebrow">{humanize(selected.node_type)}</span><h3 id="lineage-inspector-title">{lineageNodeTitle(selected)}</h3>{selected.attributes.version_label && <span className="source-version">{selected.attributes.version_label}</span>}</div><span className="integrity-unchecked"><CircleDot size={13} />Recorded evidence</span></div>
          {search && !visible.some(node => node.node_id === selectedId) && <p className="verification-help">This selected record is outside the current search results.</p>}
          {selected.attributes.quote && <blockquote>{selected.attributes.quote}</blockquote>}
          <div className="lineage-inspector-actions">
            {!supplied && sourceId && <><button className="button secondary" onClick={() => onInspect(selected)}><FileText size={15} />Inspect source</button><button className="text-button" onClick={() => onCheckSource(sourceId)}>Check source copy<ArrowRight size={14} /></button></>}
            {!supplied && selected.node_type === "finding" && <button className="text-button" onClick={() => onFinding(selected.node_id.slice("finding:".length))}>Open finding<ArrowRight size={14} /></button>}
          </div>
          <div className="lineage-relations"><h4>Connected evidence <span>{related.length}</span></h4>{related.length ? <ul>{related.slice(0, relationLimit).map(edge => {
            const from = graph.nodes.find(node => node.node_id === edge.from_node_id); const to = graph.nodes.find(node => node.node_id === edge.to_node_id);
            if (!from || !to) return null;
            const other = from.node_id === selectedId ? to : from;
            return <li key={edge.edge_id}><span><ArrowDown size={12} />{from.node_id === selectedId ? relationLabels[edge.edge_type] || humanize(edge.edge_type) : `Referenced by · ${relationLabels[edge.edge_type] || humanize(edge.edge_type)}`}</span>{recordLink(other)}</li>;
          })}</ul> : <p>No direct connections were returned for this record.</p>}{related.length > relationLimit && <button className="button secondary lineage-show-more" onClick={() => setRelationLimit(value => value + 3)}>Show more connections<span>{relationLimit} of {related.length}</span></button>}</div>
          <details className="lineage-technical"><summary>Record details</summary><dl><dt>Node</dt><dd>{selected.node_id}</dd>{Object.entries(selected.attributes).filter(([key]) => !["quote", "source_identity", "version_label"].includes(key)).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value || "Not recorded"}</dd></div>)}</dl></details>
        </> : <div className="lineage-unavailable"><Network size={22} /><h3 id="lineage-inspector-title">Record outside this view</h3><p>Return to the start or show related evidence to look for the linked record.</p><button className="button secondary" onClick={() => onSelect(graph.root_id)}>Return to the start</button></div>}
      </section>
    </div>
  </>;
}
