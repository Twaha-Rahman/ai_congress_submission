import type { CheckStatus, LineageGraph, LineageNode, VerificationReport } from "./types";
import { sourceTitle } from "./presentation";
import { searchRanges, matchingExcerpt } from "./searchHighlight";

export const MAX_EVIDENCE_BYTES = 20 * 1024 * 1024;
export const checkLabels: Record<string, string> = {
  source_file_hash: "Original file hash", content_normalized_text: "Document text",
  clause_text_match: "Passage text", merkle_root_match: "Passage commitment tree",
  bundle_binding: "Bundle identity", answer_text_hash: "Answer text hash",
  answer_signature: "Answer signature", claim_signature: "Statement signatures",
  manifest_signature: "Source manifest signatures", manifest_binding: "Source manifest binding",
  clause_inclusion: "Passage inclusion proofs", claim_binding: "Statement evidence binding",
  answer_binding: "Answer citation binding", tenant_match: "Workspace identity",
};
export const checkStatusLabels: Record<CheckStatus, string> = { passed: "Passed", failed: "Failed", not_checked: "Not checked" };
export function checkCounts(report: VerificationReport) {
  return report.checks.reduce((counts, check) => { counts[check.status]++; return counts; }, { passed: 0, failed: 0, not_checked: 0 });
}
/** Summaries describe only returned checks; they never certify policy correctness. */
export function checkSummary(report: VerificationReport) {
  const counts = checkCounts(report);
  const status = (name: string) => report.checks.find(check => check.check === name)?.status;
  if (report.target_type === "source" && status("source_file_hash") === "failed" &&
      ["content_normalized_text", "clause_text_match", "merkle_root_match"].every(name => status(name) === "passed"))
    return { tone: "failed", title: "File bytes differ; extracted text and passages match.",
      next: "Confirm that you selected the intended copy. Use the stored original if you need an exact file match; matching text alone does not establish file identity." };
  if (counts.failed) return { tone: "failed", title: `${counts.failed === 1 ? "One integrity check failed" : `${counts.failed} integrity checks failed`}${counts.not_checked ? "; some checks could not run" : ""}.`,
    next: "Review the failed checks below. Confirm the intended file or bundle and obtain the original export before relying on its integrity." };
  const undisclosed = report.checks.some(check => Number(check.detail?.skipped_not_disclosed || check.detail?.not_supplied || 0) > 0);
  const missingSourceChecks = report.target_type === "source" && ["source_file_hash", "content_normalized_text", "clause_text_match", "merkle_root_match"].some(name => !status(name));
  if (counts.not_checked || undisclosed || (counts.passed > 0 && missingSourceChecks)) return { tone: "not_checked", title: counts.passed ? "The completed checks passed; verification is incomplete." : "No checks passed; verification is incomplete.",
    next: "Review the unchecked, missing or undisclosed evidence below. Obtain the missing evidence or keys and run the checks again." };
  if (!counts.passed) return { tone: "not_checked", title: "No integrity checks were returned.", next: "Run verification again or inspect the exported report before relying on this result." };
  return { tone: "passed", title: report.target_type === "source" ? "The copy matches the stored source in all returned checks." : "All returned integrity checks passed.",
    next: report.target_type === "source" ? "File, text and passage results are listed below. These checks do not verify manifest or finding signatures." : "Review the individual checks for their scope. This result does not establish that the answer or policy interpretation is correct." };
}

