import { useEffect, useRef, useState, type FormEvent, type ChangeEvent } from "react";
import { AlertCircle, ArrowRight, Braces, Check, CircleDot, ClipboardCheck, Copy, FileCheck2, FileText, Info, Keyboard, Link, LoaderCircle, Network, Search, ShieldCheck, X } from "lucide-react";
import { api, getFinding } from "./api";
import { EmptyState, ErrorState, Loading, Modal, ShortcutHint } from "./components";
import Select from "./Select";
import Lineage from "./Lineage";
import VerificationExports from "./VerificationTools";
import { DocumentDialog } from "./Sources";
import { date, findingTag, findingTitle, humanize, sourceTitle } from "./presentation";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import { useVerificationData } from "./useVerificationData";
import { bundleLineage, checkCounts, checkSummary, focusedLineage, lineageNodes, checkLabels, checkStatusLabels, evidenceFileError, jsonObject, lineageGroups, parseEvidenceBundle } from "./verification";
import type { Finding, LineageGraph, Office, Source, StoredAnswer, RecentAnswer, VerificationReport } from "./types";
import type { View } from "./viewState";
import "./verification.css";

type Context = { source?: Source; finding?: Finding; answer?: StoredAnswer["answer"] };
const kinds = [{ value: "source", label: "Source copy" }, { value: "finding", label: "Finding" }, { value: "answer", label: "Saved answer" }, { value: "bundle", label: "Uploaded bundle" }];

