import { matchesFinding, orderFindings, type FindingSort } from "./presentation";
import type { Finding } from "./types";

export const unreviewedFindings = (findings: Finding[]) => findings.filter(finding => finding.review_state === "open");

export function reviewQueue(findings: Finding[], filters: { search:string; type:string; severity:string; forSource:string; sort:FindingSort }) {
  return orderFindings(unreviewedFindings(findings).filter(finding =>
    (filters.type === "all" || finding.finding_type === filters.type) &&
    (filters.severity === "all" || finding.severity === filters.severity) &&
    (!filters.forSource || finding.evidence.some(evidence => evidence.source_id === filters.forSource)) &&
    matchesFinding(finding, filters.search)), filters.sort);
}
