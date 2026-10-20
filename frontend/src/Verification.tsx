import { useEffect, useRef, useState, type FormEvent, type ChangeEvent } from "react";
import { AlertCircle, ArrowDownToLine, ArrowRight, Braces, Check, CircleDot, ClipboardCheck, Copy, FileCheck2, FileText, Keyboard, Link, LoaderCircle, Network, Search, ShieldCheck, X } from "lucide-react";
import { api, getFinding } from "./api";
import { EmptyState, ErrorState, Loading, ShortcutHint } from "./components";
import Select from "./Select";
import Lineage from "./Lineage";
import { DocumentDialog } from "./Sources";
import { date, findingTag, findingTitle, humanize, sourceTitle } from "./presentation";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import { bundleLineage, checkCounts, checkSummary, focusedLineage, lineageNodes, checkLabels, checkStatusLabels, downloadJson, evidenceFileError, jsonObject, lineageGroups, parseEvidenceBundle } from "./verification";
import type { Finding, LineageGraph, Office, Source, StoredAnswer, VerificationReport } from "./types";
import type { View } from "./viewState";
import "./verification.css";

type Context = { key: string; graph: LineageGraph; source?: Source; finding?: Finding; answer?: StoredAnswer["answer"]; bundle?: Record<string, unknown> };
const kinds = [{ value: "source", label: "Source copy" }, { value: "finding", label: "Finding lineage" }, { value: "answer", label: "Stored answer" }, { value: "bundle", label: "Uploaded bundle" }];

