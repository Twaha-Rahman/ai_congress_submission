import type { Answer, Office, QuestionRequest, QuestionTarget, RecentAnswer } from "./types";

export interface QuestionDraft {
  subject: QuestionTarget["subject"];
  question: string;
  amount: string;
  origin: "" | "DHAKA" | "FRANKFURT";
  processing: "" | "DHAKA" | "FRANKFURT";
  product: "" | "MTF_CROSS_OFFICE";
  validAt: string;
  historical: boolean;
  knownAt: string;
}

export function newQuestion(office: Office, now = new Date()): QuestionDraft {
  return { subject: "loan_approval", question: "", amount: "", origin: office === "dhaka" ? "DHAKA" : "FRANKFURT",
    processing: "", product: "", validAt: now.toISOString().slice(0, 16), historical: false, knownAt: "" };
}

/** Parse decimal USD without silently rounding cents or accepting exponent notation. */
export function amountMinor(value: string) {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value.trim())) throw new Error("Enter a positive USD amount with up to two decimal places, without commas.");
  const [whole, fraction = ""] = value.trim().split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents <= 0n || cents > 10n ** 15n) throw new Error("Enter an amount above zero and no greater than USD 10 trillion.");
  return Number(cents);
}

function utcInput(value: string, label: string) {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,3})?)?$/.test(value) || !Number.isFinite(Date.parse(`${value}Z`)))
    throw new Error(`Choose a valid ${label} in UTC.`);
  return new Date(`${value}Z`).toISOString();
}

export function questionRequest(draft: QuestionDraft): QuestionRequest {
  let target: QuestionTarget;
  let fallback: string;
  if (draft.subject === "loan_approval") {
    const amount = amountMinor(draft.amount);
    if (!draft.origin) throw new Error("Choose the loan's originating office.");
    target = { subject: draft.subject, amount_minor: amount, currency: "USD", loan_type: "business", origin_office: draft.origin };
    fallback = `How many approvals are required for a USD ${(amount / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} business loan originated in ${draft.origin === "DHAKA" ? "Dhaka" : "Frankfurt"}?`;
  } else {
    target = { subject: draft.subject, record_class: "loan_records", starting_event: "loan_closure",
      ...(draft.origin ? { origin_office: draft.origin } : {}), ...(draft.processing ? { processing_office: draft.processing } : {}),
      ...(draft.product ? { product: draft.product } : {}) };
    fallback = "How long must loan records be retained after loan closure?";
  }
  const question = draft.question.trim() || fallback;
  if (question.length > 500) throw new Error("Keep the question label within 500 characters.");
  return { question, target, valid_at: utcInput(draft.validAt, "policy date"),
    ...(draft.historical ? { known_at: utcInput(draft.knownAt, "knowledge cutoff") } : {}) };
}

export function draftFromAnswer(answer: Answer): QuestionDraft {
  const target = answer.target;
  return { subject: target.subject, question: answer.question, amount: target.amount_minor == null ? "" : (target.amount_minor / 100).toFixed(2),
    origin: target.origin_office || "", processing: target.processing_office || "", product: target.product || "",
    validAt: answer.valid_at.replace(/Z|\+00:00$/, ""), historical: true, knownAt: answer.known_at.replace(/Z|\+00:00$/, "") };
}

export const answerStatusLabels = { answered: "Answered", needs_review: "Needs review", abstained: "Unable to answer", partial: "Partial answer" };

export function matchesAnswer(answer: RecentAnswer, search: string) {
  const query = search.trim().toLowerCase();
  return !query || `${answer.question} ${answer.answer_id} ${answer.created_at} ${answer.status} ${answerStatusLabels[answer.status as Answer["status"]] || ""} ${new Date(answer.created_at).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })}`.toLowerCase().includes(query);
}
