import {
  findingTag,
  sortOptions,
  typeLabels,
  type FindingSort,
} from "./presentation";
import type { Finding, Office } from "./types";

export type DetailTab = "evidence" | "timeline" | "reviews";
export interface View {
  office: Office;
  finding: string;
  tag: string;
  search: string;
  state: string;
  type: string;
  severity: string;
  sort: FindingSort;
  tab: DetailTab;
  pane: "queue" | "detail";
  autoRefresh: boolean;
  source: string;
  sourceMode: "details" | "original";
  page: number;
  zoom: number;
  sourceSearch: string;
  sourceType: "all" | "pdf" | "slack";
  sourceSort: "newest" | "name";
  document: string;
  uploadJob: string;
  forSource: string;
  verifyKind: "source" | "finding" | "answer" | "bundle";
  verifyTab: "check" | "trace";
  verifyScope: "focused" | "related";
  verifyPane: "browse" | "detail";
  verifyGroup: string;
  verifyAnswerSearch: string;
  verifyId: string;
  verifyNode: string;
  verifyPassage: string;
  verifySearch: string;
  verifyChecks: "all" | "passed" | "failed" | "not_checked";
  compareMode: "general" | "rules";
  comparePane: "setup" | "results";
  compareDhaka: string;
  compareFrankfurt: string;
  compareRequest: string;
  compareSourceOffice: Office;
  compareCitation: string;
  questionId: string;
  questionSearch: string;
  questionPane: "compose" | "answer";
  questionCitation: string;
  questionPanel: "ask" | "recent";
}

