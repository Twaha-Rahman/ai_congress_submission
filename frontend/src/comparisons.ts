import type { Answer, Office, QuestionRequest } from "./types";
import { questionRequest, type QuestionDraft } from "./questions";

export const offices: Office[] = ["dhaka", "frankfurt"];
export interface RuleDraft {
  subject: "record_retention" | "loan_approval";
  origin: Office;
  processing: Office;
  amount: string;
}
export interface OfficeDelivery {
  region: string; status: string; claims: number; withheld_restricted: number;
  reason_codes: string[]; payload_bytes: number; payload_sha256?: string | null; detail?: string | null;
}
export interface GatewayReceipt {
  request_id: string; question: string; query: QuestionRequest; gateway_note: string;
  federated_answer: {
    status: Answer["status"]; generated_at: string; offices: OfficeDelivery[];
    not_checked: string[]; no_raw_source_text_transferred: boolean;
    warnings?: { code: string; message: string }[];
    statements?: { statement_id: string; text: string }[];
    contributions?: { origin_region: string; revision_id: string; authority: string; rule_summary: string; source_ref: string; manifest_root: string }[];
    comparator_region?: string;
    comparison?: { answer: Answer; local_answer_id: string; transport_redaction?: { note: string } };
    import?: { accepted: boolean; received_at?: string; snapshot_ids?: string[] };
    origin_export?: { origin_region: string; claims: number; withheld_restricted: number; payload_bytes: number; payload_sha256: string; reason_codes: string[] };
  };
}

export function generalRequests(draft: QuestionDraft, sourceIds: Record<Office, string>, now = new Date()) {
  const request = questionRequest(draft);
  // The two offices receive identical applicability and knowledge cutoffs.
  if (!draft.dated) request.valid_at = now.toISOString();
  request.known_at ||= now.toISOString();
  return Object.fromEntries(offices.map(office => [office, { ...request, source_ids: sourceIds[office] ? [sourceIds[office]] : [] }])) as Record<Office, QuestionRequest>;
}
export function ruleRequest(draft: QuestionDraft, rules: RuleDraft): QuestionRequest {
  const body = questionRequest({ ...draft, question: draft.question.trim() || (rules.subject === "record_retention" ? "Compare cross-office record retention requirements and operating procedures." : "Compare applicable loan approval requirements across offices.") });
  delete body.source_ids;
  if (rules.subject === "record_retention") {
    if (rules.origin === rules.processing) throw new Error("Choose different originating and processing offices.");
    body.target = { subject: rules.subject, origin_office: rules.origin.toUpperCase() as "DHAKA" | "FRANKFURT", processing_office: rules.processing.toUpperCase() as "DHAKA" | "FRANKFURT", record_class: "loan_records", starting_event: "loan_closure", product: "MTF_CROSS_OFFICE" };
  } else {
    const amount = rules.amount.trim();
    if (!/^\d+(?:\.\d{1,2})?$/.test(amount) || Number(amount) <= 0 || !Number.isSafeInteger(Math.round(Number(amount) * 100))) throw new Error("Enter a positive USD loan amount with at most two decimal places.");
    body.target = { subject: rules.subject, amount_minor: Math.round(Number(amount) * 100), currency: "USD", loan_type: "business", origin_office: rules.origin.toUpperCase() as "DHAKA" | "FRANKFURT" };
  }
  return body;
}
export function receiptCoverage(receipt: GatewayReceipt) {
  const answer = receipt.federated_answer;
  const missing = answer.offices.filter(office => office.status !== "delivered" || !office.claims);
  const withheld = answer.offices.reduce((sum, office) => sum + office.withheld_restricted, 0);
  const warnings = answer.comparison?.answer.warnings || answer.warnings || [];
  const partial = answer.status !== "answered" || missing.length > 0 || withheld > 0 || !!answer.comparison?.answer.partial_reasons.length;
  return { missing, withheld, warnings, partial };
}
export function sameQuestionContext(answers: Answer[]) {
  if (answers.length < 2) return true;
  return answers.every(answer => answer.question === answers[0].question && Date.parse(answer.valid_at) === Date.parse(answers[0].valid_at) && Date.parse(answer.known_at) === Date.parse(answers[0].known_at));
}
