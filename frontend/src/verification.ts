import type { CheckStatus, LineageGraph, LineageNode, VerificationReport } from "./types";
import { sourceTitle } from "./presentation";

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
  const edges: LineageGraph["edges"] = [];
  const add = (id: string, type: string, label: string, attributes: Record<string, string> = {}) => nodes.set(id, { node_id: id, node_type: type, label, attributes, restricted: false });
  const link = (from: string, to: string, type: string) => edges.push({ edge_id: `${type}:${from}:${to}`, edge_type: type, from_node_id: from, to_node_id: to, attributes: {} });
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
    const citation = jsonObject(value); const id = text(citation.claim_revision_id); if (!id) continue;
    const revision = `revision:${id}`;
    if (!nodes.has(revision) && citation.remote === true)
      add(revision, "remote_reference", "Undisclosed remote statement", { reference: id, disclosure: "Source passage not supplied" });
    if (nodes.has(revision)) link(root, revision, "CITES");
  }
  return { root_id: root, nodes: [...nodes.values()], edges, truncated: false };
}
export const lineageGroups = [
  { label: "Conclusions", types: ["answer", "finding"] },
  { label: "Statements", types: ["claim_revision", "revision", "remote_reference"] },
  { label: "Passages", types: ["clause", "message"] },
  { label: "Sources", types: ["version", "source", "document"] },
];
export function lineageNodeTitle(node: LineageNode) {
  if (node.node_type === "clause" && /^message \d+$/.test(node.label)) return `Page ${node.attributes.page || "unknown"} passage`;
  if (node.attributes.source_identity && ["version", "source"].includes(node.node_type)) return sourceTitle({ source_identity: node.attributes.source_identity });
  if (node.node_type === "document") return sourceTitle({ source_identity: node.node_id.replace(/^document:/, "") });
  if (node.node_type === "answer" && /^(answered|abstained|partial|needs_review) answer$/.test(node.label)) return "Recorded answer";
  if (["claim_revision", "revision"].includes(node.node_type)) return node.label.startsWith("general_policy:") ? "Policy statement" : node.label.replace(/^(loan_approval|record_retention):\s*/, "");
  return node.label.replace(/_/g, " ");
}
export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
