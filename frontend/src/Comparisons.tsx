import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, ArrowRight, BookOpen, CalendarDays, Check, CircleHelp, Clock3, Copy, FileText, Globe2, Keyboard, Link, LoaderCircle, LockKeyhole, MessageSquare, Network, Plus, Send, Shield, ShieldCheck } from "lucide-react";
import { api, ApiError } from "./api";
import { EmptyState, ErrorState, Loading, Modal, ShortcutHint } from "./components";
import Select from "./Select";
import { DocumentDialog } from "./Sources";
import VerificationExports from "./VerificationTools";
import { date, humanize, sourceTitle } from "./presentation";
import { answerStatusLabels, newQuestion, type QuestionDraft } from "./questions";
import { generalRequests, offices, receiptCoverage, ruleRequest, sameQuestionContext, type GatewayReceipt, type OfficeDelivery, type RuleDraft } from "./comparisons";
import { useVerificationData } from "./useVerificationData";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import type { Answer, Office, QuestionRequest, Session, Source, StoredAnswer } from "./types";
import type { View } from "./viewState";
import "./questions.css";
import "./comparisons.css";

function Status({ status }: { status: Answer["status"] }) {
  const Icon = status === "answered" ? MessageSquare : status === "abstained" ? CircleHelp : AlertCircle;
  return <span className={`badge answer-status answer-${status}`}><Icon size={13} />{answerStatusLabels[status] || humanize(status)}</span>;
}
function Delivery({ office }: { office: OfficeDelivery }) {
  const delivered = office.status === "delivered";
  return <article className="comparison-delivery">
    <div className="comparison-office-heading"><h3><Globe2 size={17} />{humanize(office.region.toLowerCase())}</h3><span className={`badge ${delivered && office.claims ? "comparison-delivered" : "comparison-attention"}`}>{delivered && office.claims ? <ShieldCheck size={13} /> : <AlertCircle size={13} />}{delivered ? office.claims ? "Signed export received" : "No matching rules" : humanize(office.status)}</span></div>
    <div className="comparison-delivery-counts"><span><BookOpen size={15} /><strong>{office.claims}</strong> {office.claims === 1 ? "rule" : "rules"} exported</span><span><LockKeyhole size={15} /><strong>{office.withheld_restricted}</strong> withheld</span><span><Network size={15} />{office.payload_bytes.toLocaleString()} bytes</span></div>
    {!!office.reason_codes.length && <ul className="comparison-reasons">{office.reason_codes.map(code => <li key={code}>{humanize(code)}</li>)}</ul>}
    {office.detail && <p className="question-help">{office.detail}</p>}
    {office.payload_sha256 && <details className="comparison-proof"><summary>Payload commitment</summary><code>{office.payload_sha256}</code></details>}
  </article>;
}

type Batch = { key: string; busy: boolean; answers: Partial<Record<Office, Answer>>; errors: Partial<Record<Office, string>>; pending: Office[] };
const emptyBatch: Batch = { key: "", busy: false, answers: {}, errors: {}, pending: [] };

