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