/** Follow evidence dependencies, without walking back into unrelated conclusions. */
export function focusedLineage(graph: LineageGraph): LineageGraph {
  const ids = new Set([graph.root_id]);
  const root = graph.nodes.find(node => node.node_id === graph.root_id);
  const dependencyTypes = new Set(["CITES", "FINDS_BETWEEN", "EXTRACTED_FROM", "IN_VERSION"]);
  // A source starts from its own statements/passages, not every finding in the
  // connected component or other versions reached through a document identity.
  if (root && ["source", "version", "document"].includes(root.node_type)) {
    for (const edge of graph.edges) {
      if (edge.to_node_id === root.node_id && edge.edge_type === "IN_VERSION") ids.add(edge.from_node_id);
    }
    if (root.node_type === "document") {
      for (const edge of graph.edges) {
        if (ids.has(edge.to_node_id) && edge.edge_type === "IN_VERSION") ids.add(edge.from_node_id);
      }
    }
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of graph.edges) {
      if (dependencyTypes.has(edge.edge_type) && ids.has(edge.from_node_id) && !ids.has(edge.to_node_id)) {
        ids.add(edge.to_node_id); changed = true;
      }
    }
  }
  return { ...graph, nodes: graph.nodes.filter(node => ids.has(node.node_id)),
    edges: graph.edges.filter(edge => ids.has(edge.from_node_id) && ids.has(edge.to_node_id)) };
}
export function lineageNodes(graph: LineageGraph, search: string) {
  const query = search.trim().toLowerCase();
  return lineageGroups.flatMap(group => {
    const nodes = graph.nodes.filter(node => group.types.includes(node.node_type));
    return group.label === "Sources" ? nodes.sort((a, b) => sourceFamily(a).localeCompare(sourceFamily(b)) ||
      Number(b.node_type === "document") - Number(a.node_type === "document") ||
      (a.attributes.version_label || "").localeCompare(b.attributes.version_label || "", undefined, { numeric: true })) : nodes;
  })
    .filter(node => !query || lineageSearchEntries(node).some(entry => searchRanges(entry.text, search, entry.identifier).length));
}
export function lineageSourceCounts(nodes: LineageNode[]) {
  const sources = nodes.filter(node => ["document", "source", "version"].includes(node.node_type));
  return { documents: new Set(sources.map(sourceFamily)).size, versions: sources.filter(node => node.node_type !== "document").length };
}
function lineageSearchEntries(node: LineageNode) {
  const entries = [{ label: "Title", text: lineageNodeTitle(node), identifier: false },
    { label: "Record ID", text: node.node_id, identifier: true }];
  if (node.node_type === "finding") entries.push({ label: "Finding tag", text: `#${node.node_id.slice(-8).toUpperCase()}`, identifier: true });
  if (node.attributes.source_identity) entries.push({ label: "Source", text: sourceTitle({ source_identity: node.attributes.source_identity }), identifier: false });
  for (const [key, value] of Object.entries(node.attributes)) entries.push({ label: key === "quote" ? "Passage" : key.replace(/_/g, " "), text: value, identifier: key.endsWith("_id") });
  return entries;
}
/** Explain matches beyond the truncated title without highlighting the inspector. */
export function lineageMatchContext(node: LineageNode, query: string) {
  const visible = [lineageNodeTitle(node), node.attributes.version_label || "",
    node.attributes.source_identity ? sourceTitle({ source_identity: node.attributes.source_identity }) : "",
    `Page ${node.attributes.page || ""}${node.attributes.section ? ` · § ${node.attributes.section}` : ""}`];
  if (visible.some(text => searchRanges(text, query).length) ||
      (node.node_type === "finding" && searchRanges(`#${node.node_id.slice(-8).toUpperCase()}`, query, true).length)) return null;
  // Passages already render a match-centered excerpt in their card.
  if (["clause", "message"].includes(node.node_type) && searchRanges(node.attributes.quote || "", query).length) return null;
  const entry = lineageSearchEntries(node).find(entry => searchRanges(entry.text, query, entry.identifier).length);
  return entry ? { ...entry, text: entry.identifier ? entry.text : matchingExcerpt(entry.text, query) } : null;
}
export function sourceFamily(node: LineageNode) {
  return node.node_type === "document" ? node.node_id.replace(/^document:/, "") : node.attributes.source_identity || node.node_id;
}
export function evidenceFileError(file: Pick<File, "size">) {
  if (!file.size) return "Choose a nonempty evidence file.";
  if (file.size > MAX_EVIDENCE_BYTES) return "Choose evidence up to 20 MB.";
  return "";
}
export function jsonObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
const text = (value: unknown) => typeof value === "string" ? value : "";
const array = (value: unknown) => Array.isArray(value) ? value : [];
export function parseEvidenceBundle(raw: string): Record<string, unknown> {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error("This file is not valid JSON. Choose an exported evidence bundle."); }
  const object = jsonObject(value);
  const bundle = "bundle" in object ? jsonObject(object.bundle) : object;
  if (!text(bundle.bundle_id) || !text(jsonObject(bundle.answer).answer_id))
    throw new Error("This JSON is not an answer evidence bundle. Choose the bundle export, rather than a verification report.");
  return bundle;
}
/** Supplied topology is a browsing aid, never a cryptographic verification result. */
export function bundleLineage(bundle: Record<string, unknown>): LineageGraph {
  const answer = jsonObject(bundle.answer);
  const root = `answer:${text(answer.answer_id)}`;
  const nodes = new Map<string, LineageNode>();
  const edges = new Map<string, LineageGraph["edges"][number]>();
  let truncated = false;
  const add = (id: string, type: string, label: string, attributes: Record<string, string> = {}) => {
    if (nodes.size >= 400 && !nodes.has(id)) { truncated = true; return; }
    nodes.set(id, { node_id: id, node_type: type, label, attributes, restricted: false });
  };
  const link = (from: string, to: string, type: string) => {
    const id = `${type}:${from}:${to}`;
    if (edges.size >= 1200 && !edges.has(id)) { truncated = true; return; }
    edges.set(id, { edge_id: id, edge_type: type, from_node_id: from, to_node_id: to, attributes: {} });
  };
  add(root, "answer", text(answer.question) || "Supplied answer", { quote: text(answer.answer_text), valid_at: text(answer.valid_at), known_at: text(answer.known_at) });
  for (const value of array(bundle.manifests)) {
    const manifest = jsonObject(value); const id = text(manifest.source_id); if (!id) continue;
    add(`source:${id}`, "version", text(manifest.source_identity), { source_id: id, source_identity: text(manifest.source_identity), version_label: text(manifest.version_label), region: text(manifest.region) });
  }
  for (const value of array(bundle.claims)) {
    const claim = jsonObject(jsonObject(value).claim); const id = text(claim.revision_id); if (!id) continue;
    const evidence = jsonObject(claim.evidence); const sourceId = text(claim.source_id);
    const revision = `revision:${id}`; const clause = `clause:${text(evidence.clause_id)}`;
    const attrs = { quote: text(evidence.quote), source_id: sourceId, source_identity: text(claim.source_identity), version_label: text(claim.source_version_label), page: String(evidence.page ?? ""), section: text(evidence.section), authority: text(claim.authority), extraction_mode: text(jsonObject(claim.extraction).mode) };
    add(revision, "claim_revision", "Policy statement", attrs);
    add(clause, "clause", text(evidence.section) || "Cited passage", attrs);
    link(revision, clause, "EXTRACTED_FROM");
    if (nodes.has(`source:${sourceId}`)) link(clause, `source:${sourceId}`, "IN_VERSION");
  }
  // Only recorded citations connect to the answer. Additional supplied claims
  // are not silently promoted to citations.
  for (const value of array(answer.citations)) {
    const citation = jsonObject(value); const id = text(citation.claim_revision_id);
    if (!id && text(citation.clause_id)) {
      const clause = `clause:${text(citation.clause_id)}`;
      const source = `source:${text(citation.source_id)}`;
      add(clause, "clause", "Cited passage", { quote: text(citation.quote), source_id: text(citation.source_id),
        source_identity: text(citation.source_identity), version_label: text(citation.source_version_label),
        page: String(citation.page ?? ""), section: text(citation.section), authority: text(citation.authority) });
      link(root, clause, "CITES");
      if (nodes.has(source)) link(clause, source, "IN_VERSION");
      continue;
    }
    if (!id) continue;
    const revision = `revision:${id}`;
    if (!nodes.has(revision) && citation.remote === true)
      add(revision, "remote_reference", "Undisclosed remote statement", { reference: id, disclosure: "Source passage not supplied" });
    if (nodes.has(revision)) link(root, revision, "CITES");
  }
  return { root_id: root, nodes: [...nodes.values()], edges: [...edges.values()].filter(edge => nodes.has(edge.from_node_id) && nodes.has(edge.to_node_id)), truncated };
}
export const lineageGroups = [
  { label: "Conclusions", types: ["answer", "finding"] },
  { label: "Statements", types: ["claim_revision", "revision", "remote_reference"] },
  { label: "Passages", types: ["clause", "message"] },
  { label: "Sources", types: ["version", "source", "document"] },
];
export function lineageNodeTitle(node: LineageNode) {
  const excerpt = node.attributes.quote?.trim().replace(/\s+/g, " ");
  if (["clause", "message"].includes(node.node_type)) return node.attributes.section ? `Section ${node.attributes.section}` :
    node.attributes.page ? `Passage on page ${node.attributes.page}` : node.node_type === "message" ? "Saved message" : "Cited passage";
  if (node.attributes.source_identity && ["version", "source"].includes(node.node_type)) return sourceTitle({ source_identity: node.attributes.source_identity });
  if (node.node_type === "document") return sourceTitle({ source_identity: node.node_id.replace(/^document:/, "") });
  if (node.node_type === "answer") return node.attributes.question || (/^(answered|abstained|partial|needs_review) answer$/.test(node.label) ? "Recorded answer" : node.label);
  if (["claim_revision", "revision"].includes(node.node_type)) return excerpt ? excerpt.length > 110 ? `${excerpt.slice(0, 110).trimEnd()}…` : excerpt : node.label.startsWith("general_policy:") ? "Policy statement" : node.label.replace(/^(loan_approval|record_retention):\s*/, "");
  return node.label.replace(/_/g, " ");
}
export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