export default function Comparisons({ view, session, sessionError, navigate, shortcutsEnabled, onHelp, onVerify, onAnswer }: {
  view: View; session: Session | null; sessionError: string; navigate: (patch: Partial<View>, replace?: boolean) => void;
  shortcutsEnabled: boolean; onHelp: () => void; onVerify: (office: Office, id: string) => void; onAnswer: (office: Office, id?: string) => void;
}) {
  const [draft, setDraft] = useState(() => newQuestion(view.office));
  const [sourceIds, setSourceIds] = useState<Record<Office, string>>({ dhaka: "", frankfurt: "" });
  const [rules, setRules] = useState<RuleDraft>({ subject: "record_retention", origin: "dhaka", processing: "frankfurt", amount: "" });
  const [batch, setBatch] = useState<Batch>(emptyBatch);
  const [submitted, setSubmitted] = useState<GatewayReceipt>();
  const [ruleBusy, setRuleBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorOffices, setErrorOffices] = useState<OfficeDelivery[]>([]);
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const request = useRef<AbortController | null>(null);
  const expectedKey = useRef("");
  const questionInput = useRef<HTMLTextAreaElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const resultSection = useRef<HTMLElement>(null);
  const shareButton = useRef<HTMLButtonElement>(null);
  const busy = batch.busy || ruleBusy;
  const currentKey = `${view.compareMode}/${view.compareDhaka}/${view.compareFrankfurt}/${view.compareRequest}`;
  const pairKey = `${view.compareDhaka}/${view.compareFrankfurt}`;
  const ids = { dhaka: view.compareDhaka, frankfurt: view.compareFrankfurt };
  const dhakaSources = useVerificationData("dhaka/sources", signal => api<{ sources: Source[] }>("dhaka/sources", { signal }));
  const frankfurtSources = useVerificationData("frankfurt/sources", signal => api<{ sources: Source[] }>("frankfurt/sources", { signal }));
  const sourceReads = { dhaka: dhakaSources, frankfurt: frankfurtSources };
  const dhakaSaved = useVerificationData(view.compareDhaka ? `dhaka/answers/${view.compareDhaka}` : "", signal => api<StoredAnswer>(`dhaka/answers/${encodeURIComponent(view.compareDhaka)}`, { signal }));
  const frankfurtSaved = useVerificationData(view.compareFrankfurt ? `frankfurt/answers/${view.compareFrankfurt}` : "", signal => api<StoredAnswer>(`frankfurt/answers/${encodeURIComponent(view.compareFrankfurt)}`, { signal }));
  const saved = { dhaka: dhakaSaved, frankfurt: frankfurtSaved };
  const receiptRead = useVerificationData(view.compareMode === "rules" && view.compareRequest ? `gateway/queries/${view.compareRequest}` : "", signal => api<GatewayReceipt>(`gateway/queries/${encodeURIComponent(view.compareRequest)}`, { signal }));
  const receipt = submitted?.request_id === view.compareRequest ? submitted : receiptRead.data;
  const local = batch.busy || batch.key === pairKey;
  const answers = Object.fromEntries(offices.map(office => {
    const fromCurrentRun = batch.busy || (local && batch.answers[office]?.answer_id === ids[office]);
    return [office, fromCurrentRun ? batch.answers[office] : saved[office].data?.answer];
  })) as Partial<Record<Office, Answer>>;
  const activeAnswers = offices.flatMap(office => answers[office] ? [answers[office]!] : []);
  const coverage = receipt ? receiptCoverage(receipt) : undefined;
  const evidenceOffice = view.compareSourceOffice;
  const citation = view.compareCitation !== "" ? answers[evidenceOffice]?.citations[Number(view.compareCitation)] : undefined;
  const evidence = citation && !citation.remote && citation.source_id === view.document ? citation : undefined;

  useEffect(() => {
    if (request.current && currentKey !== expectedKey.current) { request.current.abort(); request.current = null; setBatch(value => ({ ...value, busy: false, pending: [] })); setRuleBusy(false); }
    setError(""); setErrorOffices([]);
  }, [currentKey]);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (!busy || view.comparePane !== "results") return;
    requestAnimationFrame(() => { resultSection.current?.focus({ preventScroll: true }); resultSection.current?.scrollIntoView({ block: "start" }); });
  }, [busy, view.comparePane]);
  useEffect(() => { if (copied === "idle") return; const timer = setTimeout(() => setCopied("idle"), 1800); return () => clearTimeout(timer); }, [copied]);
  function patch(value: Partial<QuestionDraft>) { setDraft(previous => ({ ...previous, ...value })); setError(""); }
  function focusForm() {
    if (busy) return;
    navigate({ comparePane: "setup" }, true);
    requestAnimationFrame(() => { questionInput.current?.focus(); questionInput.current?.scrollIntoView({ block: "center" }); });
  }
  useKeyboardShortcuts(shortcutsEnabled, { compose: focusForm, share: () => { if (!busy) { shareButton.current?.focus(); setSharing(true); } } });
  function changeMode(mode: View["compareMode"]) { if (!busy) navigate({ compareMode: mode, comparePane: (mode === "rules" ? view.compareRequest : view.compareDhaka || view.compareFrankfurt) ? "results" : "setup", document: "", compareCitation: "" }, false); }
  function cancel() {
    request.current?.abort(); request.current = null; setRuleBusy(false);
    const dhaka = batch.answers.dhaka?.answer_id || "", frankfurt = batch.answers.frankfurt?.answer_id || "";
    const key = `${dhaka}/${frankfurt}`;
    setBatch(value => ({ ...value, key, busy: false, pending: [], errors: { ...value.errors, ...Object.fromEntries(value.pending.map(office => [office, "Stopped waiting. Check this office’s recent answers before submitting again; it may still finish."])) } }));
    if (view.compareMode === "general") { expectedKey.current = `general/${dhaka}/${frankfurt}/`; navigate({ compareDhaka: dhaka, compareFrankfurt: frankfurt, compareRequest: "", comparePane: "results", document: "", compareCitation: "" }, true); }
    else setError("Stopped waiting. The gateway may still complete the comparison. No automatic retry was sent.");
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || request.current) return;
    let bodies: Record<Office, QuestionRequest> | undefined, ruleBody: QuestionRequest | undefined;
    try { if (view.compareMode === "general") bodies = generalRequests(draft, sourceIds); else ruleBody = ruleRequest(draft, rules); }
    catch (failure) { setError((failure as Error).message); return; }
    const controller = new AbortController(); request.current = controller;
    setError(""); setErrorOffices([]);
    expectedKey.current = `${view.compareMode}///`;
    navigate({ compareDhaka: "", compareFrankfurt: "", compareRequest: "", comparePane: "results", document: "", compareCitation: "" }, false);
    if (bodies) {
      setBatch({ ...emptyBatch, busy: true, pending: [...offices] });
      const results: Partial<Record<Office, Answer>> = {};
      await Promise.allSettled(offices.map(async office => {
        try {
          if (!session?.queries?.[office]) throw new Error("This office’s question connection is not configured.");
          const result = await api<StoredAnswer>(`${office}/queries`, { method: "POST", body: JSON.stringify(bodies[office]), signal: controller.signal });
          if (controller.signal.aborted) return;
          results[office] = result.answer;
          setBatch(value => ({ ...value, answers: { ...value.answers, [office]: result.answer }, pending: value.pending.filter(item => item !== office) }));
        } catch (failure) {
          if (controller.signal.aborted) return;
          const message = (failure as Error).message + (failure instanceof ApiError && failure.status >= 500 ? " Check recent answers before submitting again; this request may have been saved." : "");
          setBatch(value => ({ ...value, errors: { ...value.errors, [office]: message }, pending: value.pending.filter(item => item !== office) }));
        }
      }));
      if (controller.signal.aborted) return;
      const dhaka = results.dhaka?.answer_id || "", frankfurt = results.frankfurt?.answer_id || "";
      setBatch(value => ({ ...value, busy: false, key: `${dhaka}/${frankfurt}` })); request.current = null;
      expectedKey.current = `general/${dhaka}/${frankfurt}/`;
      navigate({ compareDhaka: dhaka, compareFrankfurt: frankfurt, compareRequest: "", comparePane: "results", document: "", compareCitation: "" }, true);
    } else {
      setRuleBusy(true);
      try {
        const result = await api<GatewayReceipt>("gateway/queries", { method: "POST", body: JSON.stringify(ruleBody), signal: controller.signal });
        if (controller.signal.aborted) return;
        setSubmitted(result); setRuleBusy(false); request.current = null;
        expectedKey.current = `rules///${result.request_id}`;
        navigate({ compareRequest: result.request_id, compareDhaka: "", compareFrankfurt: "", comparePane: "results", document: "", compareCitation: "" }, true);
      } catch (failure) {
        if (controller.signal.aborted) return;
        request.current = null; setRuleBusy(false); setError((failure as Error).message);
        if (failure instanceof ApiError && Array.isArray(failure.detail.offices)) setErrorOffices(failure.detail.offices as OfficeDelivery[]);
      }
    }
  }
  async function copyLink() { try { await navigator.clipboard.writeText(window.location.href); setCopied("copied"); } catch { setCopied("failed"); } }
  const canSubmit = view.compareMode === "rules" ? !!session?.comparisons?.rules : offices.some(office => session?.queries?.[office]);
  const exports = view.compareMode === "rules" ? receipt ? [{ label: "Gateway comparison receipt", filename: `${receipt.request_id}.json`, value: receipt }] : [] : offices.flatMap(office => answers[office] ? [{ label: `${humanize(office)} saved answer`, filename: `${office}-${answers[office]!.answer_id}.json`, value: { answer: answers[office] } }] : []);

  return <div className="comparisons-page">
    <div className="page-heading"><h1>Cross-office</h1><div className="page-actions">
      <button className="button secondary shortcuts-button" onClick={onHelp} title="Keyboard shortcuts (F1)"><Keyboard size={16} />Shortcuts<ShortcutHint>F1</ShortcutHint></button>
      {view.comparePane === "results" && <button className="button secondary" onClick={focusForm} disabled={busy}><Plus size={15} />New comparison{shortcutsEnabled && <ShortcutHint>N</ShortcutHint>}</button>}
      <VerificationExports items={busy ? [] : exports} shortcutsEnabled={shortcutsEnabled} />
      <button ref={shareButton} className="button secondary" disabled={busy} onClick={() => { setCopied("idle"); setSharing(true); }} aria-keyshortcuts={shortcutsEnabled ? "Shift+S" : undefined}><Link size={15} />Share view{shortcutsEnabled && <ShortcutHint>Shift+S</ShortcutHint>}</button>
    </div></div>
    <div className="comparison-tabs" role="tablist" aria-label="Comparison method" onKeyDown={event => {
      if (busy || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); const mode = event.key === "Home" ? "general" : event.key === "End" ? "rules" : view.compareMode === "general" ? "rules" : "general";
      changeMode(mode); requestAnimationFrame(() => document.getElementById(`compare-tab-${mode}`)?.focus());
    }}>{([ ["general", "Source answers", MessageSquare], ["rules", "Signed-rule check", ShieldCheck] ] as const).map(([mode, label, Icon]) => <button key={mode} id={`compare-tab-${mode}`} role="tab" aria-selected={view.compareMode === mode} aria-controls="comparison-panel" tabIndex={view.compareMode === mode ? 0 : -1} disabled={busy} onClick={() => changeMode(mode)}><Icon size={16} />{label}</button>)}</div>
    <div id="comparison-panel" role="tabpanel" aria-labelledby={`compare-tab-${view.compareMode}`}>
      <form ref={form} className="question-form comparison-form" hidden={view.comparePane !== "setup"} onSubmit={submit} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); form.current?.requestSubmit(); } }}>
        <div className="comparison-method"><span className="comparison-method-icon">{view.compareMode === "general" ? <MessageSquare size={21} /> : <ShieldCheck size={21} />}</span><div><h2>{view.compareMode === "general" ? "One question. Two office answers." : "Compare approved structured rules"}</h2><p>{view.compareMode === "general" ? "Each office answers from its own sources. Review the cited answers together; no combined verdict is inferred." : "The gateway exchanges signed rules. Original passages stay in their office; passage inclusion is not checked."}</p></div></div>
        <fieldset disabled={busy || !canSubmit}>
          <label className="question-field" htmlFor="comparison-question">{view.compareMode === "general" ? "Your question" : "Question label (optional)"}{shortcutsEnabled && <ShortcutHint>N</ShortcutHint>}</label>
          <textarea ref={questionInput} id="comparison-question" rows={3} maxLength={500} required={view.compareMode === "general"} value={draft.question} placeholder={view.compareMode === "general" ? "What approvals are needed before buying new software?" : "Describe this check…"} onChange={event => patch({ question: event.target.value })} />
          {view.compareMode === "general" ? <div className="comparison-form-grid">{offices.map(office => <div key={office}><div className="question-field"><span><Globe2 size={14} />{humanize(office)} sources</span><Select label={`${humanize(office)} comparison sources`} value={sourceIds[office]} onChange={value => setSourceIds(previous => ({ ...previous, [office]: value }))} options={[{ value: "", label: "All accessible sources" }, ...(sourceReads[office].data?.sources || []).map(source => ({ value: source.source_id, label: `${sourceTitle(source)} · ${source.version_label}` })), ...(sourceIds[office] && !sourceReads[office].data?.sources.some(source => source.source_id === sourceIds[office]) ? [{ value: sourceIds[office], label: "Selected source unavailable" }] : [])]} /></div>{sourceReads[office].error && <p className="question-help" role="status">Source list unavailable. <button type="button" className="text-button" onClick={sourceReads[office].retry}>Retry list</button></p>}</div>)}</div> : <>
            <div className="comparison-form-grid"><div className="question-field"><span>Rule type</span><Select label="Comparison rule type" value={rules.subject} onChange={subject => setRules(previous => ({ ...previous, subject: subject as RuleDraft["subject"] }))} options={[{ value: "record_retention", label: "Record retention" }, { value: "loan_approval", label: "Loan approvals" }]} /></div><div className="question-field"><span>Originating office</span><Select label="Originating office" value={rules.origin} onChange={value => setRules(previous => ({ ...previous, origin: value as Office, processing: value === "dhaka" ? "frankfurt" : "dhaka" }))} options={offices.map(office => ({ value: office, label: humanize(office) }))} /></div>
              {rules.subject === "record_retention" ? <div className="question-field"><span>Processing office</span><Select label="Processing office" value={rules.processing} onChange={value => setRules(previous => ({ ...previous, processing: value as Office }))} options={offices.map(office => ({ value: office, label: humanize(office) }))} /></div> : <label className="question-field">Business loan amount (USD)<input inputMode="decimal" value={rules.amount} placeholder="25000.00" required onChange={event => setRules(previous => ({ ...previous, amount: event.target.value }))} /></label>}</div>
            <p className="question-help comparison-scope"><BookOpen size={14} />{rules.subject === "record_retention" ? "Loan records · MTF_CROSS_OFFICE · Retention measured from loan closure. The processing office compares its policy with the origin’s exported rules." : "Business loans · USD · Both offices export rules applicable to this origin and amount."}</p>
            <p className="question-help">This strict protocol supports these two numeric rule types. Use Source answers for any other policy topic.</p>
          </>}
          <details className="question-date-options"><summary><CalendarDays size={14} />Date filters<span>{draft.dated || draft.historical ? "Custom · UTC" : "Current"}</span></summary><div className="comparison-form-grid">
            <div><label className="question-checkbox"><input type="checkbox" checked={draft.dated} onChange={event => patch({ dated: event.target.checked })} />Choose policy date</label>{draft.dated && <label className="question-field">Policy applies at (UTC)<input type="datetime-local" step="0.001" required value={draft.validAt} onChange={event => patch({ validAt: event.target.value })} /></label>}</div>
            <div><label className="question-checkbox"><input type="checkbox" checked={draft.historical} onChange={event => patch({ historical: event.target.checked })} />Choose knowledge cutoff</label>{draft.historical && <label className="question-field">Information known by (UTC)<input type="datetime-local" step="0.001" required value={draft.knownAt} onChange={event => patch({ knownAt: event.target.value })} /></label>}</div>
          </div><p className="question-help">Policy date controls applicability; knowledge cutoff excludes information learned later.{view.compareMode === "rules" ? " An export received after a historical cutoff cannot complete that historical comparison." : " Both offices receive the same cutoffs."}</p></details>
        </fieldset>
        {view.compareMode === "general" && <p className="question-help comparison-privacy"><LockKeyhole size={14} />This browser reads both offices using your configured access. Source text is shown here; it is not exchanged through the gateway. Each office’s model permissions still apply.</p>}
        {(!session || !canSubmit) && <p className="question-help" role="status">{sessionError || (!session ? "Connecting workspace access…" : view.compareMode === "rules" ? session.role === "reader" ? "Signed-rule checks require reviewer access." : "Configure DEMO_TOKEN_GATEWAY_SERVICE and restart the frontend to enable signed-rule checks." : "Office question connections are not configured.")}</p>}
        <div className="question-submit"><button className="button primary" type="submit" disabled={busy || !canSubmit} aria-keyshortcuts="Control+Enter Meta+Enter">{busy ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />}{busy ? "Comparing…" : view.compareMode === "general" ? "Ask both offices" : "Run signed-rule check"}<ShortcutHint>⌘ / Ctrl ↵</ShortcutHint></button>{busy && <button type="button" className="button secondary" onClick={cancel}>Stop waiting</button>}</div>
      </form>
      {busy && view.comparePane === "results" && <div className="notice" role="status"><LoaderCircle className="spin" size={17} /><span>{ruleBusy ? "Checking signed rules…" : "Asking both offices…"}</span><button className="text-button" onClick={cancel}>Stop waiting</button></div>}
      {error && <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{error}</span></div>}
      {!!errorOffices.length && <div className="comparison-columns">{errorOffices.map(office => <Delivery key={office.region} office={office} />)}</div>}
      {view.compareMode === "general" ? <section ref={resultSection} className="comparison-results" tabIndex={-1} aria-label="Office answers">
        {!!activeAnswers.length && <div className="comparison-result-heading"><h2>{activeAnswers[0].question}</h2><p>{!sameQuestionContext(activeAnswers) ? "These saved answers have different questions or date cutoffs. They are not the same comparison." : batch.busy ? "Each office’s answer appears when ready." : activeAnswers.length === 2 ? "Two independent, model-assisted answers. Differences need human review." : "Only one saved answer is available. This comparison is incomplete."}</p><div className="question-dates"><div><CalendarDays size={16} /><span>Policy applies at<strong>{date(activeAnswers[0].valid_at, true)}</strong></span></div><div><Clock3 size={16} /><span>Information known by<strong>{date(activeAnswers[0].known_at, true)}</strong></span></div></div></div>}
        <div className="comparison-columns">{offices.map(office => {
          const answer = answers[office]; const read = saved[office];
          const officeError = local ? batch.errors[office] || read.error : read.error;
          const pending = batch.busy ? batch.pending.includes(office) : !!ids[office] && !answer && read.loading;
          return <article className="comparison-answer" key={office} aria-label={`${humanize(office)} answer`} aria-busy={pending}><header className="comparison-office-heading"><h3><Globe2 size={18} />{humanize(office)}</h3>{answer && <Status status={answer.status} />}</header>
            {pending && <Loading label="Reading this office’s sources…" />}
            {officeError && !answer && <div className="comparison-office-error" role="alert"><AlertCircle size={19} /><p>{officeError}</p>{ids[office] && <button className="button secondary" onClick={read.retry}>Reload saved answer</button>}<button className="text-button" onClick={() => onAnswer(office)}>Check recent answers<ArrowRight size={14} /></button></div>}
            {!pending && !officeError && !answer && <p className="comparison-awaiting">{ids[office] ? "This answer is unavailable." : "No saved answer selected for this office."}</p>}
            {answer && <>
              <span className="sr-only" role="status">{humanize(office)}: {answerStatusLabels[answer.status]}.</span>
              {!sameQuestionContext(activeAnswers) && <p className="question-help">{answer.question} · {date(answer.valid_at, true)} · Known by {date(answer.known_at, true)}</p>}
              <div className="comparison-answer-text">{answer.answer_text.split(/(\[S\d+\])/).map((part, index) => /^\[S\d+\]$/.test(part) && answer.citations.some(item => `[${item.statement_id}]` === part) ? <button key={index} className="question-citation-ref" title={`Show ${humanize(office)} evidence ${part}`} onClick={() => { const target = document.getElementById(`compare-${office}-${part.slice(1, -1)}`); if (target instanceof HTMLDetailsElement) target.open = true; target?.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" }); target?.querySelector('summary')?.focus({ preventScroll: true }); }}>{part}</button> : part)}</div>
              {(answer.warnings.length > 0 || answer.partial_reasons.length > 0) && <div className="comparison-limitations"><h4><AlertCircle size={15} />Needs attention</h4><ul>{[...new Set([...answer.warnings.map(warning => warning.message), ...answer.partial_reasons])].map((reason, index) => <li key={index}>{reason.includes(" ") ? reason : humanize(reason)}</li>)}</ul></div>}
              <div className="comparison-answer-actions"><button className="text-button" onClick={() => onAnswer(office, answer.answer_id)}>Open answer<ArrowRight size={14} /></button><button className="text-button" onClick={() => onVerify(office, answer.answer_id)}><Shield size={15} />Verify evidence</button></div>
              <div className="comparison-citations"><h4><BookOpen size={15} />Supporting evidence <span>{answer.citations.length}</span></h4>{!answer.citations.length && <p className="question-help">No citations; this answer cannot establish a policy requirement.</p>}{answer.citations.map((item, index) => <details className="comparison-citation" id={answer.citations.findIndex(c => c.statement_id === item.statement_id) === index ? `compare-${office}-${item.statement_id}` : undefined} key={index}><summary><span className="comparison-statement">{item.statement_id}</span><span>{sourceTitle({ source_identity: item.source_identity })}<small>{humanize(item.authority)} · Page {item.page}{item.section ? ` · § ${item.section}` : ""}</small></span><span className="source-version">{item.source_version_label}</span></summary><div>{item.quote ? <blockquote>{item.quote}</blockquote> : <p className="question-help">The passage is not disclosed.</p>}{item.remote ? <p className="question-help"><LockKeyhole size={13} />The original stays in its originating office.</p> : <button className="text-button" onClick={() => navigate({ document: item.source_id, compareSourceOffice: office, compareCitation: String(index), page: item.page, zoom: 100 }, false)}><FileText size={14} />Inspect source<ArrowRight size={14} /></button>}</div></details>)}</div>
              <p className="comparison-saved-at"><Clock3 size={13} />Saved {date(answer.created_at, true)}</p>
            </>}
          </article>;
        })}</div>
      </section> : <section ref={resultSection} className="comparison-results" tabIndex={-1} aria-label="Signed-rule result">
        {ruleBusy ? <Loading label="Verifying signed exports and comparing approved rules…" /> : view.compareRequest && !receipt ? receiptRead.error ? <ErrorState title="Comparison unavailable" error={receiptRead.error} retry={receiptRead.retry} /> : <Loading label="Opening saved comparison…" /> : !receipt ? <EmptyState icon={<Network size={27} />} title="No signed-rule check yet">Run an explicit check to exchange approved rules. Source files remain in their own office.</EmptyState> : <>
          <div className="comparison-result-heading"><div className="comparison-office-heading"><span className={`badge ${coverage?.partial || coverage?.warnings.length ? "comparison-attention" : ""}`}>{coverage?.partial || coverage?.warnings.length ? <AlertCircle size={13} /> : <ShieldCheck size={13} />}{coverage?.partial ? "Incomplete comparison" : coverage?.warnings.length ? "Review findings" : "Comparison returned"}</span><span className="question-help">{date(receipt.federated_answer.generated_at, true)}</span></div><h2>{receipt.question}</h2><p>{humanize(receipt.query.target.subject)} · Origin: {humanize(receipt.query.target.origin_office || "")} {receipt.query.target.processing_office ? `· Processing: ${humanize(receipt.query.target.processing_office)}` : `· USD ${((receipt.query.target.amount_minor || 0) / 100).toLocaleString()}`} · Policy date: {date(receipt.query.valid_at, true)} · {receipt.query.known_at ? `Known by ${date(receipt.query.known_at, true)}` : "Latest knowledge at execution"}</p></div>
          <div className="comparison-verdict">{receipt.federated_answer.comparison ? <p>{receipt.federated_answer.comparison.answer.answer_text}</p> : receipt.federated_answer.statements?.length ? receipt.federated_answer.statements.map(statement => <p key={statement.statement_id}>{statement.text}</p>) : <p>No supported conclusion was established.</p>}</div>
          {(coverage?.partial || !!coverage?.warnings.length) && <div className="comparison-limitations"><h3><AlertCircle size={17} />What needs attention</h3>{coverage?.partial && <p>The result does not cover all requested evidence. Withheld, missing or unavailable rules cannot establish agreement.</p>}<ul>{coverage?.warnings.map((warning, index) => <li key={index}>{warning.message}</li>)}{receipt.federated_answer.comparison?.answer.partial_reasons.map((reason, index) => <li key={`partial-${index}`}>{reason.includes(" ") ? reason : humanize(reason)}</li>)}</ul></div>}
          <div className="comparison-columns">{receipt.federated_answer.offices.map(office => <Delivery key={office.region} office={office} />)}{receipt.federated_answer.comparator_region && <article className="comparison-delivery"><div className="comparison-office-heading"><h3><Globe2 size={17} />{humanize(receipt.federated_answer.comparator_region.toLowerCase())}</h3><span className="badge"><Network size={13} />Comparing office</span></div><p>Compared its own policy with the signed origin export.</p><p className="question-help">Import: {receipt.federated_answer.import?.accepted ? "Accepted" : "Not accepted"}{receipt.federated_answer.import?.received_at ? ` · ${date(receipt.federated_answer.import.received_at, true)}` : ""}</p>{receipt.federated_answer.comparison && <button className="text-button" onClick={() => onVerify(receipt.federated_answer.comparator_region!.toLowerCase() as Office, receipt.federated_answer.comparison!.local_answer_id)}><Shield size={15} />Verify at this office<ArrowRight size={14} /></button>}</article>}</div>
          {!!receipt.federated_answer.contributions?.length && <section className="comparison-rule-list"><h3>Exported requirements</h3>{receipt.federated_answer.contributions.map(item => <div key={`${item.origin_region}/${item.revision_id}`}><span className="badge"><Globe2 size={13} />{humanize(item.origin_region)}</span><strong>{item.rule_summary}</strong><span>{humanize(item.authority)}</span><details className="comparison-proof"><summary>Provenance reference</summary><code>{item.source_ref}<br />{item.manifest_root}</code></details></div>)}</section>}
          <details className="question-details"><summary>Exchange and verification scope</summary><p>{receipt.gateway_note}</p><p>This is a saved gateway receipt. Export signatures were checked during execution; reopening this view does not rerun those checks.</p><p>{receipt.federated_answer.no_raw_source_text_transferred ? "The gateway reports no raw source text in this structured exchange." : "No raw-text transfer assurance was returned."} This does not describe hosted-model traffic.</p><p>Not checked: {receipt.federated_answer.not_checked.map(humanize).join(", ") || "None reported"}. Signatures authenticate exported records; they do not prove policy interpretation.</p><code>{receipt.request_id}</code></details>
        </>}
      </section>}
    </div>
    {view.document && <DocumentDialog key={`${evidenceOffice}/${view.document}`} office={evidenceOffice} sourceId={view.document} view={view} navigate={navigate} evidence={evidence ? { source_id: evidence.source_id, page: evidence.page, section: evidence.section, quote: evidence.quote || "" } : undefined} onClose={() => navigate({ document: "", compareCitation: "" })} />}
    {sharing && <Modal title="Share cross-office view" onClose={() => setSharing(false)}><div className="dialog-body"><p className="dialog-description">The link opens the saved office answers or gateway receipt, without submitting again. Recipients need the same office access. Drafts, unsaved failures and source files are not included.</p><label className="question-field">View link<input readOnly value={window.location.href} onFocus={event => event.currentTarget.select()} /></label><button className={`button secondary question-copy copy-${copied}`} onClick={copyLink} title={copied === "copied" ? "Copied" : copied === "failed" ? "Copy failed; select the link and copy manually" : "Copy link"}>{copied === "copied" ? <Check size={16} /> : copied === "failed" ? <AlertCircle size={16} /> : <Copy size={16} />}Copy link</button><span className="sr-only" role="status">{copied === "copied" ? "Link copied" : copied === "failed" ? "Copy failed. Select the link and copy it manually." : ""}</span></div></Modal>}
  </div>;
}
