import type { Answer, Office, QuestionRequest, QuestionTarget, RecentAnswer } from "./types";
import { date } from "./presentation";

export interface QuestionDraft {
  subject: QuestionTarget["subject"];
  question: string;
  amount: string;
  origin: "" | "DHAKA" | "FRANKFURT";
  processing: "" | "DHAKA" | "FRANKFURT";
  validAt: string;
  historical: boolean;
  knownAt: string;
  exactDates?: { validAt: string; knownAt: string };
}

export function newQuestion(office: Office, now = new Date()): QuestionDraft {
  return { subject: "loan_approval", question: "", amount: "", origin: office === "dhaka" ? "DHAKA" : "FRANKFURT",
    processing: "", validAt: now.toISOString().slice(0, 16), historical: false, knownAt: "" };
}

/** Parse decimal USD without silently rounding cents or accepting exponent notation. */
export function amountMinor(value: string) {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value.trim())) throw new Error("Enter a positive USD amount with up to two decimal places, without commas.");
  const [whole, fraction = ""] = value.trim().split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents <= 0n || cents > 10n ** 15n) throw new Error("Enter an amount above zero and no greater than USD 10 trillion.");
  return Number(cents);
}

function utcInput(value: string, label: string, original?: string) {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,3})?)?$/.test(value) || !Number.isFinite(Date.parse(`${value}Z`)))
    throw new Error(`Choose a valid ${label} in UTC.`);
  const result = new Date(`${value}Z`).toISOString();
  if (result.slice(0, 16) !== value.slice(0, 16)) throw new Error(`Choose a valid ${label} in UTC.`);
  // Browser date controls support milliseconds; saved knowledge cutoffs can
  // contain microseconds. Preserve the original until the displayed time changes.
  if (original && /\.\d{4,}/.test(original) && Date.parse(original) === Date.parse(result)) return original;
  return result;
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
      product: "MTF_CROSS_OFFICE" };
    fallback = "How long must loan records be retained after loan closure?";
  }
  const question = draft.question.trim() || fallback;
  if (question.length > 500) throw new Error("Keep the question label within 500 characters.");
  return { question, target, valid_at: utcInput(draft.validAt, "policy date", draft.exactDates?.validAt),
    ...(draft.historical ? { known_at: utcInput(draft.knownAt, "knowledge cutoff", draft.exactDates?.knownAt) } : {}) };
}

export function draftFromAnswer(answer: Answer): QuestionDraft {
  const target = answer.target;
  return { subject: target.subject, question: answer.question, amount: target.amount_minor == null ? "" : (target.amount_minor / 100).toFixed(2),
    origin: target.origin_office || "", processing: target.processing_office || "",
    validAt: new Date(answer.valid_at).toISOString().slice(0, 23), historical: true, knownAt: new Date(answer.known_at).toISOString().slice(0, 23),
    exactDates: { validAt: answer.valid_at, knownAt: answer.known_at } };
}

export const answerStatusLabels = { answered: "Answered", needs_review: "Needs review", abstained: "Unable to answer", partial: "Partial answer" };

export function matchesAnswer(answer: RecentAnswer, search: string) {
  const query = search.trim().toLowerCase();
  return !query || [answer.question, answer.answer_id, answer.created_at, answerStatusLabels[answer.status as Answer["status"]] || "", date(answer.created_at)].some(value => value.toLowerCase().includes(query));
}

export function answerSearchContext(answer: RecentAnswer, search: string) {
  const query = search.trim().toLowerCase();
  if (!query || [answer.question, answerStatusLabels[answer.status as Answer["status"]] || "", date(answer.created_at)].some(value => value.toLowerCase().includes(query))) return "";
  return [answer.answer_id, answer.created_at].find(value => value.toLowerCase().includes(query)) || "";
}
