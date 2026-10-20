import type {
  AmountInterval,
  Claim,
  Finding,
  FindingType,
  Scope,
  Source,
} from "./types";

export function humanize(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
export function date(value: string | null | undefined, includeTime = false) {
  if (!value) return "Not specified";
  return (
    new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
      ...(includeTime ? ({ hour: "2-digit", minute: "2-digit" } as const) : {}),
    }).format(new Date(value)) + (includeTime ? " UTC" : "")
  );
}
export function money(minor: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: minor % 100 ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}
export function amountRange(interval: AmountInterval, currency = "USD") {
  const { lower, upper, lower_inclusive: li, upper_inclusive: ui } = interval;
  if (lower !== null && upper !== null && lower === upper)
    return `Exactly ${money(lower, currency)}`;
  const start =
    lower === null
      ? null
      : `${li ? "From" : "Above"} ${money(lower, currency)}`;
  const end =
    upper === null
      ? null
      : `${ui ? "up to" : "below"} ${money(upper, currency)}`;
  if (start && end) return `${start}${li ? (ui ? " " : " to ") : " and "}${end}`;
  return start || end || "All amounts";
}
export function scopeLabel(scope: Scope) {
  if (scope.kind === "policy") return scope.description || "Policy applicability";
  if (scope.kind === "loan" && scope.amount_minor)
    return amountRange(scope.amount_minor, scope.currency);
  return `${humanize(scope.record_class || "records")} · ${humanize(scope.product || "all products")}`;
}
export function scopeContext(scope: Scope) {
  if (scope.kind === "policy") {
    return Object.entries(scope.attributes || {}).map(([key, value]) => `${humanize(key)}: ${value}`).join(" · ") || "See source passages for conditions and exceptions";
  }
  return scope.kind === "loan"
    ? `${humanize(scope.loan_type || "business")} loans · ${scope.currency || "USD"} · ${humanize((scope.origin_office || "").toLowerCase())} origin`
    : `${humanize((scope.origin_office || "").toLowerCase())} → ${humanize((scope.processing_office || "").toLowerCase())} · From ${humanize(scope.starting_event || "loan closure").toLowerCase()}`;
}
export const typeLabels: Record<FindingType, string> = {
  stale_guidance: "Stale guidance",
  incorrect_guidance: "Incorrect guidance",
  contradiction: "Contradiction",
  compliance_gap: "Compliance gap",
  compatible_difference: "Compatible difference",
  supersession: "Policy replacement",
  not_comparable: "Not comparable",
  needs_review: "Needs interpretation",
};
export function findingTitle(finding: Finding) {
  if (finding.subject === "general_policy") {
    if (finding.detail.assessment === "historical") return "Previous policy assessment";
    const titles: Record<FindingType, string> = {
      contradiction: "Policy statements may conflict",
      incorrect_guidance: "Guidance may conflict with policy",
      compliance_gap: "Procedure may fall short of policy",
      stale_guidance: "Guidance may be out of date",
      compatible_difference: "Policy statements appear compatible",
      supersession: "Policy has been replaced",
      not_comparable: "Statements need separate interpretation",
      needs_review: "Policy comparison needs context",
    };
    return titles[finding.finding_type];
  }
  const subject =
    finding.subject === "loan_approval" ? "Approval" : "Retention";
  const titles: Record<FindingType, string> = {
    stale_guidance: `${subject} guidance is out of date`,
    incorrect_guidance: `${subject} guidance conflicts with a requirement`,
    contradiction: `${subject} requirements cannot both be met`,
    compliance_gap: `${subject} procedure falls short of policy`,
    compatible_difference: `${subject} requirements can be met together`,
    supersession: `${subject} policy has been replaced`,
    not_comparable: `${subject} rules need separate interpretation`,
    needs_review: `${subject} rules need human interpretation`,
  };
  return titles[finding.finding_type];
}
export function explanation(finding: Finding) {
  const d = finding.detail;
  if (finding.subject === "general_policy" && d.explanation) {
    return d.explanation + (d.assessment === "model_assisted" ? " This is a model-assisted assessment; review the source passages before acting." : "");
  }
  switch (finding.finding_type) {
    case "stale_guidance":
      return `The guidance matches a superseded requirement. ${d.required ? `The governing requirement is ${d.required}; ` : ""}${d.advised_value ? `the guidance says ${d.advised_value} is sufficient. ` : ""}The mismatch applies only to the scope below.`;
    case "incorrect_guidance":
      return `The guidance does not satisfy the governing requirement${d.required ? ` (${d.required})` : ""}. Compare the source passages before deciding how to respond.`;
    case "supersession":
      return "An explicit policy replacement links these revisions. This records a change in policy; it is not a contradiction alert.";
    case "compatible_difference":
      return `Both requirements can be satisfied at the same time${d.satisfying_value ? ` with a value of ${d.satisfying_value}` : ""}. A difference in wording or minimums does not by itself create a conflict.`;
    case "contradiction":
      return "The allowed values of these requirements do not overlap in the affected scope. Compare their authority and applicability before taking action.";
    case "compliance_gap":
      return "The operating procedure does not meet the policy requirement for the same scope and starting event. Review both passages to establish the change needed.";
    default:
      return "These rules could not be fully compared automatically. Inspect their scope, dates, and original evidence before drawing a conclusion.";
  }
}
export function sourceTitle(source?: Pick<Source, "source_identity">) {
  if (!source) return "Source metadata unavailable";
  const names: Record<string, string> = {
    dhaka_lending_policy: "Business lending policy",
    dha_slack_credit_channel: "Credit team · Slack",
    dhaka_credit_note_restricted: "Credit committee note",
    dhaka_records_procedure: "Records operating procedure",
    frankfurt_records_policy: "Records retention policy",
  };
  return names[source.source_identity] || humanize(source.source_identity);
}
export function ruleSummary(claim?: Claim) {
  if (!claim) return "Rule metadata unavailable";
  if (claim.rule.kind === "policy_statement") return claim.rule.statement || "Policy statement unavailable";
  const kinds: Record<string, string> = {
    required_minimum: "At least",
    maximum_allowed: "At most",
    exactly_required: "Exactly",
    advised_sufficient: "Sufficient:",
    operating_exact: "Operating at",
  };
  const value = claim.rule.value;
  const unit =
    claim.rule.unit === "approvals" && Number(value) === 1
      ? "approval"
      : claim.rule.unit;
  return `${kinds[claim.rule.kind] || humanize(claim.rule.kind)} ${value} ${unit}`;
}
export const sortOptions = [
  { value: "severity", label: "Severity first" },
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "status", label: "Review status" },
  { value: "id", label: "Finding ID" },
];
export type FindingSort = "severity" | "newest" | "oldest" | "status" | "id";