export function readView(search: string): View {
  const p = new URLSearchParams(search);
  const allowed = (key: string, values: string[], fallback = "all") =>
    values.includes(p.get(key) || "") ? p.get(key)! : fallback;
  const finding = p.get("finding") || "";
  const tag = (p.get("tag") || "").replace(/^#/, "").trim().toUpperCase();
  const page = Number(p.get("page") || 1);
  return {
    office: p.get("office") === "frankfurt" ? "frankfurt" : "dhaka",
    finding,
    tag,
    search: p.get("q") || "",
    state: allowed("state", ["open", "acknowledged", "resolved", "dismissed"]),
    type: allowed("type", Object.keys(typeLabels)),
    severity: allowed("severity", ["high", "review", "info"]),
    sort: allowed(
      "sort",
      sortOptions.map((option) => option.value),
      "severity",
    ) as FindingSort,
    tab: allowed(
      "tab",
      ["evidence", "timeline", "reviews"],
      "evidence",
    ) as DetailTab,
    pane: allowed(
      "pane",
      ["queue", "detail"],
      finding || tag ? "detail" : "queue",
    ) as View["pane"],
    autoRefresh: p.get("auto") === "1",
    source: p.get("source") || "",
    sourceMode: p.get("sourceMode") === "original" ? "original" : "details",
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    zoom: Math.min(200, Math.max(50, Number(p.get("zoom")) || 100)),
    sourceSearch: p.get("sq") || "",
    sourceType: allowed("sourceType", ["pdf", "slack"]) as View["sourceType"],
    sourceSort: allowed("sourceSort", ["newest", "name"], "newest") as View["sourceSort"],
    document: p.get("document") || "",
    uploadJob: p.get("job") || "",
    forSource: p.get("forSource") || "",
    verifyKind: allowed("verify", ["source", "finding", "answer", "bundle"], "source") as View["verifyKind"],
    verifyTab: allowed("task", ["check", "trace"], p.get("verify") === "finding" ? "trace" : "check") as View["verifyTab"],
    verifyScope: p.get("scope") === "related" ? "related" : "focused",
    verifyPane: p.get("tracePane") === "detail" ? "detail" : "browse",
    verifyGroup: allowed("group", ["Conclusions", "Statements", "Passages", "Sources"], ""),
    verifyAnswerSearch: p.get("aq") || "",
    verifyId: p.get("target") || "",
    verifyNode: p.get("node") || "",
    verifyPassage: p.get("passage") || "",
    verifySearch: p.get("vq") || "",
    verifyChecks: allowed("checks", ["passed", "failed", "not_checked"]) as View["verifyChecks"],
    compareMode: p.get("compareMode") === "rules" ? "rules" : "general",
    comparePane: allowed("comparePane", ["setup", "results"], p.get("dhaAnswer") || p.get("fraAnswer") || p.get("comparison") ? "results" : "setup") as View["comparePane"],
    compareDhaka: p.get("dhaAnswer") || "",
    compareFrankfurt: p.get("fraAnswer") || "",
    compareRequest: p.get("comparison") || "",
    compareSourceOffice: p.get("evidenceOffice") === "frankfurt" ? "frankfurt" : "dhaka",
    compareCitation: p.get("evidenceCitation") || "",
    questionId: p.get("answer") || "",
    questionSearch: p.get("qq") || "",
    questionPane: allowed("questionPane", ["compose", "answer"], p.get("answer") ? "answer" : "compose") as View["questionPane"],
    questionCitation: p.get("citation") || "",
    questionPanel: allowed("questionPanel", ["ask", "recent"], p.get("answer") ? "recent" : "ask") as View["questionPanel"],
  };
}

export function viewSearch(view: View) {
  const p = new URLSearchParams({
    office: view.office,
    state: view.state,
    type: view.type,
    severity: view.severity,
    sort: view.sort,
    tab: view.tab,
    pane: view.pane,
    auto: view.autoRefresh ? "1" : "0",
  });
  if (view.finding) p.set("finding", view.finding);
  if (view.tag) p.set("tag", view.tag);
  if (view.search) p.set("q", view.search);
  if (view.sourceSearch) p.set("sq", view.sourceSearch);
  if (view.sourceType !== "all") p.set("sourceType", view.sourceType);
  if (view.sourceSort !== "newest") p.set("sourceSort", view.sourceSort);
  if (view.document) {
    p.set("document", view.document);
    p.set("page", String(view.page));
    p.set("zoom", String(view.zoom));
  }
  if (view.uploadJob) p.set("job", view.uploadJob);
  if (view.forSource) p.set("forSource", view.forSource);
  if (view.verifyKind !== "source") p.set("verify", view.verifyKind);
  p.set("task", view.verifyTab);
  if (view.verifyScope !== "focused") p.set("scope", view.verifyScope);
  if (view.verifyPane !== "browse") p.set("tracePane", view.verifyPane);
  if (view.verifyGroup) p.set("group", view.verifyGroup);
  if (view.verifyAnswerSearch) p.set("aq", view.verifyAnswerSearch);
  if (view.verifyId) p.set("target", view.verifyId);
  if (view.verifyNode) p.set("node", view.verifyNode);
  if (view.verifyPassage) p.set("passage", view.verifyPassage);
  if (view.verifySearch) p.set("vq", view.verifySearch);
  if (view.verifyChecks !== "all") p.set("checks", view.verifyChecks);
  p.set("compareMode", view.compareMode);
  p.set("comparePane", view.comparePane);
  if (view.compareDhaka) p.set("dhaAnswer", view.compareDhaka);
  if (view.compareFrankfurt) p.set("fraAnswer", view.compareFrankfurt);
  if (view.compareRequest) p.set("comparison", view.compareRequest);
  if (view.compareCitation !== "") p.set("evidenceCitation", view.compareCitation);
  if (view.document) p.set("evidenceOffice", view.compareSourceOffice);
  if (view.questionId) p.set("answer", view.questionId);
  if (view.questionSearch) p.set("qq", view.questionSearch);
  p.set("questionPane", view.questionPane);
  p.set("questionPanel", view.questionPanel);
  if (view.questionCitation) p.set("citation", view.questionCitation);
  if (view.source) {
    p.set("source", view.source);
    p.set("sourceMode", view.sourceMode);
    p.set("page", String(view.page));
    p.set("zoom", String(view.zoom));
  }
  return `?${p}`;
}

export function selectedFinding(
  view: View,
  all: Finding[],
  visible: Finding[],
) {
  if (view.finding)
    return { id: view.finding, ambiguous: false, missingTag: false };
  if (view.tag) {
    const matches = all.filter((f) => findingTag(f).slice(1) === view.tag);
    return {
      id: matches.length === 1 ? matches[0].finding_id : "",
      ambiguous: matches.length > 1,
      missingTag: matches.length === 0,
    };
  }
  return {
    id: visible[0]?.finding_id || "",
    ambiguous: false,
    missingTag: false,
  };
}

export function pinSelection(view: View, finding?: Finding) {
  return finding
    ? {
        ...view,
        finding: finding.finding_id,
        tag: findingTag(finding).slice(1),
      }
    : view;
}
