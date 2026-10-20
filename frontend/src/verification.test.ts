import { test } from "node:test";
import assert from "node:assert/strict";
import { bundleLineage, checkCounts, evidenceFileError, parseEvidenceBundle } from "./verification.ts";
import { readView, viewSearch } from "./viewState.ts";

test("verification URLs retain target, selected node, filters and original-source location", () => {
  const view = { ...readView(""), office: "frankfurt" as const, verifyKind: "finding" as const,
    verifyId: "find_a", verifyPassage: "revision:r#1", verifyNode: "revision:r#1", verifySearch: "policy & procedures", verifyChecks: "failed" as const,
    document: "src_1", page: 4, zoom: 125 };
  assert.deepEqual(readView(viewSearch(view)), view);
  const invalid = readView("?verify=admin&checks=verified");
  assert.equal(invalid.verifyKind, "source"); assert.equal(invalid.verifyChecks, "all");
});

test("a not-checked result remains separate from passed checks", () => {
  assert.deepEqual(checkCounts({ target_type: "bundle", target_id: "b", checks: [
    { check: "signature", status: "passed", detail: {} }, { check: "text", status: "not_checked", detail: {} },
    { check: "binding", status: "failed", detail: {} },
  ] }), { passed: 1, failed: 1, not_checked: 1 });
  assert.ok(evidenceFileError({ size: 0 })); assert.ok(evidenceFileError({ size: 20 * 1024 * 1024 + 1 }));
  assert.equal(evidenceFileError({ size: 20 * 1024 * 1024 }), "");
});

test("imported lineage connects only explicit citations and keeps remote evidence opaque", () => {
  const bundle = { bundle_id: "b", answer: { answer_id: "a", answer_text: "<script>unsafe()</script>", citations: [
    { claim_revision_id: "cited", remote: false }, { claim_revision_id: "remote", remote: true },
  ] }, manifests: [{ source_id: "s", source_identity: "Policy", version_label: "v1" }],
  claims: ["cited", "extra"].map(revision_id => ({ claim: { revision_id, source_id: "s", evidence: { clause_id: revision_id, quote: "Exact text", page: 1 } } })) };
  for (const parsed of [parseEvidenceBundle(JSON.stringify(bundle)), parseEvidenceBundle(JSON.stringify({ bundle }))]) {
    const graph = bundleLineage(parsed);
    assert.equal(graph.nodes.find(n => n.node_id === "answer:a")?.attributes.quote, "<script>unsafe()</script>");
    assert.deepEqual(graph.edges.filter(e => e.edge_type === "CITES").map(e => e.to_node_id).sort(), ["revision:cited", "revision:remote"]);
    const remote = graph.nodes.find(n => n.node_id === "revision:remote")!;
    assert.equal(remote.node_type, "remote_reference"); assert.equal(remote.attributes.quote, undefined);
    assert.ok(!graph.edges.some(e => e.to_node_id === "revision:extra" && e.edge_type === "CITES"));
  }
  for (const raw of ["invalid", "null", "[]", '{"target_id":"b","checks":[]}']) assert.throws(() => parseEvidenceBundle(raw));
});

test("large supplied traces are bounded without changing the evidence sent for verification", () => {
  const bundle = { bundle_id: "b", answer: { answer_id: "a", citations: [] }, manifests: [{ source_id: "s" }],
    claims: Array.from({ length: 500 }, (_, i) => ({ claim: { revision_id: `r${i}`, source_id: "s", evidence: { clause_id: `c${i}`, quote: "Source text" } } })) };
  const before = JSON.stringify(bundle);
  const graph = bundleLineage(bundle);
  assert.equal(graph.truncated, true);
  assert.ok(graph.nodes.length <= 400); assert.ok(graph.edges.length <= 1200);
  const ids = new Set(graph.nodes.map(node => node.node_id));
  assert.ok(graph.edges.every(edge => ids.has(edge.from_node_id) && ids.has(edge.to_node_id)));
  assert.equal(JSON.stringify(bundle), before);
});
