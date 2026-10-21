import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, ArrowLeft, ArrowRight, BookOpen, CalendarDays, CircleHelp, Clock3, FileText, Keyboard, Link, LoaderCircle, LockKeyhole, MessageSquare, Plus, RefreshCw, Search, Send, Shield, X } from "lucide-react";
import { api, ApiError } from "./api";
import { EmptyState, ErrorState, Loading, Modal, ShortcutHint } from "./components";
import Select from "./Select";
import DateInput from "./DateInput";
import ShareLink from "./ShareLink";
import Highlight from "./Highlight";
import { DocumentDialog } from "./Sources";
import { date, humanize, sourceTitle, scopeLabel } from "./presentation";
import { answerSearchContext, answerStatusLabels, draftFromAnswer, matchesAnswer, newQuestion, questionRequest, type QuestionDraft } from "./questions";
import { useVerificationData } from "./useVerificationData";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import VerificationExports from "./VerificationTools";
import type { Answer, Office, RecentAnswer, Scope, Session, Source, StoredAnswer } from "./types";
import type { View } from "./viewState";
import "./questions.css";

function factScope(value: string) {
  try { return scopeLabel(JSON.parse(value) as Scope); } catch { return value; }
}

function AnswerBadge({ status, query = "" }: { status: Answer["status"]; query?: string }) {
  const Icon = status === "answered" ? MessageSquare : status === "abstained" ? CircleHelp : AlertCircle;
  return <span className={`badge answer-status answer-${status}`}><Icon size={13} /><Highlight text={answerStatusLabels[status] || humanize(status)} query={query} /></span>;
}