export default function Verification({ office, view, navigate, shortcutsEnabled, onHelp, onFinding }: {
  office: Office; view: View; navigate: (patch: Partial<View>, replace?: boolean) => void;
  shortcutsEnabled: boolean; onHelp: () => void; onFinding: (id: string) => void;
}) {
  const [library, setLibrary] = useState<{ sources: Source[]; findings: Finding[] } | null>(null);
  const [libraryError, setLibraryError] = useState("");
  const [libraryRevision, setLibraryRevision] = useState(0);
  const [context, setContext] = useState<Context | null>(null);
  const [contextError, setContextError] = useState("");
  const [contextRevision, setContextRevision] = useState(0);
  const [answerDraft, setAnswerDraft] = useState(view.verifyKind === "answer" ? view.verifyId : "");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [reading, setReading] = useState(false);
  const [imported, setImported] = useState<Record<string, unknown> | null>(null);
  const [report, setReport] = useState<VerificationReport | null>(null);
  const [checkError, setCheckError] = useState("");
  const [checking, setChecking] = useState(false);
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const [tagCopy, setTagCopy] = useState<"idle" | "copied" | "failed">("idle");
  const form = useRef<HTMLFormElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const lineage = useRef<HTMLElement>(null);
  const selection = useRef<HTMLButtonElement>(null);
  const verificationRequest = useRef<AbortController | null>(null);
  const fileGeneration = useRef(0);
  const traceReturnScroll = useRef(0);
  const keyboardNodeFocus = useRef(false);
  const key = `${office}/${view.verifyKind}/${view.verifyId}`;
  const current = context?.key === key ? context : null;
  const rawGraph = view.verifyKind === "bundle" ? (imported ? bundleLineage(imported) : null) : current?.graph;
  const availableGraph = rawGraph && view.verifyKind !== "bundle" ? { ...rawGraph, nodes: rawGraph.nodes.map(node => {
    const finding = node.node_type === "finding" ? library?.findings.find(item => `finding:${item.finding_id}` === node.node_id) : null;
    return finding ? { ...node, label: findingTitle(finding) } : node;
  }) } : rawGraph;
  const focusedGraph = availableGraph ? focusedLineage(availableGraph) : null;
  const graph = view.verifyScope === "related" ? availableGraph : focusedGraph;
  const selectedId = view.verifyNode || graph?.root_id;
  const inspectedPassage = graph?.nodes.find(node => node.node_id === view.verifyPassage);
  const canCheck = view.verifyKind === "source" ? !!current?.source && !!file && !fileError : view.verifyKind === "answer" ? !!current?.bundle : view.verifyKind === "bundle" ? !!imported && !fileError : false;

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api<{ sources: Source[] }>(`${office}/sources`, { signal: controller.signal }), api<{ findings: Finding[] }>(`${office}/findings`, { signal: controller.signal })])
      .then(([sources, findings]) => { if (!controller.signal.aborted) { setLibrary({ sources: sources.sources, findings: findings.findings }); setLibraryError(""); } })
      .catch(error => { if (!controller.signal.aborted) setLibraryError(error.message); });
    return () => controller.abort();
  }, [office, libraryRevision]);
  useEffect(() => {
    if (library && !view.verifyId && view.verifyKind === "source" && library.sources.length)
      navigate({ verifyId: [...library.sources].sort((a, b) => sourceTitle(a).localeCompare(sourceTitle(b)))[0].source_id }, true);
  }, [library, view.verifyId, view.verifyKind]);
  useEffect(() => {
    verificationRequest.current?.abort(); fileGeneration.current++;
    setFile(null); setFileError(""); setImported(null); setReport(null); setCheckError(""); setChecking(false); setReading(false); setTagCopy("idle");
    if (input.current) input.current.value = "";
    if (view.verifyKind === "answer") setAnswerDraft(view.verifyId);
    return () => { verificationRequest.current?.abort(); fileGeneration.current++; };
  }, [key]);
  useEffect(() => {
    setContextError("");
    if (!view.verifyId || view.verifyKind === "bundle") return;
    const controller = new AbortController(); const signal = controller.signal;
    const path = view.verifyKind === "source" ? "sources" : view.verifyKind === "finding" ? "findings" : "answers";
    const base = `${office}/${path}/${encodeURIComponent(view.verifyId)}`;
    const root = view.verifyKind === "source" ? api<{ source: Source }>(base, { signal }) : view.verifyKind === "finding" ? getFinding(office, view.verifyId, signal) : api<StoredAnswer>(base, { signal });
    Promise.all([root, api<{ lineage: LineageGraph }>(`${base}/lineage`, { signal }), view.verifyKind === "answer" ? api<{ bundle: Record<string, unknown> }>(`${base}/bundle`, { signal }) : Promise.resolve(null)])
      .then(([record, graph, bundle]) => { if (!signal.aborted) setContext({ key, ...record, graph: graph.lineage, ...(bundle ? { bundle: bundle.bundle } : {}) }); })
      .catch(error => { if (!signal.aborted) setContextError(error.message); });
    return () => controller.abort();
  }, [key, contextRevision]);
  useEffect(() => {
    if (copied === "idle" && tagCopy === "idle") return;
    const timer = window.setTimeout(() => { setCopied("idle"); setTagCopy("idle"); }, 1800);
    return () => window.clearTimeout(timer);
  }, [copied, tagCopy]);

  function choose(kind: View["verifyKind"], id = "", task = view.verifyTab) {
    navigate({ verifyKind: kind, verifyId: id, verifyTab: task, verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "", page: 1, zoom: 100 }, false);
  }
  function selectNode(id: string) {
    if (view.verifyPane === "browse") traceReturnScroll.current = window.scrollY;
    const node = graph?.nodes.find(item => item.node_id === id);
    navigate({ verifyNode: id, verifyPane: "detail", verifyGroup: lineageGroups.find(group => group.types.includes(node?.node_type || ""))?.label || "" }, true);
  }
  function switchTask(task: View["verifyTab"]) { navigate({ verifyTab: task }); }
  useEffect(() => {
    if (view.verifyNode && availableGraph?.nodes.some(node => node.node_id === view.verifyNode) && !focusedGraph?.nodes.some(node => node.node_id === view.verifyNode) && view.verifyScope === "focused")
      navigate({ verifyScope: "related" }, true);
  }, [key, view.verifyNode, availableGraph?.nodes.length]);
  function moveNode(direction: number) {
    if (!graph) return;
    if (view.verifyTab !== "trace") return;
    const nodes = lineageNodes(graph, view.verifySearch);
    const next = nodes[Math.max(0, Math.min(nodes.length - 1, nodes.findIndex(node => node.node_id === selectedId) + direction))];
    if (!next) return;
    keyboardNodeFocus.current = true;
    selectNode(next.node_id);
  }
  useKeyboardShortcuts(shortcutsEnabled, {
    search: () => { navigate({ verifyTab: "trace", verifyPane: "browse" }); requestAnimationFrame(() => { search.current?.focus(); search.current?.select(); }); },
    verify: () => { if (canCheck && !checking && !reading) { switchTask("check"); requestAnimationFrame(() => form.current?.requestSubmit()); } },
    lineage: () => { switchTask("trace"); requestAnimationFrame(() => { document.getElementById("verification-tab-trace")?.setAttribute("data-shortcut-focus", "true"); document.getElementById("verification-tab-trace")?.focus(); }); },
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
    try {
      const bundle = parseEvidenceBundle(await chosen.text());
      if (generation === fileGeneration.current) setImported(bundle);
    } catch (error) { if (generation === fileGeneration.current) setFileError((error as Error).message); }
    finally { if (generation === fileGeneration.current) setReading(false); }
  }
  async function verify(event: FormEvent) {
    event.preventDefault(); if (!canCheck || checking || reading) return;
    const controller = new AbortController(); verificationRequest.current?.abort(); verificationRequest.current = controller;
    setChecking(true); setCheckError(""); setReport(null);
    try {
      let body: BodyInit;
      if (view.verifyKind === "source") {
        const data = new FormData(); data.set("source_id", view.verifyId); data.set("file", file!); body = data;
      } else body = JSON.stringify(current?.bundle || imported);
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
  const targetOptions = view.verifyKind === "source" ? [...library?.sources || []].sort((a, b) => sourceTitle(a).localeCompare(sourceTitle(b))).map(source => ({ value: source.source_id, label: `${sourceTitle(source)} · ${source.version_label}` })) : (library?.findings || []).map(finding => ({ value: finding.finding_id, label: `${findingTag(finding)} · ${findingTitle(finding)}` }));
  const targetExists = targetOptions.some(option => option.value === view.verifyId);
  const bundleAnswer = jsonObject(imported?.answer);
  const title = current?.source ? sourceTitle(current.source) : current?.finding ? findingTitle(current.finding) : current?.answer?.question;
  const checkForm = <form className="verification-form" ref={form} onSubmit={verify} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); if (canCheck && !checking) event.currentTarget.requestSubmit(); } }}>
    {view.verifyKind !== "answer" && <>
      <input ref={input} type="file" id="verification-file" className="sr-only" tabIndex={-1} accept={view.verifyKind === "bundle" ? ".json,application/json" : current?.source?.source_type === "pdf" ? ".pdf,application/pdf" : ".json,application/json"} onChange={(event: ChangeEvent<HTMLInputElement>) => void chooseFile(event.target.files?.[0] || null)} />
      <div className={`evidence-file ${file ? "has-file" : ""}`}>
        <button type="button" onClick={() => input.current?.click()} aria-label={view.verifyKind === "bundle" ? "Choose evidence bundle" : "Choose source copy"} aria-describedby="verification-file-help" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); void chooseFile(event.dataTransfer.files[0] || null); }}>
          {view.verifyKind === "bundle" ? <Braces size={23} /> : <FileText size={23} />}<span><strong title={file?.name}>{file?.name || (view.verifyKind === "bundle" ? "Choose a JSON bundle" : "Choose a source copy")}</strong><span>{file ? `${new Intl.NumberFormat().format(Math.ceil(file.size / 1024))} KB · Click to change` : "Click or drop a file · up to 20 MB"}</span></span>
        </button>
        {file && <button type="button" className="icon-button" aria-label="Remove selected file" onClick={() => { if (input.current) input.current.value = ""; void chooseFile(null); }}><X size={16} /></button>}
      </div>
      <p className="verification-help" id="verification-file-help">{view.verifyKind === "bundle" ? "Use an exported answer evidence bundle. The file is checked against the office’s pinned public keys." : "Compare a copy with the stored original. The original stays unchanged."}</p>
      {fileError && <p className="verification-inline-error" role="alert"><AlertCircle size={15} />{fileError}</p>}
    </>}
    {view.verifyKind === "answer" && <p className="verification-help">Check this answer’s signatures, citations, manifests and disclosed passage proofs against pinned public keys.</p>}
    <div className="verification-submit"><button className="button primary" disabled={!canCheck || checking || reading} aria-keyshortcuts={shortcutsEnabled ? "V Control+Enter Meta+Enter" : "Control+Enter Meta+Enter"}>
      {checking || reading ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />}{checking ? "Checking…" : reading ? "Reading…" : "Run verification"}{shortcutsEnabled && <ShortcutHint>V</ShortcutHint>}
    </button>{view.verifyKind === "answer" && current?.bundle && <button type="button" className="button secondary" onClick={() => downloadJson(current.bundle, `evidence-${view.verifyId}.json`)}><ArrowDownToLine size={15} />Export bundle</button>}</div>
    {checkError && <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{checkError}</span></div>}
  </form>;

  return <div className="verification-workspace">
    <div className="page-heading"><h1>Verification</h1><div className="page-actions">
      <button className="button secondary shortcuts-button" aria-label="Keyboard shortcuts" onClick={onHelp} aria-keyshortcuts="F1"><Keyboard size={16} />Shortcuts<ShortcutHint>F1</ShortcutHint></button>
      <button className={`button secondary verification-share copy-${copied}`} title={copied === "copied" ? "Link copied" : copied === "failed" ? "Could not copy link" : "Copy this view’s link"} onClick={() => void share()}>{copied === "copied" ? <Check size={15} /> : copied === "failed" ? <AlertCircle size={15} /> : <Link size={15} />}Share view</button>
      <span className="sr-only" role="status">{copied === "copied" ? "View link copied" : copied === "failed" ? "Could not copy the view link" : ""}</span>
    </div></div>
    <div className="detail-tabs verification-task-tabs" role="tablist" aria-label="Verification task">
      {([ ["check", "Check integrity", ShieldCheck], ["trace", "Trace evidence", Network] ] as const).map(([task, label, Icon], index) => <button key={task} id={`verification-tab-${task}`} role="tab" aria-selected={view.verifyTab === task} aria-controls={`verification-panel-${task}`} tabIndex={view.verifyTab === task ? 0 : -1} aria-keyshortcuts={task === "trace" && shortcutsEnabled ? "L" : undefined} onBlur={event => { delete event.currentTarget.dataset.shortcutFocus; }} onPointerDown={event => { delete event.currentTarget.dataset.shortcutFocus; }} onClick={() => switchTask(task)} onKeyDown={event => {
        delete event.currentTarget.dataset.shortcutFocus;
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); const next = event.key === "Home" ? "check" : event.key === "End" ? "trace" : index === 0 ? "trace" : "check";
        switchTask(next); document.getElementById(`verification-tab-${next}`)?.focus();
      }}><Icon size={16} />{label}{task === "trace" && shortcutsEnabled && <ShortcutHint>L</ShortcutHint>}</button>)}
    </div>
    <section className="verification-target" aria-label="Choose evidence">
      <div className="verification-target-kind"><label>Evidence type</label><Select label="Evidence type" value={view.verifyKind} options={kinds} onChange={value => choose(value as View["verifyKind"], "", value === "finding" ? "trace" : view.verifyTab)} icon={<ClipboardCheck size={16} />} /></div>
      {["source", "finding"].includes(view.verifyKind) ? <div className="verification-target-record"><label>{view.verifyKind === "source" ? "Source" : "Finding"}</label><Select label={view.verifyKind === "source" ? "Source to verify" : "Finding to trace"} triggerRef={selection} value={view.verifyId} options={targetExists ? targetOptions : [{ value: view.verifyId, label: view.verifyId ? "Selected evidence unavailable" : library ? "Choose evidence" : "Loading evidence…" }, ...targetOptions]} onChange={value => choose(view.verifyKind, value)} /></div> : view.verifyKind === "answer" ? <form className="verification-answer-picker" onSubmit={event => { event.preventDefault(); if (answerDraft.trim()) choose("answer", answerDraft.trim()); }}><label htmlFor="answer-id">Answer ID</label><div><input id="answer-id" placeholder="ans_…" value={answerDraft} onChange={event => setAnswerDraft(event.target.value)} required /><button className="button secondary">Open answer<ArrowRight size={15} /></button></div></form> : <p className="verification-target-note"><Braces size={18} />Inspect an exported bundle, including a modified copy.</p>}
    </section>
    {libraryError && <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{libraryError}</span><button className="text-button" onClick={() => setLibraryRevision(n => n + 1)}>Retry</button></div>}
    {contextError ? <ErrorState title="Evidence unavailable" error={contextError} retry={() => setContextRevision(n => n + 1)} /> : view.verifyKind !== "bundle" && view.verifyId && !current ? <Loading label="Opening evidence and lineage…" /> : <>
      {title && <section className="verification-record-heading"><div><h2>{title}</h2><div>{current?.source && <><span className="source-version">{current.source.version_label}</span><span>{humanize(current.source.authority)}</span></>}{current?.finding && <><button className={`verification-finding-tag copy-${tagCopy}`} title={tagCopy === "copied" ? "Tag copied" : tagCopy === "failed" ? "Could not copy tag" : "Copy finding tag"} aria-label={`Copy finding tag ${findingTag(current.finding)}`} onClick={() => void copyTag()}>{findingTag(current.finding)}{tagCopy === "copied" ? <Check size={13} /> : tagCopy === "failed" ? <AlertCircle size={13} /> : <Copy size={13} />}</button><span className="sr-only" role="status">{tagCopy === "copied" ? "Finding tag copied" : tagCopy === "failed" ? "Could not copy the finding tag" : ""}</span></>}{current?.answer && <><span>{humanize(current.answer.status)}</span><span>Effective {date(current.answer.valid_at)}</span><span>Known {date(current.answer.known_at, true)}</span></>}</div></div>{current?.source && <button className="button secondary" onClick={() => navigate({ document: current.source!.source_id, verifyPassage: "", page: 1, zoom: 100 })}><FileText size={15} />Inspect source</button>}{current?.finding && <button className="button secondary" onClick={() => onFinding(current.finding!.finding_id)}>Open finding<ArrowRight size={15} /></button>}</section>}
      {current?.answer && <><blockquote className="verification-answer-text">{current.answer.answer_text}</blockquote><div className="verification-answer-modes" aria-label="Recorded answer execution modes">{Object.entries(current.answer.modes || {}).map(([stage, mode]) => <span key={stage}><CircleDot size={12} />{humanize(stage)} · {humanize(mode)}</span>)}</div></>}
      <div id="verification-panel-check" role="tabpanel" aria-labelledby="verification-tab-check" hidden={view.verifyTab !== "check"}>
      {view.verifyKind === "finding" && current?.finding ? <section className="verification-finding-sources"><h3><FileCheck2 size={17} />Choose a source copy to check</h3><p>This finding references the sources below. Choose one to compare its file and passages; finding signatures are not checked here.</p><div>{[...new Set(current.finding.evidence.map(item => item.source_id))].map(id => { const source = library?.sources.find(s => s.source_id === id); return <button className="button secondary" key={id} onClick={() => choose("source", id, "check")}><FileCheck2 size={15} /><span>{source ? sourceTitle(source) : "Source"}</span>{source && <span className="source-version">{source.version_label}</span>}<ArrowRight size={14} /></button>; })}</div><p className="verification-help">Finding snapshot signatures are not checked by the source-copy or answer-bundle verifier.</p></section> : (current || view.verifyKind === "bundle") ? <div className="verification-check-layout"><section className="verification-input-panel" aria-labelledby="verification-input-title"><h2 id="verification-input-title">{view.verifyKind === "source" ? "Check a copy" : "Check signed evidence"}</h2>{checkForm}{view.verifyKind === "bundle" && <p className="verification-local-file-note">The file and its result are not saved in shared links. Select the file again after reloading.</p>}{imported && <div className="bundle-preview"><span className="eyebrow">Supplied answer</span><h3>{typeof bundleAnswer.question === "string" ? bundleAnswer.question : "Question not recorded"}</h3><p>{typeof bundleAnswer.answer_text === "string" ? bundleAnswer.answer_text : "Answer text not recorded"}</p></div>}</section>
        <section className="verification-results-panel" aria-labelledby="verification-results-title"><h2 id="verification-results-title">Check results</h2>{report ? <CheckResults report={report} filter={view.verifyChecks} onFilter={value => navigate({ verifyChecks: value }, true)} /> : <div className="verification-not-run"><ShieldCheck size={27} /><strong>{checking ? "Verification in progress" : "No checks run yet"}</strong><p>{view.verifyKind === "source" ? "File identity, document text and passage commitments are checked separately." : "Signatures, evidence bindings and passage proofs are checked separately."}</p></div>}</section></div> : !library && !libraryError ? <Loading label="Loading available evidence…" /> : <EmptyState title={view.verifyKind === "answer" ? "Open a stored answer" : "No evidence selected"} icon={<ShieldCheck size={28} />}>{view.verifyKind === "answer" ? "Enter the answer ID from an API response or demo export, or choose Uploaded bundle." : "Choose a source or finding available to your office."}</EmptyState>}
      </div>
      <div id="verification-panel-trace" role="tabpanel" aria-labelledby="verification-tab-trace" hidden={view.verifyTab !== "trace"}>
      {graph ? <section className={`verification-lineage pane-${view.verifyPane}`} ref={lineage} id="evidence-lineage" tabIndex={-1} aria-labelledby="evidence-lineage-title"><div className="verification-lineage-header"><div><h2 id="evidence-lineage-title">{view.verifyScope === "focused" ? "Selected evidence" : "Related evidence"}</h2><p>{view.verifyScope === "focused" ? "Follow the selected record’s statements, passages and sources." : "Explore the wider set of authorized connections."} Tracing connections does not verify their integrity.</p></div><button className="button secondary" onClick={() => downloadJson(graph, "evidence-lineage.json")}><ArrowDownToLine size={15} />Export trace</button></div>
        <div className="lineage-toolbar"><label className="search-input"><Search size={16} /><span className="sr-only">Search lineage</span><input ref={search} aria-label="Search lineage" placeholder="Search nodes or passages…" value={view.verifySearch} onChange={event => navigate({ verifySearch: event.target.value }, true)} onKeyDown={event => { if (event.key === "Escape" && !event.nativeEvent.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) { event.preventDefault(); lineage.current?.focus({ preventScroll: true }); } }} />{view.verifySearch ? <button className="icon-button" aria-label="Clear lineage search" onClick={() => navigate({ verifySearch: "" }, true)}><X size={14} /></button> : shortcutsEnabled && <ShortcutHint>/</ShortcutHint>}</label><span>{graph.nodes.length} records{shortcutsEnabled && <span className="lineage-navigation-hint"><ShortcutHint>J</ShortcutHint><ShortcutHint>K</ShortcutHint></span>}</span></div>
        <div className="lineage-scope-control"><button className="button secondary" aria-pressed={view.verifyScope === "related"} onClick={() => navigate({ verifyScope: view.verifyScope === "focused" ? "related" : "focused", verifyNode: "", verifyGroup: "", verifyPane: "browse" }, true)}>{view.verifyScope === "focused" ? "Show related evidence" : "Return to focused trace"}<ArrowRight size={14} /></button>{view.verifyScope === "focused" && availableGraph && <span>{Math.max(0, availableGraph.nodes.length - graph.nodes.length)} related records outside this trace</span>}</div>
        <Lineage graph={graph} nodeId={view.verifyNode} search={view.verifySearch} group={view.verifyGroup} pane={view.verifyPane} returnScroll={traceReturnScroll} keyboardFocus={keyboardNodeFocus} onGroup={group => navigate({ verifyGroup: group }, true)} onBack={() => navigate({ verifyPane: "browse" }, true)} onSelect={selectNode} supplied={view.verifyKind === "bundle"} onInspect={node => { navigate({ document: node.attributes.source_id, verifyPassage: node.node_id, page: Math.max(1, Number(node.attributes.page) || 1), zoom: 100 }, false); }} onCheckSource={id => choose("source", id, "check")} onFinding={onFinding} />
      </section> : <div className="verification-trace-empty"><Network size={24} /><p>{view.verifyKind === "bundle" ? "Choose a bundle in Check integrity to explore its supplied evidence." : "Choose evidence to trace its statements, passages and sources."}</p>{view.verifyKind === "bundle" && <button className="button secondary" onClick={() => switchTask("check")}>Choose a bundle<ArrowRight size={15} /></button>}</div>}
      </div>
    </>}
    {view.document && <DocumentDialog office={office} sourceId={view.document} view={view} navigate={navigate} onClose={() => navigate({ document: "", verifyPassage: "" })} onVerify={id => choose("source", id, "check")} evidence={inspectedPassage?.attributes.source_id === view.document && inspectedPassage.attributes.quote ? { source_id: view.document, quote: inspectedPassage.attributes.quote, page: Math.max(1, Number(inspectedPassage.attributes.page) || 1), section: inspectedPassage.attributes.section || null } : undefined} />}
  </div>;
}