export default function Verification({ office, view, navigate, shortcutsEnabled, onHelp, onFinding }: {
  office: Office; view: View; navigate: (patch: Partial<View>, replace?: boolean) => void;
  shortcutsEnabled: boolean; onHelp: () => void; onFinding: (id: string) => void;
}) {
  const key = `${office}/${view.verifyKind}/${view.verifyId}`;
  const base = `${office}/${view.verifyKind === "source" ? "sources" : view.verifyKind === "finding" ? "findings" : "answers"}/${encodeURIComponent(view.verifyId)}`;
  const recordKey = view.verifyId && view.verifyKind !== "bundle" ? key : "";
  const sources = useVerificationData(`${office}/sources`, signal => api<{ sources: Source[] }>(`${office}/sources`, { signal }));
  const findings = useVerificationData(`${office}/findings`, signal => api<{ findings: Finding[] }>(`${office}/findings`, { signal }));
  const answers = useVerificationData(view.verifyKind === "answer" ? `${office}/answers` : "", signal => api<{ answers: RecentAnswer[]; has_more: boolean }>(`${office}/answers`, { signal }));
  const record = useVerificationData<Context>(recordKey, signal => view.verifyKind === "finding" ? getFinding(office, view.verifyId, signal) : api<Context>(base, { signal }));
  const trace = useVerificationData(recordKey, signal => api<{ lineage: LineageGraph }>(`${base}/lineage`, { signal }));
  const bundle = useVerificationData(recordKey && view.verifyKind === "answer" ? key : "", signal => api<{ bundle: Record<string, unknown> }>(`${base}/bundle`, { signal }));
  const current = record.data;
  const [answerDraft, setAnswerDraft] = useState(view.verifyKind === "answer" ? view.verifyId : "");
  const [fileValue, setFile] = useState<File | null>(null);
  const [fileErrorValue, setFileError] = useState("");
  const [readingValue, setReading] = useState(false);
  const [importedValue, setImported] = useState<Record<string, unknown> | null>(null);
  const [reportValue, setReport] = useState<VerificationReport | null>(null);
  const [checkErrorValue, setCheckError] = useState("");
  const [checkingValue, setChecking] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const [tagCopy, setTagCopy] = useState<"idle" | "copied" | "failed">("idle");
  const form = useRef<HTMLFormElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const answerPicker = useRef<HTMLButtonElement>(null);
  const shareTrigger = useRef<HTMLButtonElement>(null);
  const lineage = useRef<HTMLElement>(null);
  const verificationRequest = useRef<AbortController | null>(null);
  const fileGeneration = useRef(0);
  const traceReturnScroll = useRef(0);
  const keyboardNodeFocus = useRef(false);
  const evidenceKey = useRef(key);
  const sameEvidence = evidenceKey.current === key;
  const file = sameEvidence ? fileValue : null;
  const fileError = sameEvidence ? fileErrorValue : "";
  const imported = sameEvidence ? importedValue : null;
  const report = sameEvidence ? reportValue : null;
  const checkError = sameEvidence ? checkErrorValue : "";
  const reading = sameEvidence && readingValue;
  const checking = sameEvidence && checkingValue;
  const rawGraph = view.verifyKind === "bundle" ? (imported ? bundleLineage(imported) : null) : trace.data?.lineage;
  const availableGraph = rawGraph ? { ...rawGraph, nodes: rawGraph.nodes.map(node => {
    if (view.verifyKind === "bundle") return node;
    const finding = node.node_type === "finding" ? findings.data?.findings.find(item => `finding:${item.finding_id}` === node.node_id) : null;
    return finding ? { ...node, label: findingTitle(finding) } : node;
  }) } : null;
  const focusedGraph = availableGraph ? focusedLineage(availableGraph) : null;
  const graph = view.verifyScope === "related" ? availableGraph : focusedGraph;
  const selectedId = view.verifyNode || graph?.root_id;
  const inspectedPassage = availableGraph?.nodes.find(node => node.node_id === view.verifyPassage);
  const signedBundle = bundle.data?.bundle;
  const canCheck = view.verifyKind === "source" ? !!current?.source && !!file && !fileError : view.verifyKind === "answer" ? !!signedBundle : view.verifyKind === "bundle" ? !!imported && !fileError : false;

  useEffect(() => {
    evidenceKey.current = key;
    verificationRequest.current?.abort(); fileGeneration.current++;
    setFile(null); setFileError(""); setImported(null); setReport(null); setCheckError(""); setChecking(false); setReading(false); setTagCopy("idle");
    if (input.current) input.current.value = "";
    if (view.verifyKind === "answer") setAnswerDraft(view.verifyId);
    return () => { verificationRequest.current?.abort(); fileGeneration.current++; };
  }, [key]);
  useEffect(() => {
    if (copied === "idle" && tagCopy === "idle") return;
    const timer = window.setTimeout(() => { setCopied("idle"); setTagCopy("idle"); }, 1800);
    return () => window.clearTimeout(timer);
  }, [copied, tagCopy]);
  useEffect(() => {
    if (view.verifyNode && availableGraph?.nodes.some(node => node.node_id === view.verifyNode) && !focusedGraph?.nodes.some(node => node.node_id === view.verifyNode) && view.verifyScope === "focused")
      navigate({ verifyScope: "related" }, true);
  }, [key, view.verifyNode, availableGraph?.nodes.length]);

  function choose(kind: View["verifyKind"], id = "", task = view.verifyTab) {
    navigate({ verifyKind: kind, verifyId: id, verifyTab: task, verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "", page: 1, zoom: 100 }, false);
  }
  function selectNode(id: string) {
    if (view.verifyPane === "browse") traceReturnScroll.current = window.scrollY;
    const node = graph?.nodes.find(item => item.node_id === id);
    navigate({ verifyNode: id, verifyPane: "detail", verifyGroup: lineageGroups.find(group => group.types.includes(node?.node_type || ""))?.label || "" }, true);
  }
  function switchTask(task: View["verifyTab"]) { navigate({ verifyTab: task }); }
  function focusTask(task: View["verifyTab"]) {
    switchTask(task);
    requestAnimationFrame(() => { const tab = document.getElementById(`verification-tab-${task}`); tab?.setAttribute("data-shortcut-focus", "true"); tab?.focus(); });
  }
  function moveNode(direction: number) {
    if (!graph || view.verifyTab !== "trace") return;
    const nodes = lineageNodes(graph, view.verifySearch);
    const next = nodes[Math.max(0, Math.min(nodes.length - 1, nodes.findIndex(node => node.node_id === selectedId) + direction))];
    if (!next) return;
    keyboardNodeFocus.current = true; selectNode(next.node_id);
  }
  useKeyboardShortcuts(shortcutsEnabled, {
    search: () => { navigate({ verifyTab: "trace", verifyPane: "browse" }); requestAnimationFrame(() => { search.current?.focus(); search.current?.select(); }); },
    verify: () => { if (canCheck && !checking && !reading) { switchTask("check"); requestAnimationFrame(() => form.current?.requestSubmit()); } },
    lineage: () => focusTask("trace"),
    integrity: () => focusTask("check"),
    share: () => { shareTrigger.current?.focus(); setSharing(true); },
    next: () => moveNode(1), previous: () => moveNode(-1),
  });
  async function chooseFile(chosen: File | null) {
    const generation = ++fileGeneration.current;
    verificationRequest.current?.abort(); setChecking(false); setReport(null); setCheckError(""); setImported(null); setFile(chosen); setReading(false);
    if (view.verifyKind === "bundle") navigate({ verifyNode: "", verifyChecks: "all", verifyScope: "focused", verifyGroup: "", verifyPane: "browse" }, true);
    if (!chosen) { setFileError(""); return; }
    const error = evidenceFileError(chosen); setFileError(error);
    if (error || view.verifyKind !== "bundle") return;
    setReading(true);
    try { const parsed = parseEvidenceBundle(await chosen.text()); if (generation === fileGeneration.current) setImported(parsed); }
    catch (error) { if (generation === fileGeneration.current) setFileError((error as Error).message); }
    finally { if (generation === fileGeneration.current) setReading(false); }
  }
  async function verify(event: FormEvent) {
    event.preventDefault(); if (!canCheck || checking || reading) return;
    const controller = new AbortController(); verificationRequest.current?.abort(); verificationRequest.current = controller;
    setChecking(true); setCheckError(""); setReport(null);
    try {
      let body: BodyInit;
      if (view.verifyKind === "source") { const data = new FormData(); data.set("source_id", view.verifyId); data.set("file", file!); body = data; }
      else body = JSON.stringify(signedBundle || imported);
      const result = await api<{ report: VerificationReport }>(`${office}/verifications/${view.verifyKind === "source" ? "source" : "bundle"}`, { method: "POST", body, signal: controller.signal });
      if (!controller.signal.aborted) { setReport(result.report); setChecking(false); }
    } catch (error) { if (!controller.signal.aborted) { setCheckError((error as Error).message); setChecking(false); } }
  }
  async function share() {
    try { await navigator.clipboard.writeText(window.location.href); setCopied("copied"); } catch { setCopied("failed"); }
  }
  async function copyTag() {
    if (!current?.finding) return;
    try { await navigator.clipboard.writeText(findingTag(current.finding)); setTagCopy("copied"); } catch { setTagCopy("failed"); }
  }
  const targetRead = view.verifyKind === "source" ? sources : findings;
  const targetOptions = view.verifyKind === "source" ? [...sources.data?.sources || []].sort((a, b) => sourceTitle(a).localeCompare(sourceTitle(b))).map(source => ({ value: source.source_id, label: `${sourceTitle(source)} · ${source.version_label}` })) : (findings.data?.findings || []).map(finding => ({ value: finding.finding_id, label: `${findingTag(finding)} · ${findingTitle(finding)}` }));
  const placeholder = targetRead.loading ? "Loading evidence…" : targetRead.error ? "Evidence list unavailable" : !targetOptions.length ? "No available evidence" : "Choose evidence";
  const bundleAnswer = jsonObject(imported?.answer);
  const title = current?.source ? sourceTitle(current.source) : current?.finding ? findingTitle(current.finding) : current?.answer?.question;
  const filteredAnswers = (answers.data?.answers || []).filter(answer => `${answer.question} ${date(answer.created_at, true)}`.toLowerCase().includes(view.verifyAnswerSearch.trim().toLowerCase()));
  const answerOptions = filteredAnswers.map(answer => ({ value: answer.answer_id, label: `${answer.question} · ${date(answer.created_at, true)}` }));
  const exportItems = [
    ...(report ? [{ label: "Verification report", filename: "verification-report.json", value: report }] : []),
    ...(graph ? [{ label: view.verifyKind === "bundle" ? "Supplied evidence trace" : view.verifyScope === "focused" ? "Focused evidence trace" : "Related evidence trace", filename: "evidence-lineage.json", value: graph }] : []),
    ...(signedBundle ? [{ label: "Signed answer bundle", filename: `evidence-${view.verifyId}.json`, value: signedBundle }] : []),
  ];
  const hasTarget = !!recordKey || view.verifyKind === "bundle";

  function emptyEvidence() {
    const read = view.verifyKind === "answer" ? answers : targetRead;
    if (read.loading) return <Loading label="Loading available evidence…" />;
    if (read.error) return null;
    const count = view.verifyKind === "answer" ? answers.data?.answers.length : targetOptions.length;
    return <EmptyState title={count ? "Choose evidence" : "No evidence available"} icon={<FileText size={25} />}>
      {count ? "Select the intended evidence above." : view.verifyKind === "source" ? "Add a source in Sources before comparing a copy." : view.verifyKind === "finding" ? "There are no findings available to your office." : "There are no saved answers available to your office. You can check an exported answer bundle instead."}
      {view.verifyKind === "answer" && !count && <button className="button secondary" onClick={() => choose("bundle", "", "check")}>Choose a bundle<ArrowRight size={15} /></button>}
    </EmptyState>;
  }

  const fileControl = <>
    <input ref={input} type="file" id="verification-file" className="sr-only" tabIndex={-1} accept={view.verifyKind === "bundle" ? ".json,application/json" : current?.source?.source_type === "pdf" ? ".pdf,application/pdf" : ".json,application/json"} onChange={(event: ChangeEvent<HTMLInputElement>) => void chooseFile(event.target.files?.[0] || null)} />
    <div className={`evidence-file ${file ? "has-file" : ""}`}>
      <button type="button" onClick={() => input.current?.click()} aria-label={view.verifyKind === "bundle" ? "Choose evidence bundle" : "Choose source copy"} aria-describedby="verification-file-help" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); void chooseFile(event.dataTransfer.files[0] || null); }}>
        {view.verifyKind === "bundle" ? <Braces size={23} /> : <FileText size={23} />}<span><strong title={file?.name}>{file?.name || (view.verifyKind === "bundle" ? "Choose a JSON bundle" : "Choose a source copy")}</strong><span>{file ? `${new Intl.NumberFormat().format(Math.ceil(file.size / 1024))} KB · Click to change` : "Click or drop a file · up to 20 MB"}</span></span>
      </button>
      {file && <button type="button" className="icon-button" aria-label="Remove selected file" onClick={() => { if (input.current) input.current.value = ""; void chooseFile(null); }}><X size={16} /></button>}
    </div>
    {file && !fileError && <p className="verification-file-state"><CircleDot size={13} />{reading ? "Reading bundle…" : checking ? "Check in progress" : report ? "Checks completed — see results below" : "Selected · not checked"}</p>}
    <p className="verification-help" id="verification-file-help">{view.verifyKind === "bundle" ? "Choose an exported answer evidence bundle." : "Choose the PDF or saved message file you want to compare."}</p>
    {fileError && <p className="verification-inline-error" role="alert"><AlertCircle size={15} />{fileError}</p>}
  </>;

  return <div className="verification-workspace">
    <div className="page-heading"><h1>Verification</h1><div className="page-actions">
      <button className="button secondary shortcuts-button" aria-label="Keyboard shortcuts" onClick={onHelp} aria-keyshortcuts="F1"><Keyboard size={16} />Shortcuts<ShortcutHint>F1</ShortcutHint></button>
      <VerificationExports items={exportItems} shortcutsEnabled={shortcutsEnabled} />
      <button ref={shareTrigger} className="button secondary verification-share" aria-label="Share view" aria-keyshortcuts={shortcutsEnabled ? "Shift+S" : undefined} onClick={() => setSharing(true)}><Link size={15} />Share view{shortcutsEnabled && <ShortcutHint>Shift+S</ShortcutHint>}</button>
    </div></div>
    <div className="detail-tabs verification-task-tabs" role="tablist" aria-label="Verification task">
      {([ ["check", "Check integrity", ShieldCheck], ["trace", "Trace evidence", Network] ] as const).map(([task, label, Icon], index) => <button key={task} id={`verification-tab-${task}`} role="tab" aria-selected={view.verifyTab === task} aria-controls={`verification-panel-${task}`} tabIndex={view.verifyTab === task ? 0 : -1} aria-keyshortcuts={shortcutsEnabled ? task === "trace" ? "L" : "I" : undefined} onBlur={event => { delete event.currentTarget.dataset.shortcutFocus; }} onPointerDown={event => { delete event.currentTarget.dataset.shortcutFocus; }} onClick={() => switchTask(task)} onKeyDown={event => {
        delete event.currentTarget.dataset.shortcutFocus;
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); const next = event.key === "Home" ? "check" : event.key === "End" ? "trace" : index === 0 ? "trace" : "check";
        switchTask(next); document.getElementById(`verification-tab-${next}`)?.focus();
      }}><Icon size={16} />{label}{shortcutsEnabled && <ShortcutHint>{task === "trace" ? "L" : "I"}</ShortcutHint>}</button>)}
    </div>
    <section className="verification-target" aria-label="Choose evidence">
      <div className="verification-target-kind"><label>Evidence type</label><Select label="Evidence type" value={view.verifyKind} options={kinds} onChange={value => choose(value as View["verifyKind"], "", value === "finding" ? "trace" : view.verifyTab)} icon={<ClipboardCheck size={16} />} /></div>
      {["source", "finding"].includes(view.verifyKind) ? <div className="verification-target-record"><label>{view.verifyKind === "source" ? "Source" : "Finding"}</label>
        <Select label={view.verifyKind === "source" ? "Source to verify" : "Finding to trace"} value={view.verifyId} options={targetOptions.some(option => option.value === view.verifyId) ? targetOptions : [{ value: view.verifyId, label: view.verifyId ? title || "Selected evidence" : placeholder }, ...targetOptions]} onChange={value => choose(view.verifyKind, value)} />
        {targetRead.error && <ReadError title="Evidence list unavailable" error={targetRead.error} retry={targetRead.retry} />}
        {!targetRead.loading && !targetRead.error && !targetOptions.length && <p className="verification-help">No {view.verifyKind === "source" ? "sources" : "findings"} are available to your office.</p>}
      </div> : view.verifyKind === "answer" ? <div className="verification-answer-picker">
        <label htmlFor="saved-answer-search">Find a saved answer</label><label className="search-input"><Search size={16} /><input id="saved-answer-search" aria-label="Find saved answers" placeholder="Search by question or date" onKeyDown={event => { if (event.key === "Escape" && !event.nativeEvent.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) { event.preventDefault(); answerPicker.current?.focus(); } }} value={view.verifyAnswerSearch} onChange={event => navigate({ verifyAnswerSearch: event.target.value }, true)} /></label>
        <Select label="Saved answer" triggerRef={answerPicker} value={view.verifyId} options={answerOptions.some(option => option.value === view.verifyId) ? answerOptions : [{ value: view.verifyId, label: current?.answer?.question || (answers.loading ? "Loading saved answers…" : answers.error ? "Answer list unavailable" : "Choose a saved answer") }, ...answerOptions]} onChange={id => { if (id) choose("answer", id); }} />
        {answers.error ? <ReadError title="Answer list unavailable" error={answers.error} retry={answers.retry} /> : !answers.loading && !filteredAnswers.length && <p className="verification-help">{answers.data?.answers.length ? "No questions match this search." : "No saved answers are available to your office."}</p>}
        {answers.data?.has_more && <p className="verification-help">Showing the latest 50 available answers. Older answers can be opened by ID.</p>}
        <details className="verification-answer-advanced"><summary>Open by answer ID</summary><form onSubmit={event => { event.preventDefault(); if (answerDraft.trim()) choose("answer", answerDraft.trim()); }}><label htmlFor="answer-id" className="sr-only">Answer ID</label><input id="answer-id" placeholder="ans_…" value={answerDraft} onChange={event => setAnswerDraft(event.target.value)} required /><button className="button secondary">Open answer<ArrowRight size={15} /></button></form></details>
      </div> : <p className="verification-target-note"><Braces size={18} />Choose a bundle below to check or explore it.</p>}
    </section>
    {record.error && !current ? <ErrorState title="Evidence unavailable" error={record.error} retry={record.retry} /> : recordKey && !current ? <Loading label="Opening selected evidence…" /> : <>
      {title && !(current?.source && view.verifyTab === "check") && <section className="verification-record-heading"><div><h2>{title}</h2><div>
        {current?.source && <><span className="source-version">{current.source.version_label}</span><span>{humanize(current.source.authority)}</span></>}
        {current?.finding && <><button className={`verification-finding-tag copy-${tagCopy}`} title={tagCopy === "copied" ? "Tag copied" : tagCopy === "failed" ? "Could not copy tag" : "Copy finding tag"} aria-label={`Copy finding tag ${findingTag(current.finding)}`} onClick={() => void copyTag()}>{findingTag(current.finding)}{tagCopy === "copied" ? <Check size={13} /> : tagCopy === "failed" ? <AlertCircle size={13} /> : <Copy size={13} />}</button><span className="sr-only" role="status">{tagCopy === "copied" ? "Finding tag copied" : tagCopy === "failed" ? "Could not copy the finding tag" : ""}</span></>}
        {current?.answer && <><span>Saved {date(current.answer.created_at, true)}</span><span>{humanize(current.answer.status)}</span></>}
      </div></div>{current?.source && <button className="button secondary" onClick={() => navigate({ document: current.source!.source_id, verifyPassage: "", page: 1, zoom: 100 })}><FileText size={15} />Inspect source</button>}{current?.finding && <button className="button secondary" onClick={() => onFinding(current.finding!.finding_id)}>Open finding<ArrowRight size={15} /></button>}</section>}
      {current?.answer && <details className="verification-answer-preview"><summary>Read saved answer</summary><blockquote>{current.answer.answer_text}</blockquote><div className="verification-answer-modes">{Object.entries(current.answer.modes || {}).map(([stage, mode]) => <span key={stage}>{humanize(stage)} · {humanize(mode)}</span>)}</div></details>}
      <div id="verification-panel-check" role="tabpanel" aria-labelledby="verification-tab-check" hidden={view.verifyTab !== "check"}>
        {current?.finding ? <section className="verification-finding-sources"><h2>Choose a source copy to check</h2><p>Finding signatures are not checked here. You can compare copies of the referenced sources.</p><div>{[...new Set(current.finding.evidence.map(item => item.source_id))].map(id => {
          const source = sources.data?.sources.find(s => s.source_id === id);
          return <button className="button secondary" key={id} onClick={() => choose("source", id, "check")}><FileCheck2 size={15} /><span>{source ? sourceTitle(source) : "Referenced source"}</span>{source && <span className="source-version">{source.version_label}</span>}<ArrowRight size={14} /></button>;
        })}</div>{sources.error && <ReadError title="Source names unavailable" error={sources.error} retry={sources.retry} />}</section> : hasTarget ? <>
          <form className="verification-form" ref={form} onSubmit={verify} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); if (canCheck && !checking) event.currentTarget.requestSubmit(); } }}>
            {current?.source ? <><h2 className="verification-section-title">Compare source copies</h2><div className="verification-comparison">
              <section className="verification-original" aria-labelledby="stored-original-title"><h3 id="stored-original-title"><FileText size={17} />Stored original</h3><strong>{sourceTitle(current.source)}</strong><div className="verification-original-meta"><span className="source-version">{current.source.version_label}</span><span>{humanize(current.source.source_type)} · {humanize(current.source.authority)}</span></div><p className="verification-help">Published {date(current.source.publication_time)}</p><button type="button" className="button secondary" onClick={() => navigate({ document: current.source!.source_id, verifyPassage: "", page: 1, zoom: 100 })}><FileText size={15} />Inspect source</button></section>
              <section className="verification-copy" aria-labelledby="your-copy-title"><h3 id="your-copy-title"><Copy size={17} />Your copy</h3>{fileControl}</section>
            </div></> : view.verifyKind === "bundle" ? <section className="verification-bundle-input"><h2 className="verification-section-title">Check an evidence bundle</h2>{fileControl}</section> : <><h2 className="verification-section-title">Check this saved answer</h2>{bundle.loading && !signedBundle && <Loading label="Loading signed answer bundle…" />}{bundle.error && <ReadError title="Signed bundle unavailable" error={bundle.error} retry={bundle.retry} />}</>}
            <div className="verification-submit"><button className="button primary" disabled={!canCheck || checking || reading} aria-keyshortcuts={shortcutsEnabled ? "V Control+Enter Meta+Enter" : "Control+Enter Meta+Enter"}>{checking || reading ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />}{checking ? "Checking…" : reading ? "Reading…" : "Run verification"}{shortcutsEnabled && <ShortcutHint>V</ShortcutHint>}</button><span className="verification-help">{view.verifyKind === "source" ? "The stored original stays unchanged." : "No source data is changed."}</span></div>
            {checkError && <ReadError title="Verification could not finish" error={checkError} />}
          </form>
          {checking && <p className="verification-progress" role="status"><LoaderCircle className="spin" size={17} />Checking integrity… You can explore the trace while this runs.</p>}
          {report && <section className="verification-results-panel" aria-labelledby="verification-results-title"><h2 id="verification-results-title">Check results</h2><CheckResults report={report} filter={view.verifyChecks} onFilter={value => navigate({ verifyChecks: value }, true)} /></section>}
          {!report && !checking && <p className="verification-unchecked"><CircleDot size={15} />No checks run yet.</p>}
          {imported && <details className="verification-answer-preview"><summary>Read supplied answer</summary><h3>{typeof bundleAnswer.question === "string" ? bundleAnswer.question : "Question not recorded"}</h3><blockquote>{typeof bundleAnswer.answer_text === "string" ? bundleAnswer.answer_text : "Answer text not recorded"}</blockquote></details>}
          <details className="verification-scope"><summary><Info size={14} />What these checks cover</summary><p>{view.verifyKind === "source" ? "Source-copy checks compare file bytes, extracted text and passages against stored commitments. They do not verify manifest or finding signatures." : "Answer checks verify signatures and evidence bindings against the office’s pinned public keys. Passage proofs require disclosed evidence."} Integrity checks do not establish that a policy or interpretation is correct.</p></details>
        </> : emptyEvidence()}
      </div>
      <div id="verification-panel-trace" role="tabpanel" aria-labelledby="verification-tab-trace" hidden={view.verifyTab !== "trace"}>
        {view.verifyKind !== "bundle" && trace.error ? <ReadError title="Evidence trace unavailable" error={trace.error} retry={trace.retry} /> : view.verifyKind !== "bundle" && trace.loading && !graph ? <Loading label="Loading evidence trace…" /> : graph ? <section className={`verification-lineage pane-${view.verifyPane}`} ref={lineage} id="evidence-lineage" tabIndex={-1} aria-labelledby="evidence-lineage-title">
          <div className="verification-lineage-header"><h2 id="evidence-lineage-title">{view.verifyScope === "focused" ? "Selected evidence" : "Related evidence"}</h2></div>
          <div className="lineage-toolbar"><label className="search-input"><Search size={16} /><span className="sr-only">Search lineage</span><input ref={search} aria-label="Search lineage" placeholder="Search evidence or passages…" value={view.verifySearch} onChange={event => navigate({ verifySearch: event.target.value }, true)} onKeyDown={event => { if (event.key === "Escape" && !event.nativeEvent.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) { event.preventDefault(); lineage.current?.focus({ preventScroll: true }); } }} />{view.verifySearch ? <button className="icon-button" aria-label="Clear lineage search" onClick={() => navigate({ verifySearch: "" }, true)}><X size={14} /></button> : shortcutsEnabled && <ShortcutHint>/</ShortcutHint>}</label><span>{graph.nodes.length} records{shortcutsEnabled && <span className="lineage-navigation-hint"><ShortcutHint>J</ShortcutHint><ShortcutHint>K</ShortcutHint></span>}</span></div>
          <div className="lineage-scope-control"><button className="button secondary" aria-pressed={view.verifyScope === "related"} onClick={() => navigate({ verifyScope: view.verifyScope === "focused" ? "related" : "focused", verifyNode: "", verifyGroup: "", verifyPane: "browse" }, true)}>{view.verifyScope === "focused" ? "Show related evidence" : "Return to focused trace"}<ArrowRight size={14} /></button>{view.verifyScope === "focused" && availableGraph && <span>{Math.max(0, availableGraph.nodes.length - graph.nodes.length)} related records outside this trace</span>}</div>
          <Lineage graph={graph} nodeId={view.verifyNode} search={view.verifySearch} group={view.verifyGroup} pane={view.verifyPane} returnScroll={traceReturnScroll} keyboardFocus={keyboardNodeFocus} onGroup={group => navigate({ verifyGroup: group }, true)} onBack={() => navigate({ verifyPane: "browse" }, true)} onSelect={selectNode} supplied={view.verifyKind === "bundle"} onInspect={node => navigate({ document: node.attributes.source_id, verifyPassage: node.node_id, page: Math.max(1, Number(node.attributes.page) || 1), zoom: 100 })} onCheckSource={id => choose("source", id, "check")} onFinding={onFinding} />
          <p className="verification-help">Connections show recorded evidence, not an integrity result.</p>
        </section> : view.verifyKind !== "bundle" ? emptyEvidence() : <div className="verification-trace-empty"><Network size={24} /><p>{view.verifyKind === "bundle" ? "Choose a bundle in Check integrity to explore its supplied evidence." : "Choose evidence above to trace its statements, passages and sources."}</p>{view.verifyKind === "bundle" && <button className="button secondary" onClick={() => switchTask("check")}>Choose a bundle<ArrowRight size={15} /></button>}</div>}
      </div>
    </>}
    {sharing && <Modal title="Share view" onClose={() => setSharing(false)} className="verification-share-dialog"><div className="dialog-body"><p>This link opens the same office, evidence, filters and selected record.</p><p className="verification-share-limit"><Info size={16} />Local files and verification results are not included. Export the report to keep or share the completed checks.</p><label htmlFor="verification-share-url">View link</label><input id="verification-share-url" readOnly value={window.location.href} onFocus={event => event.currentTarget.select()} /><button className={`button primary copy-${copied}`} title={copied === "copied" ? "Link copied" : copied === "failed" ? "Could not copy; select the link and copy it manually" : "Copy view link"} onClick={() => void share()}>{copied === "copied" ? <Check size={15} /> : copied === "failed" ? <AlertCircle size={15} /> : <Copy size={15} />}Copy link</button><span className="sr-only" role="status">{copied === "copied" ? "View link copied" : copied === "failed" ? "Could not copy the view link" : ""}</span></div></Modal>}
    {view.document && <DocumentDialog office={office} sourceId={view.document} view={view} navigate={navigate} onClose={() => navigate({ document: "", verifyPassage: "" })} onVerify={id => choose("source", id, "check")} evidence={inspectedPassage?.attributes.source_id === view.document && inspectedPassage.attributes.quote ? { source_id: view.document, quote: inspectedPassage.attributes.quote, page: Math.max(1, Number(inspectedPassage.attributes.page) || 1), section: inspectedPassage.attributes.section || null } : undefined} />}
  </div>;
}