export default function Questions({ office, view, session, sessionError, navigate, shortcutsEnabled, onHelp, onVerify, onFinding }: {
  office: Office; view: View; session: Session | null; sessionError: string; navigate: (patch: Partial<View>, replace?: boolean) => void;
  shortcutsEnabled: boolean; onHelp: () => void; onVerify: (id: string) => void; onFinding: (id: string) => void;
}) {
  const [draft, setDraft] = useState(() => newQuestion(office));
  const [submitted, setSubmitted] = useState<StoredAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [sharing, setSharing] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const questionInput = useRef<HTMLTextAreaElement>(null);
  const share = useRef<HTMLButtonElement>(null);
  const request = useRef<AbortController | null>(null);
  const pendingFocus = useRef(false);
  const browseScroll = useRef(0);
  const history = useVerificationData(`${office}/answers`, signal => api<{ answers: RecentAnswer[]; has_more: boolean }>(`${office}/answers`, { signal }));
  const sources = useVerificationData(`${office}/sources`, signal => api<{ sources: Source[] }>(`${office}/sources`, { signal }));
  const stored = useVerificationData(view.questionId ? `${office}/answers/${view.questionId}` : "", signal => api<StoredAnswer>(`${office}/answers/${encodeURIComponent(view.questionId)}`, { signal }));
  const answer = view.questionId ? submitted?.answer.answer_id === view.questionId ? submitted.answer : stored.data?.answer : undefined;
  const additionalReasons = answer?.partial_reasons.filter(reason => !answer.warnings.some(warning => warning.message === reason)) || [];
  const visible = (history.data?.answers || []).filter(item => matchesAnswer(item, view.questionSearch));
  const [shown, setShown] = useState(10);
  const canAsk = !!session?.queries?.[office];
  const citation = answer?.citations[Number(view.questionCitation)];
  const inspected = view.questionCitation !== "" && citation?.source_id === view.document && !citation.remote ? citation : undefined;

  useEffect(() => { request.current?.abort(); setAsking(false); setError(""); }, [view.questionId]);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { setShown(10); }, [view.questionSearch]);
  useEffect(() => {
    if (answer && pendingFocus.current) {
      pendingFocus.current = false;
      requestAnimationFrame(() => {
        document.getElementById("question-answer-title")?.focus({ preventScroll: true });
        if (window.matchMedia("(max-width: 760px)").matches) document.querySelector(".question-result")?.scrollIntoView({ block: "start" });
      });
    }
  }, [answer, view.questionPane]);

  function patch(values: Partial<QuestionDraft>) { setDraft(previous => ({ ...previous, ...values })); setError(""); }
  function focusComposer() {
    navigate({ questionPane: "compose", questionPanel: "ask", document: "", questionCitation: "" });
    requestAnimationFrame(() => questionInput.current?.focus());
  }
  function focusRecent() {
    navigate({ questionPane: "compose", questionPanel: "recent" });
    requestAnimationFrame(() => document.getElementById("question-tab-recent")?.focus());
  }
  function reuseQuestion() {
    if (!answer || asking) return;
    patch(draftFromAnswer(answer)); focusComposer();
  }
  function selectAnswer(id: string, keyboard = false) {
    if (view.questionPane === "compose") browseScroll.current = window.scrollY;
    request.current?.abort(); setAsking(false); setError("");
    pendingFocus.current = !keyboard;
    navigate({ questionId: id, questionPanel: "recent", questionPane: "answer", questionCitation: "", document: "", page: 1, zoom: 100 }, false);
  }
  function moveAnswer(direction: number) {
    const index = visible.findIndex(item => item.answer_id === view.questionId);
    const next = visible[Math.max(0, Math.min(visible.length - 1, index + direction))];
    if (!next) return;
    const position = visible.indexOf(next); setShown(previous => Math.max(previous, position + 1));
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    selectAnswer(next.answer_id, !mobile);
    requestAnimationFrame(() => {
      const card = document.querySelector<HTMLButtonElement>(`[data-answer-id="${CSS.escape(next.answer_id)}"]`);
      if (!mobile) { card?.focus({ preventScroll: true }); card?.scrollIntoView({ block: "nearest" }); }
    });
  }
  useKeyboardShortcuts(shortcutsEnabled, {
    search: () => { navigate({ questionPane: "compose", questionPanel: "recent" }); requestAnimationFrame(() => { search.current?.focus(); search.current?.select(); }); },
    next: () => moveAnswer(1), previous: () => moveAnswer(-1),
    share: () => { share.current?.focus(); setSharing(true); },
    verify: () => { if (answer) onVerify(answer.answer_id); },
    compose: () => focusComposer(),
    recent: focusRecent,
    reuse: reuseQuestion,
  });

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!canAsk || request.current && !request.current.signal.aborted) return;
    let body;
    try { body = questionRequest(draft); } catch (error) { setError((error as Error).message); return; }
    const controller = new AbortController(); request.current = controller;
    setAsking(true); setError("");
    try {
      const result = await api<StoredAnswer>(`${office}/queries`, { method: "POST", body: JSON.stringify(body), signal: controller.signal });
      if (controller.signal.aborted) return;
      setSubmitted(result); setAsking(false); request.current = null;
      browseScroll.current = 0;
      pendingFocus.current = true;
      navigate({ questionId: result.answer.answer_id, questionPanel: "recent", questionPane: "answer", questionCitation: "", document: "", page: 1, zoom: 100 }, false);
      history.retry();
    } catch (error) {
      if (!controller.signal.aborted) {
        request.current = null; setAsking(false);
        setError((error as Error).message + (error instanceof ApiError && error.status >= 500 ? " Check recent answers before submitting again; the request may have been saved." : ""));
        history.retry();
      }
    }
  }
  function cancel() { request.current?.abort(); request.current = null; setAsking(false); history.retry(); }

  return <div className="questions-page">
    <div className="page-heading"><h1>Questions</h1><div className="page-actions">
      <button className="button secondary shortcuts-button" onClick={onHelp} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (F1)"><Keyboard size={16} />Shortcuts<ShortcutHint>F1</ShortcutHint></button>
      <VerificationExports shortcutsEnabled={shortcutsEnabled} items={answer && !asking ? [{ label: "Saved answer", filename: `${answer.answer_id}.json`, value: stored.data?.answer.answer_id === answer.answer_id ? stored.data : submitted }] : []} />
      <button ref={share} className="button secondary" onClick={() => setSharing(true)} aria-keyshortcuts={shortcutsEnabled ? "Shift+S" : undefined}><Link size={15} />Share view{shortcutsEnabled && <ShortcutHint>Shift+S</ShortcutHint>}</button>
    </div></div>
    <div className={`questions-layout question-pane-${view.questionPane}`}>
      <aside className="question-sidebar" aria-label="Ask and browse questions">
        <div className="question-panel-tabs" role="tablist" aria-label="Question workspace" onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const panel = event.key === "Home" ? "ask" : event.key === "End" ? "recent" : view.questionPanel === "ask" ? "recent" : "ask";
          navigate({ questionPanel: panel }); requestAnimationFrame(() => document.getElementById(`question-tab-${panel}`)?.focus());
        }}>
          <button id="question-tab-ask" role="tab" aria-selected={view.questionPanel === "ask"} aria-controls="question-panel-ask" tabIndex={view.questionPanel === "ask" ? 0 : -1} onClick={() => navigate({ questionPanel: "ask" })} aria-keyshortcuts={shortcutsEnabled ? "N" : undefined}><Plus size={15} />New question{shortcutsEnabled && <ShortcutHint>N</ShortcutHint>}</button>
          <button id="question-tab-recent" role="tab" aria-selected={view.questionPanel === "recent"} aria-controls="question-panel-recent" tabIndex={view.questionPanel === "recent" ? 0 : -1} onClick={() => navigate({ questionPanel: "recent" })} aria-keyshortcuts={shortcutsEnabled ? "B" : undefined}><Clock3 size={15} />Recent answers{shortcutsEnabled && <ShortcutHint>B</ShortcutHint>}</button>
        </div>
        <form className="question-form" id="question-panel-ask" role="tabpanel" aria-labelledby="question-tab-ask" hidden={view.questionPanel !== "ask"} ref={form} onSubmit={ask} onKeyDown={event => {
          if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); form.current?.requestSubmit(); }
        }} aria-busy={asking}>
          <fieldset disabled={asking || !canAsk}>
            <label className="question-field" htmlFor="question-text">Your question</label>
            <textarea ref={questionInput} id="question-text" value={draft.question} onChange={event => patch({ question: event.target.value })}
              maxLength={500} required rows={5} placeholder="Ask anything about your policies, procedures or team messages…" aria-describedby="question-help" />
            <p className="question-help" id="question-help">Answers use the selected sources and include citations. Missing or conflicting evidence is called out.</p>
            <div className="question-field"><span>Sources</span><Select label="Question sources" value={draft.sourceId}
              options={[{ value: "", label: "All accessible sources" }, ...(sources.data?.sources || []).map(source => ({ value: source.source_id, label: `${sourceTitle(source)} · ${source.version_label}` })),
                ...(draft.sourceId && !sources.data?.sources.some(source => source.source_id === draft.sourceId) ? [{ value: draft.sourceId, label: "Selected source unavailable" }] : [])]}
              onChange={sourceId => patch({ sourceId })} /></div>
            <p className="question-help">Original PDF passages and saved Slack messages in this office. Source processing permissions still apply.</p>
            <details className="question-date-options"><summary><CalendarDays size={14} />Date filters <span>{draft.dated || draft.historical ? "Custom" : "Current"}</span></summary>
              <label className="question-checkbox"><input type="checkbox" checked={draft.dated} onChange={event => patch({ dated: event.target.checked })} />Use a historical policy date</label>
              {draft.dated && <><label className="question-field">Policy applies at <DateInput type="datetime-local" step="0.001" value={draft.validAt} onChange={event => patch({ validAt: event.target.value })} required aria-describedby="question-valid-help" /></label><p className="question-help" id="question-valid-help">UTC. Which source versions applied at this time?</p></>}
              <label className="question-checkbox"><input type="checkbox" checked={draft.historical} onChange={event => patch({ historical: event.target.checked })} />Use a historical knowledge cutoff</label>
              {draft.historical ? <><label className="question-field">Information known by <DateInput type="datetime-local" step="0.001" value={draft.knownAt} onChange={event => patch({ knownAt: event.target.value })} required aria-describedby="question-known-help" /></label><p className="question-help" id="question-known-help">UTC. Exclude information learned after this time.</p></> : <p className="question-help">Use everything this office knows when answering.</p>}
            </details>
          </fieldset>
          {!session && (sessionError ? <div className="notice warning" role="alert"><AlertCircle size={17} /><span>Question access could not be loaded. {sessionError} <button type="button" className="text-button" onClick={() => window.location.reload()}>Reload workspace</button></span></div> : <p className="question-help" role="status">Connecting question access…</p>)}
          {session && !canAsk && <div className="notice warning" role="status"><LockKeyhole size={17} /><span>This office’s question connection is not configured. Run make setup and restart the frontend.</span></div>}
          {error && <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{error}</span></div>}
          <div className="question-submit"><button className="button primary" type="submit" disabled={!canAsk || asking} aria-keyshortcuts="Control+Enter Meta+Enter">{asking ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}{asking ? "Answering…" : "Ask question"}<ShortcutHint>⌘ / Ctrl ↵</ShortcutHint></button>{asking && <button type="button" className="button secondary" onClick={cancel}>Cancel</button>}</div>
        </form>
        <section className="question-history" id="question-panel-recent" role="tabpanel" aria-labelledby="question-tab-recent" hidden={view.questionPanel !== "recent"}>
          {asking && <div className="notice" role="status"><LoaderCircle size={16} className="spin" /><span>Answering your question… <button className="text-button" onClick={cancel}>Cancel request</button></span></div>}
          <div className="question-section-heading"><h2 id="recent-questions-title">Recent answers</h2><button className="icon-button" aria-label="Refresh recent answers" title="Refresh recent answers" onClick={history.retry} disabled={history.loading} aria-busy={history.loading}><RefreshCw size={16} className={history.loading ? "spin" : ""} /></button></div>
          <div className="search-input"><Search size={17} /><input ref={search} type="search" aria-label="Search recent answers" placeholder="Search questions or dates…" value={view.questionSearch} onChange={event => navigate({ questionSearch: event.target.value }, true)} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.currentTarget.blur(); } }} />{view.questionSearch ? <button className="icon-button" aria-label="Clear answer search" onClick={() => { navigate({ questionSearch: "" }); search.current?.focus(); }}><X size={15} /></button> : shortcutsEnabled && <ShortcutHint>/</ShortcutHint>}</div>
          {history.error && !history.data && <ErrorState title="Recent answers unavailable" error={history.error} retry={history.retry} />}
          {!history.data && history.loading && <Loading label="Loading recent answers…" />}
          {history.data && <>
            <div className="question-history-meta">
              <p className="question-list-count">{visible.length} {view.questionSearch ? "matching" : "recent"} {visible.length === 1 ? "answer" : "answers"}{history.data.has_more ? " · Latest 50 loaded" : ""}</p>
              <span className={`question-refresh-status ${history.error ? "refresh-failed" : ""}`} role="status" title={history.error ? `${history.error}. Showing the previously loaded answers. Use Refresh to try again.` : undefined}>
                {history.loading ? "Refreshing…" : history.error ? <><AlertCircle size={13} /><span>Refresh failed</span><span className="sr-only">{history.error}. Showing previously loaded answers. Use Refresh to try again.</span></> : null}
              </span>
            </div>
            {!visible.length && <p className="question-help">{view.questionSearch ? "No matching answers. Try another question or date." : "Your saved answers will appear here."}</p>}
            <div className="question-answer-list">{visible.slice(0, shown).map(item => <button key={item.answer_id} data-answer-id={item.answer_id} className={`question-answer-card ${view.questionId === item.answer_id ? "selected" : ""}`} aria-current={view.questionId === item.answer_id ? "true" : undefined} onClick={() => selectAnswer(item.answer_id)}>
              <strong><Highlight text={item.question} query={view.questionSearch} /></strong><span className="question-card-meta"><AnswerBadge status={item.status as Answer["status"]} query={view.questionSearch} /><time><Highlight text={date(item.created_at)} query={view.questionSearch} /></time></span>
              {answerSearchContext(item, view.questionSearch) && <small className="question-id-match"><Highlight text={answerSearchContext(item, view.questionSearch)} query={view.questionSearch} identifier /></small>}
            </button>)}</div>
            {visible.length > shown && <button className="button secondary" onClick={() => setShown(value => value + 10)}>Show more answers</button>}
          </>}
        </section>
      </aside>
      <section className="question-result" aria-label="Selected answer" aria-busy={asking || stored.loading}>
        <button className="button secondary question-mobile-back" onClick={() => {
          navigate({ questionPane: "compose" }); requestAnimationFrame(() => {
            window.scrollTo({ top: browseScroll.current });
            document.querySelector<HTMLButtonElement>(`[data-answer-id="${CSS.escape(view.questionId)}"]`)?.focus({ preventScroll: true });
          });
        }}><ArrowLeft size={15} />Questions</button>
        {asking ? <Loading label="Reading the relevant source passages…" /> : !view.questionId ? <EmptyState icon={<MessageSquare size={27} />} title="Ask a question">Ask about your sources, or open a saved answer.</EmptyState> : <>
          {stored.error && !answer && <ErrorState title="Answer unavailable" error={stored.error} retry={stored.retry} />}
          {!answer && stored.loading && <Loading label="Opening saved answer…" />}
          {answer && <>
            <div className="question-answer-heading"><AnswerBadge status={answer.status} /><span className="question-saved-at"><Clock3 size={14} />Saved {date(answer.created_at, true)}</span></div>
            <h2 id="question-answer-title" tabIndex={-1}>{answer.question}</h2>
            <div className="question-dates"><div><CalendarDays size={17} /><span>Policy applies at<strong>{date(answer.valid_at, true)}</strong></span></div><div><Clock3 size={17} /><span>Information known by<strong>{date(answer.known_at, true)}</strong></span></div></div>
            {answer.target.subject === "general_policy" && <p className="question-help question-model-note">Model-assisted answer · Check the cited passages when making a decision.</p>}
            <div className={`question-answer-text answer-${answer.status}`}><MessageSquare size={20} /><p>{answer.answer_text ? answer.target.subject === "general_policy" ? answer.answer_text.split(/(\[S\d+\])/).map((part, index) => /^\[S\d+\]$/.test(part) && answer.citations.some(c => `[${c.statement_id}]` === part) ? <button className="question-citation-ref" key={index} title={`Show supporting evidence for ${part}`} onClick={() => {
              const citation = document.querySelector<HTMLElement>(`[data-answer-statement="${part.slice(1, -1)}"]`); citation?.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" }); citation?.focus({ preventScroll: true });
            }}>{part}</button> : part) : answer.answer_text : "The office could not establish an answer from the available evidence. Review the warnings below."}</p></div>
            <div className="question-result-actions"><button className="button secondary" onClick={reuseQuestion} disabled={asking} aria-keyshortcuts={shortcutsEnabled ? "Shift+N" : undefined}><Plus size={15} />Use this question{shortcutsEnabled && <ShortcutHint>Shift+N</ShortcutHint>}</button><button className="button secondary" onClick={() => onVerify(answer.answer_id)} aria-keyshortcuts={shortcutsEnabled ? "V" : undefined}><Shield size={15} />Verify answer{shortcutsEnabled && <ShortcutHint>V</ShortcutHint>}</button></div>
            {!!additionalReasons.length && <div className="notice warning"><AlertCircle size={17} /><div><strong>Coverage is incomplete</strong><ul>{additionalReasons.map((reason, index) => <li key={index}>{humanize(reason)}</li>)}</ul></div></div>}
            {!!answer.warnings.length && <section className="question-warnings"><h3><AlertCircle size={17} />What needs attention</h3>{answer.warnings.map((warning, index) => <div className="question-warning" key={index}><p>{warning.message.replace(/^([a-z]+(?:_[a-z]+)+):\s*/, (_, code: string) => `${humanize(code)}: `)}</p>{warning.finding_ids.map(id => <button key={id} className="text-button" onClick={() => onFinding(id)}>View finding <span className="question-warning-tag">#{id.slice(-8).toUpperCase()}</span><ArrowRight size={14} /></button>)}</div>)}</section>}
            <section className="question-evidence"><div className="question-section-heading"><h3><BookOpen size={17} />Supporting evidence</h3><span>{answer.citations.length} {answer.citations.length === 1 ? "citation" : "citations"}</span></div>
              {!answer.citations.length && <p className="question-help">This answer has no supporting citations. It cannot establish a policy requirement.</p>}
              {answer.citations.map((item, index) => {
                const source = sources.data?.sources.find(source => source.source_id === item.source_id);
                return <article key={`${item.claim_revision_id}/${item.statement_id}/${index}`} data-answer-statement={item.statement_id} tabIndex={-1} className={`question-citation authority-${item.authority}`}>
                  <div className="question-citation-top"><span><FileText size={15} />{humanize(item.authority)}</span>{(item.restricted || item.remote) && <span><LockKeyhole size={13} />{item.remote ? "Remote evidence" : "Restricted"}</span>}</div>
                  <div className="question-citation-title"><h4>{sourceTitle({ source_identity: item.source_identity })}</h4><span className="source-version">{item.source_version_label}</span></div>
                  <p className="question-citation-location">Page {item.page}{item.section ? ` · § ${item.section}` : ""} · Statement {item.statement_id}</p>
                  {item.quote ? <blockquote>{item.quote}</blockquote> : <p className="question-help">The source passage is not disclosed in this answer.</p>}
                  {!item.remote && source ? <button className="text-button" onClick={() => navigate({ document: item.source_id, questionCitation: String(index), page: item.page, zoom: 100 }, false)}>Inspect source<ArrowRight size={14} /></button> : <p className="question-help">{item.remote ? "The original stays in its originating office." : sources.loading ? "Loading source access…" : "Source inspection is unavailable in your current access scope."}</p>}
                </article>;
              })}
              {sources.error && <div className="notice warning"><AlertCircle size={17} /><span>Source access could not be loaded. <button className="text-button" onClick={sources.retry}>Retry source access</button></span></div>}
            </section>
            <details className="question-details"><summary>Scope and processing details</summary><dl>
              <dt>Topic</dt><dd>{answer.target.subject === "general_policy" ? "Source question" : answer.target.subject === "loan_approval" ? "Loan approvals" : "Record retention"}</dd>
              {Object.entries(answer.target).filter(([key, value]) => key !== "subject" && value !== null && value !== undefined).map(([key, value]) => <div key={key}><dt>{key === "amount_minor" ? "Loan amount" : humanize(key)}</dt><dd>{key === "amount_minor" ? `USD ${(Number(value) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : humanize(String(value))}</dd></div>)}
              {Object.entries(answer.modes).map(([stage, mode]) => <div key={stage}><dt>{humanize(stage)} mode</dt><dd>{humanize(mode)}</dd></div>)}
              <dt>Answer ID</dt><dd>{answer.answer_id}</dd><dt>Integrity</dt><dd>Not checked here. Use Verify answer to check the signed evidence bundle.</dd>
            </dl>{!!answer.governing_facts.length && <><h4>Governing requirements</h4>{answer.governing_facts.map(fact => <p key={fact.claim_revision_id}>{fact.rule_summary} · {factScope(fact.scope_summary)}<br /><span className="question-help">Effective {date(fact.valid_interval.start)}{fact.valid_interval.end ? ` until ${date(fact.valid_interval.end)}` : " · No recorded end date"}</span></p>)}</>}</details>
          </>}
        </>}
      </section>
    </div>
    {view.document && <DocumentDialog key={view.document} office={office} sourceId={view.document} view={view} navigate={navigate} evidence={inspected ? { source_id: inspected.source_id, page: inspected.page, section: inspected.section, quote: inspected.quote || "" } : undefined} onClose={() => navigate({ document: "", questionCitation: "" })} />}
    {sharing && <Modal title="Share Questions view" onClose={() => setSharing(false)}><div className="dialog-body"><p className="dialog-description">The link includes this office, selected saved answer, search and source location. Unsent questions and source filters stay out of the link. Recipients need access to the same office and evidence.</p><ShareLink /></div></Modal>}
  </div>;
}