function CheckResults({ report, filter, onFilter }: { report: VerificationReport; filter: View["verifyChecks"]; onFilter: (value: View["verifyChecks"]) => void }) {
  const counts = checkCounts(report);
  const summary = checkSummary(report);
  const order = { failed: 0, not_checked: 1, passed: 2 };
  const checks = report.checks.filter(check => filter === "all" || check.status === filter).sort((a, b) => order[a.status] - order[b.status]);
  return <>
    <div className={`verification-result-summary summary-${summary.tone}`} role="status"><h3>{summary.tone === "failed" ? <AlertCircle size={20} /> : summary.tone === "passed" ? <Check size={20} /> : <CircleDot size={20} />}{summary.title}</h3><p>{summary.next}</p></div>
    <div className="verification-counts" role="status" aria-label="Verification result counts">{(["passed", "failed", "not_checked"] as const).map(status => { const Icon = status === "passed" ? Check : status === "failed" ? AlertCircle : CircleDot; return <div className={`check-count check-${status}`} key={status}><Icon size={15} /><strong>{counts[status]}</strong><span>{checkStatusLabels[status]}</span></div>; })}</div>
    <div className="verification-report-toolbar"><Select label="Filter checks" compact value={filter} options={[{ value: "all", label: "All checks" }, ...Object.entries(checkStatusLabels).map(([value, label]) => ({ value, label }))]} onChange={value => onFilter(value as View["verifyChecks"])} /><button className="text-button" onClick={() => downloadJson(report, "verification-report.json")}><ArrowDownToLine size={14} />Export report</button></div>
    <ul className="verification-check-list">{checks.map((check, index) => { const Icon = check.status === "passed" ? Check : check.status === "failed" ? AlertCircle : CircleDot; const skipped = Number(check.detail?.skipped_not_disclosed || check.detail?.not_supplied || 0); return <li key={`${check.check}-${index}`}><div><strong>{checkLabels[check.check] || humanize(check.check)}</strong><span className={`check-badge check-${check.status}`}><Icon size={13} />{checkStatusLabels[check.status]}</span></div>{check.reason && <p>{check.reason}</p>}{skipped > 0 && <p className="check-undisclosed"><CircleDot size={13} />{skipped} undisclosed {skipped === 1 ? "passage or reference was" : "passages or references were"} not checked.</p>}{Object.keys(check.detail || {}).length > 0 && <details><summary>Check details</summary><dl>{Object.entries(check.detail).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value}</dd></div>)}</dl></details>}</li>; })}</ul>
    {!checks.length && <p className="verification-help">No {filter === "all" ? "checks were returned" : `${checkStatusLabels[filter].toLowerCase()} checks in this result`}.</p>}
    {report.generated_at && <p className="verification-report-date">Checked {date(report.generated_at, true)}</p>}
    <p className="verification-help">{report.target_type === "source" ? "Source-copy checks compare bytes and passages with stored commitments. They do not check manifest or finding signatures." : "Signatures are checked against the office’s pinned public keys; passage checks require disclosed evidence."} Integrity checks do not establish that a policy or interpretation is correct.</p>
  </>;
}
