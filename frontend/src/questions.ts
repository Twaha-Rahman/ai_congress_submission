import type { Answer, Office, QuestionRequest, RecentAnswer } from "./types";
import { date } from "./presentation";

export interface QuestionDraft {
  question: string;
  sourceId: string;
  dated: boolean;
  validAt: string;
  historical: boolean;
  knownAt: string;
  exactDates?: { validAt: string; knownAt: string };
}

export function newQuestion(_office: Office, now = new Date()): QuestionDraft {
  return { question: "", sourceId: "", dated: false, validAt: now.toISOString().slice(0, 16), historical: false, knownAt: "" };
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
  const question = draft.question.trim();
  if (!question) throw new Error("Enter a question about your sources.");
  if (question.length > 500) throw new Error("Keep the question within 500 characters.");
  return { question, target: { subject: "general_policy" },
    source_ids: draft.sourceId ? [draft.sourceId] : [],
    valid_at: draft.dated ? utcInput(draft.validAt, "policy date", draft.exactDates?.validAt) : new Date().toISOString(),
    ...(draft.historical ? { known_at: utcInput(draft.knownAt, "knowledge cutoff", draft.exactDates?.knownAt) } : {}) };
}

export function draftFromAnswer(answer: Pick<Answer, "question" | "valid_at" | "known_at" | "model_metadata">): QuestionDraft {
  let sourceIds: unknown;
  try { sourceIds = JSON.parse(answer.model_metadata?.source_ids || "[]"); } catch { sourceIds = []; }
  return { question: answer.question, sourceId: Array.isArray(sourceIds) && sourceIds.length === 1 && typeof sourceIds[0] === "string" ? sourceIds[0] : "",
    dated: true, validAt: new Date(answer.valid_at).toISOString().slice(0, 23), historical: true,
    knownAt: new Date(answer.known_at).toISOString().slice(0, 23), exactDates: { validAt: answer.valid_at, knownAt: answer.known_at } };
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