export function findingTag(finding: Pick<Finding, "finding_id">) {
  return `#${finding.finding_id.slice(-8).toUpperCase()}`;
}

export function matchesFinding(finding: Finding, search: string) {
  const query = search.trim().toLowerCase();
  if (!query) return true;
  if (query.startsWith("#"))
    return finding.finding_id.toLowerCase().includes(query.slice(1));
  return [
    findingTitle(finding),
    typeLabels[finding.finding_type],
    scopeLabel(finding.affected_scope),
    finding.finding_id,
    ...finding.evidence.map((e) => e.quote),
  ]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

export function orderFindings(
  findings: Finding[],
  sort: FindingSort = "severity",
) {
  const rank = { high: 0, review: 1, info: 2 };
  const states = { open: 0, acknowledged: 1, resolved: 2, dismissed: 3 };
  const newest = (a: Finding, b: Finding) =>
    Date.parse(b.created_at) - Date.parse(a.created_at);
  const id = (a: Finding, b: Finding) =>
    findingTag(a).localeCompare(findingTag(b)) ||
    a.finding_id.localeCompare(b.finding_id);
  return [...findings].sort((a, b) => {
    if (sort === "newest") return newest(a, b) || id(a, b);
    if (sort === "oldest") return -newest(a, b) || id(a, b);
    if (sort === "id") return id(a, b);
    if (sort === "status")
      return (
        states[a.review_state] - states[b.review_state] ||
        rank[a.severity] - rank[b.severity] ||
        newest(a, b) ||
        id(a, b)
      );
    return rank[a.severity] - rank[b.severity] || newest(a, b) || id(a, b);
  });
}