function ReadError({ title, error, retry }: { title: string; error: string; retry?: () => void }) {
  return <div className="verification-read-error" role="alert"><AlertCircle size={17} /><div><strong>{title}</strong><p>{error}</p>{retry && <button type="button" className="text-button" onClick={retry}>Retry</button>}</div></div>;
}
function CheckResults({ report, filter, onFilter }: { report: VerificationReport; filter: View["verifyChecks"]; onFilter: (value: View["verifyChecks"]) => void }) {
  const counts = checkCounts(report), summary = checkSummary(report), order = { failed: 0, not_checked: 1, passed: 2 };
  const checks = report.checks.filter(check => filter === "all" || check.status === filter).sort((a, b) => order[a.status] - order[b.status]);
  return <>
    <div className={`verification-result-summary summary-${summary.tone}`} role="status"><h3>{summary.tone === "failed" ? <AlertCircle size={20} /> : summary.tone === "passed" ? <Check size={20} /> : <CircleDot size={20} />}{summary.title}</h3><p>{summary.next}</p></div>
    <div className="verification-counts" aria-label="Verification result counts">{(["passed", "failed", "not_checked"] as const).map(status => { const Icon = status === "passed" ? Check : status === "failed" ? AlertCircle : CircleDot; return <div className={`check-count check-${status} ${counts[status] ? "" : "check-empty"}`} key={status}><Icon size={15} /><strong>{counts[status]}</strong><span>{checkStatusLabels[status]}</span></div>; })}</div>
    <div className="verification-report-toolbar"><Select label="Filter checks" value={filter} options={[{ value: "all", label: "All checks" }, ...Object.entries(checkStatusLabels).map(([value, label]) => ({ value, label }))]} onChange={value => onFilter(value as View["verifyChecks"])} /></div>
    <ul className="verification-check-list">{checks.map((check, index) => { const Icon = check.status === "passed" ? Check : check.status === "failed" ? AlertCircle : CircleDot; const skipped = Number(check.detail?.skipped_not_disclosed || check.detail?.not_supplied || 0); return <li key={`${check.check}-${index}`}><div><strong>{checkLabels[check.check] || humanize(check.check)}</strong><span className={`check-badge check-${check.status}`}><Icon size={13} />{checkStatusLabels[check.status]}</span></div>{check.reason && <p>{check.reason}</p>}{skipped > 0 && <p className="check-undisclosed"><CircleDot size={13} />{skipped} undisclosed {skipped === 1 ? "passage or reference was" : "passages or references were"} not checked.</p>}{Object.keys(check.detail || {}).length > 0 && <details><summary>Check details</summary><dl>{Object.entries(check.detail).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value}</dd></div>)}</dl></details>}</li>; })}</ul>
    {!checks.length && <p className="verification-help">No {filter === "all" ? "checks were returned" : `${checkStatusLabels[filter].toLowerCase()} checks in this result`}.</p>}
    {report.generated_at && <p className="verification-report-date">Checked {date(report.generated_at, true)}</p>}
  </>;
}
