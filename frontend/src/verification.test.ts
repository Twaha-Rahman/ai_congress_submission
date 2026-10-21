import { test } from "node:test";
import assert from "node:assert/strict";
import { bundleLineage, checkCounts, checkSummary, focusedLineage, lineageNodes, lineageNodeTitle, sourceFamily, lineageSourceCounts, lineageMatchContext, evidenceFileError, parseEvidenceBundle } from "./verification.ts";
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

test("task, trace scope, mobile pane and evidence group survive sharing", () => {
  const view = { ...readView("?verify=finding"), verifyTab: "check" as const,
    verifyScope: "related" as const, verifyPane: "detail" as const, verifyGroup: "Statements" };
  assert.deepEqual(readView(viewSearch(view)), view);
  assert.equal(readView("?verify=finding").verifyTab, "trace");
  const invalid = readView("?task=unknown&scope=all&tracePane=bad&group=unknown");
  assert.equal(invalid.verifyTab, "check"); assert.equal(invalid.verifyScope, "focused");
  assert.equal(invalid.verifyPane, "browse"); assert.equal(invalid.verifyGroup, "");
});

test("a focused finding follows its dependencies without pulling in sibling findings or versions", () => {
  const nodes = [ ["f1", "finding"], ["f2", "finding"], ["r1", "claim_revision"], ["r2", "claim_revision"],
    ["c1", "clause"], ["c2", "clause"], ["s1", "version"], ["s2", "version"], ["doc", "document"] ]
    .map(([node_id, node_type]) => ({ node_id, node_type, label: node_id, attributes: {}, restricted: false }));
  const edges = [ ["f1", "r1", "FINDS_BETWEEN"], ["f2", "r1", "FINDS_BETWEEN"], ["f2", "r2", "FINDS_BETWEEN"],
    ["r1", "c1", "EXTRACTED_FROM"], ["r1", "s1", "IN_VERSION"], ["c1", "s1", "IN_VERSION"],
    ["r2", "c2", "EXTRACTED_FROM"], ["r2", "s2", "IN_VERSION"], ["c2", "s2", "IN_VERSION"],
    ["s1", "doc", "IN_VERSION"], ["s2", "doc", "IN_VERSION"], ["s2", "s1", "SUPERSEDES"] ]
    .map(([from_node_id, to_node_id, edge_type], i) => ({ edge_id: String(i), edge_type, from_node_id, to_node_id, attributes: {} }));
  const graph = { root_id: "f1", nodes, edges, truncated: false };
  const before = JSON.stringify(graph);
  assert.deepEqual(focusedLineage(graph).nodes.map(node => node.node_id), ["f1", "r1", "c1", "s1", "doc"]);
  assert.deepEqual(focusedLineage({ ...graph, root_id: "s1" }).nodes.map(node => node.node_id), ["r1", "c1", "s1", "doc"]);
  assert.equal(JSON.stringify(graph), before);
  assert.deepEqual(lineageNodes(focusedLineage(graph), "r2"), []);
});

test("result summaries distinguish byte mismatch, missing checks, undisclosed proofs, and successful checks", () => {
  const source = { target_type: "source", target_id: "s", checks: ["source_file_hash", "content_normalized_text", "clause_text_match", "merkle_root_match"]
    .map(check => ({ check, status: "passed" as const, detail: {} })) };
  assert.equal(checkSummary(source).tone, "passed");
  const mismatch = { ...source, checks: source.checks.map((check, i) => ({ ...check, status: i === 0 ? "failed" as const : "passed" as const })) };
  assert.equal(checkSummary(mismatch).title, "File bytes differ; extracted text and passages match.");
  assert.equal(checkSummary({ ...source, checks: source.checks.slice(1) }).tone, "not_checked");
  assert.equal(checkSummary({ ...source, checks: [] }).title, "No integrity checks were returned.");
  const partial = { target_type: "bundle", target_id: "b", checks: [{ check: "clause_inclusion", status: "passed" as const, detail: { skipped_not_disclosed: "1" } }] };
  assert.equal(checkSummary(partial).tone, "not_checked");
  assert.equal(checkSummary({ ...partial, checks: [{ check: "signature", status: "not_checked", detail: {} }] }).title, "No checks passed; verification is incomplete.");
  assert.equal(checkSummary({ ...mismatch, checks: mismatch.checks.map(check => ({ ...check, status: "failed" })) }).tone, "failed");
});

test("evidence labels use literal excerpts and clear locators without modifying evidence", () => {
  const quote = 'Employees must never send customer data to personal email accounts.';
  const node = { node_id: 'revision:r', node_type: 'claim_revision', label: 'general_policy:statement', attributes: { quote, source_identity: 'security_policy', version_label: 'v1' }, restricted: false };
  assert.equal(lineageNodeTitle(node), quote);
  assert.equal(node.attributes.quote, quote);
  assert.equal(lineageNodeTitle({ ...node, node_type: 'clause', attributes: { section: '3.1', page: '2' } }), 'Section 3.1');
  assert.equal(lineageNodeTitle({ ...node, node_type: 'clause', attributes: { page: '2' } }), 'Passage on page 2');
  assert.equal(lineageNodeTitle({ ...node, node_type: 'answer', attributes: { question: 'What policy applies?' } }), 'What policy applies?');
  const version = { ...node, node_type: 'version', node_id: 'source:s' };
  assert.equal(sourceFamily(version), sourceFamily({ ...node, node_type: 'document', node_id: 'document:security_policy' }));
  const graph = { root_id: node.node_id, nodes: [version, node], edges: [], truncated: false };
  assert.equal(lineageNodes(graph, 'email accounts')[0].node_id, node.node_id);
  const view = { ...readView(''), verifyAnswerSearch: 'policy & date' };
  assert.deepEqual(readView(viewSearch(view)), view);
});

test("source counts distinguish documents from their uploaded versions", () => {
  const make = (id: string, type: string, identity: string) => ({ node_id: id, node_type: type, label: identity, attributes: { source_identity: identity }, restricted: false });
  const document = make('document:handbook', 'document', 'handbook');
  const v1 = make('source:one', 'version', 'handbook');
  assert.deepEqual(lineageSourceCounts([document, v1]), { documents: 1, versions: 1 });
  assert.deepEqual(lineageSourceCounts([document, v1, make('source:two', 'version', 'handbook')]), { documents: 1, versions: 2 });
  assert.deepEqual(lineageSourceCounts([v1, make('source:other', 'version', 'other')]), { documents: 2, versions: 2 });
});

test("lineage search uses visible source names and exposes matches beyond shortened titles", () => {
  const node = { node_id: 'revision:claim_abcdef12', node_type: 'claim_revision', label: 'Policy statement',
    attributes: { quote: 'A'.repeat(130) + ' HR system records leave.', source_identity: 'employee_handbook', version_label: 'v1' }, restricted: false };
  const graph = { root_id: node.node_id, nodes: [node], edges: [], truncated: false };
  assert.equal(lineageNodes(graph, 'employee handbook').length, 1);
  assert.equal(lineageNodes(graph, 'HR').length, 1);
  assert.match(lineageMatchContext(node, 'hr')!.text, /HR system/);
  const finding = { ...node, node_id: 'finding:find_abcdef12', node_type: 'finding' };
  assert.equal(lineageNodes({ ...graph, nodes: [finding] }, '#ABCDEF12').length, 1);
  assert.equal(lineageMatchContext(finding, '#ABCDEF12'), null);
});
