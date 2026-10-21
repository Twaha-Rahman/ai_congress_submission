import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowDownToLine, ArrowRight, ArrowUpFromLine, ArrowDownWideNarrow, Check, Clock3, FileText, Files, Keyboard, LockKeyhole, MessageSquare, GitCompareArrows, Search, X } from "lucide-react";
import { api } from "./api";
import { EmptyState, ErrorState, Loading, Modal, ShortcutHint, AutoRefreshButton } from "./components";
import { date, humanize, scopeLabel, sourceTitle } from "./presentation";
import Select from "./Select";
import UploadPdf from "./UploadPdf";
import SlackConnection from "./SlackConnection";
import ImportSlack from "./ImportSlack";
import UploadStatus, { JobBadge } from "./UploadStatus";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import { isProcessing, keepUploadSelection, visibleSources } from "./uploads";
import type { Evidence, Office, Session, Source, SourceDetail, UploadJob } from "./types";
import type { View } from "./viewState";
import "./sources.css";

const SourceComparison = lazy(() => import("./SourceComparison"));
const SourcePreview = lazy(() => import("./SourcePreview"));

export default function Sources({ office, session, view, navigate, shortcutsEnabled, onHelp, onFindings, onVerify, uploadRequest, onUploadOpened }: {
  office: Office; session: Session | null; view: View;
  navigate: (patch: Partial<View>, replace?: boolean) => void;
  shortcutsEnabled: boolean; onHelp: () => void; onFindings: (sourceId: string) => void;
  uploadRequest: number; onUploadOpened: () => void;
  onVerify: (sourceId: string) => void;
}) {
  const [sources, setSources] = useState<Source[]>([]);
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<UploadJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [jobError, setJobError] = useState("");
  const [notice, setNotice] = useState("");
  const [openUpload, setOpenUpload] = useState(false);
  const [slackOpen, setSlackOpen] = useState(false);
  const [savedSlackOpen, setSavedSlackOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [readRevision, setReadRevision] = useState(0);
  const search = useRef<HTMLInputElement>(null);
  const sort = useRef<HTMLButtonElement>(null);
  const requestSequence = useRef(0);
  const mounted = useRef(true);
  const busy = useRef(false);
  const selectedJobId = useRef(view.uploadJob);
  selectedJobId.current = view.uploadJob;
  const canUpload = !!session?.uploads?.[office]?.enabled;
  const active = jobs.some(isProcessing) || !!(selectedJob && isProcessing(selectedJob));

  const load = useCallback(async (signal?: AbortSignal) => {
    if (busy.current) return;
    busy.current = true;
    const sequence = ++requestSequence.current;
    setRefreshing(true);
    try {
      const [library, activity] = await Promise.all([
        api<{ sources: Source[] }>(`${office}/sources`, { signal }),
        api<{ jobs: UploadJob[] }>(`${office}/jobs?limit=50`, { signal }),
      ]);
      if (!mounted.current || signal?.aborted || sequence !== requestSequence.current) return;
      setSources(library.sources);
      setJobs(activity.jobs.filter((j) => j.kind === "pdf" || j.kind === "slack" || j.kind === "policy_comparison"));
      setError(""); setLoading(false);
    } catch (e) {
      if (mounted.current && !signal?.aborted && sequence === requestSequence.current) {
        setError(e instanceof Error ? e.message : "Sources could not be loaded."); setLoading(false);
      }
    } finally { busy.current = false; if (mounted.current && sequence === requestSequence.current) setRefreshing(false); }
  }, [office]);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void load(controller.signal);
    return () => { mounted.current = false; controller.abort(); busy.current = false; };
  }, [load]);
  useEffect(() => { if (uploadRequest > 0) { setOpenUpload(true); onUploadOpened(); } }, [uploadRequest, onUploadOpened]);
  useEffect(() => {
    if (!view.uploadJob) { setSelectedJob(null); setJobError(""); return; }
    const fromList = jobs.find((j) => j.job_id === view.uploadJob);
    if (fromList) { setSelectedJob(fromList); setJobError(""); return; }
    const controller = new AbortController();
    setSelectedJob(null); setJobError("");
    api<{ job: UploadJob }>(`${office}/jobs/${encodeURIComponent(view.uploadJob)}`, { signal: controller.signal })
      .then(({ job }) => { if (!controller.signal.aborted) setSelectedJob(job); })
      .catch((e) => { if (!controller.signal.aborted) setJobError(e.message); });
    return () => controller.abort();
  }, [jobs, office, view.uploadJob, readRevision]);
  useEffect(() => {
    if (!view.autoRefresh || openUpload || view.document) return;
    const timer = window.setInterval(() => {
      if (document.hidden || document.querySelector("dialog[open]:not(.upload-status-dialog)") || document.activeElement?.closest("input, textarea, [contenteditable=true], [role=combobox][aria-expanded=true]")) return;
      void load();
      setReadRevision((n) => n + 1);
    }, active ? 3000 : 10000);
    return () => window.clearInterval(timer);
  }, [view.autoRefresh, view.document, openUpload, active, load]);

  const visible = useMemo(() => visibleSources(sources, view.sourceSearch, view.sourceType, view.sourceSort), [sources, view.sourceSearch, view.sourceType, view.sourceSort]);
  useKeyboardShortcuts(shortcutsEnabled, {
    search: () => { search.current?.focus(); search.current?.select(); },
    sort: () => { sort.current?.focus(); sort.current?.click(); },
    refresh: () => navigate({ autoRefresh: !view.autoRefresh }),
  });
  function compareVersions(sourceId: string) {
    navigate({versionSource: sourceId, versionBase: "", versionNext: "", versionFilter: "changes", versionSearch: "", document: ""}, false);
  }
  function queued(job: UploadJob) {
    if (!mounted.current) return;
    setOpenUpload(false); setSavedSlackOpen(false); setJobs((current) => [job, ...current.filter((j) => j.job_id !== job.job_id)]);
    setNotice(`${job.kind === "slack" ? "Saved messages" : "PDF"} received. Processing is queued and auto-refresh is on.`);
    navigate({ uploadJob: keepUploadSelection(selectedJobId.current, job.job_id), autoRefresh: true });
    void load();
  }
  async function retryComparison(job: UploadJob) {
    if (!job.source_id || retrying) return;
    setRetrying(true); setJobError("");
    try {
      const result = await api<{ job: UploadJob }>(`${office}/sources/${encodeURIComponent(job.source_id)}/comparisons?mode=live`, { method: "POST" });
      if (!mounted.current) return;
      if (!result.job?.job_id) throw new Error("The office did not confirm a comparison job.");
      setJobs((current) => [result.job, ...current]); navigate({ uploadJob: result.job.job_id, autoRefresh: true });
      setNotice("Comparison queued. The original PDF and earlier assessments are preserved.");
    } catch (e) { if (mounted.current) setJobError((e instanceof Error ? e.message : "Comparison could not be queued.") + " Check recent uploads before retrying."); }
    finally { if (mounted.current) setRetrying(false); }
  }
  return <>
    <div className="page-heading sources-heading"><h1>Sources</h1>
      <div className="page-actions">
        <button className="button secondary shortcuts-button" aria-label="Keyboard shortcuts" aria-keyshortcuts={shortcutsEnabled ? "F1 Shift+/" : "F1"} onClick={onHelp}><Keyboard size={16} /><span>Shortcuts</span><ShortcutHint>F1</ShortcutHint></button>
        <AutoRefreshButton enabled={view.autoRefresh} refreshing={refreshing} shortcutsEnabled={shortcutsEnabled}
          title="Checks every 3 seconds during processing and every 10 seconds otherwise. Pauses while editing or inspecting sources."
          onToggle={() => { navigate({ autoRefresh: !view.autoRefresh }); if (!view.autoRefresh) void load(); }} />
        {canUpload && <><button className="button secondary" onClick={() => setSavedSlackOpen(true)}><MessageSquare size={16} />Import Slack JSON</button><button className="button secondary" onClick={() => setSlackOpen(true)}><MessageSquare size={16} />Live Slack</button></>}
        <button className="button primary" disabled={!canUpload} aria-keyshortcuts={shortcutsEnabled && canUpload ? "U" : undefined} onClick={() => setOpenUpload(true)}><ArrowUpFromLine size={16} />Upload PDF{shortcutsEnabled && <ShortcutHint>U</ShortcutHint>}</button>
      </div>
    </div>
    {session && !canUpload && <div className="notice"><LockKeyhole size={17} /><span>{session.role === "reader" ? "Read-only access. You can inspect sources; uploading requires an authorized workspace." : `The ${humanize(office)} upload connection is not configured. Set the office uploader credential on the frontend server, then restart it.`}</span></div>}
    {notice && <div className="notice success" role="status"><Check size={17} /><span>{notice}</span><button className="icon-button" aria-label="Dismiss notification" onClick={() => setNotice("")}><X size={16} /></button></div>}
    {loading ? <Loading label="Loading sources and recent uploads…" /> : error && !sources.length && !jobs.length ? <ErrorState error={error} retry={() => void load()} /> : <>
      {error && <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{error} Previously loaded data is shown.</span><button className="text-button" onClick={() => void load()}>Try again</button></div>}
      <div className="sources-layout">
        <section className="source-library" aria-labelledby="source-library-title">
          <div className="source-section-heading"><h2 id="source-library-title" tabIndex={-1}>Office library <span>{sources.length}</span></h2><span>{humanize(office)} office</span></div>
          <div className="source-tools"><label className="search-input"><Search size={16} /><span className="sr-only">Search sources</span>
            <input ref={search} placeholder="Search policies, categories or versions…" aria-label="Search sources" value={view.sourceSearch} aria-keyshortcuts={shortcutsEnabled ? "/ Escape" : "Escape"}
              onChange={(e) => navigate({ sourceSearch: e.target.value })} onKeyDown={(e) => { if (e.key === "Escape" && !e.nativeEvent.isComposing && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); document.getElementById("source-library-title")?.focus(); } }} />
            {shortcutsEnabled && <span className="search-shortcuts" aria-hidden="true"><ShortcutHint className="search-idle">/</ShortcutHint><ShortcutHint className="search-editing">Esc</ShortcutHint></span>}
            <button className="icon-button" aria-label="Clear source search" tabIndex={view.sourceSearch ? 0 : -1} style={{ visibility: view.sourceSearch ? "visible" : "hidden" }} onClick={() => { navigate({ sourceSearch: "" }); search.current?.focus(); }}><X size={14} /></button></label>
            <Select label="Source type" value={view.sourceType} options={[{ value: "all", label: "All sources" }, { value: "pdf", label: "PDF documents" }, { value: "slack", label: "Slack messages" }]} onChange={(value) => navigate({ sourceType: value as View["sourceType"] })} />
            <Select label="Sort sources" compact icon={<ArrowDownWideNarrow size={15} />} value={view.sourceSort} triggerRef={sort} shortcut={shortcutsEnabled ? "S" : undefined}
              options={[{ value: "newest", label: "Newest first" }, { value: "name", label: "Policy name" }]} onChange={(value) => navigate({ sourceSort: value as View["sourceSort"] })} />
          </div>
          {visible.length ? <ul className="source-list">
            {visible.map((source) => <li className="source-row" key={source.source_id}>
              <span className={`source-type-icon authority-${source.authority}`}>{source.source_type === "pdf" ? <FileText size={20} /> : <MessageSquare size={20} />}</span>
              <div className="source-row-body"><div className="source-row-top"><button className="source-name" onClick={() => navigate({ document: source.source_id, page: 1, zoom: 100 }, false)}>{sourceTitle(source)}</button><span className="source-version">{source.version_label}</span></div>
                <div className="source-row-meta">{source.status === "withdrawn" && <span>Withdrawn</span>}<span>{humanize(source.authority)}</span>{source.policy_family && <span>{humanize(source.policy_family)}</span>}{source.sensitivity === "restricted" && <span className="restricted-source"><LockKeyhole size={12} />Restricted</span>}</div>
                <p className="source-row-date">Effective {date(source.effective_from)} <span>· Added {date(source.ingested_at)}</span></p>
              </div>
              <div className="source-row-actions"><button className="icon-button" aria-label={`Compare versions of ${source.source_identity}`} title="Compare source versions" onClick={()=>compareVersions(source.source_id)}><GitCompareArrows size={17}/></button><button className="button secondary" aria-label={`Inspect ${source.source_identity} ${source.version_label}`} onClick={() => navigate({ document: source.source_id, page: 1, zoom: 100 }, false)}>Inspect</button><button className="icon-button" aria-label={`Findings for ${source.source_identity} ${source.version_label}`} title="View findings for this source" onClick={() => onFindings(source.source_id)}><ArrowRight size={17} /></button></div>
            </li>)}
          </ul> : <EmptyState icon={<Files size={27} />} title={sources.length ? "No sources match" : "No sources yet"}
            action={sources.length ? <button className="button secondary" onClick={() => navigate({ sourceSearch: "", sourceType: "all" })}>Clear filters</button> : canUpload ? <button className="button secondary" onClick={() => setOpenUpload(true)}><ArrowUpFromLine size={16} />Upload a PDF</button> : undefined}>
            {sources.length ? "Try another name, category or version." : "Add a policy PDF to begin checking guidance against its evidence."}</EmptyState>}
          <p className="source-library-note"><LockKeyhole size={13} />Only sources your role can access are shown.</p>
        </section>
        <aside className="upload-activity" id="upload-activity" tabIndex={-1} aria-labelledby="upload-activity-title">
          <div className="source-section-heading"><h2 id="upload-activity-title">Recent activity</h2>{active && <span className="activity-live"><span className="small-dot dot-policy" />In progress</span>}</div>
          {!view.autoRefresh && active && <p className="activity-paused">Updates paused. <button className="text-button" onClick={() => { navigate({ autoRefresh: true }); void load(); }}>Resume updates</button></p>}
          {jobError && <div className="notice warning" role="alert"><AlertCircle size={16} /><span>{jobError}</span></div>}
          {jobs.length ? <ul className="upload-job-list">{jobs.slice(0, 12).map((job) => <li key={job.job_id}><button className={`upload-job ${view.uploadJob === job.job_id ? "selected" : ""}`} aria-pressed={view.uploadJob === job.job_id} onClick={() => navigate({ uploadJob: job.job_id })}>
            <span className="upload-job-name">{job.display_name || job.source_identity || (job.kind === "slack" ? "Slack message" : job.kind === "policy_comparison" ? "Policy comparison" : "PDF upload")}</span><JobBadge job={job} /><span className="upload-job-date">{`${job.kind === "slack" ? "Slack · " : ""}${job.version_label ? `${job.version_label} · ` : ""}`}{date(job.created_at, true)}</span>
          </button></li>)}</ul> : <div className="activity-empty"><Clock3 size={21} /><p>No recent activity</p><span>PDF and Slack processing will appear here.</span></div>}
        </aside>
      </div>
    </>}
    {view.uploadJob && !openUpload && !savedSlackOpen && !slackOpen && !view.versionSource && !view.document && <Modal title="Upload status" className="upload-status-dialog" onClose={() => navigate({ uploadJob: "" })}>
      {selectedJob && jobError && <div className="notice warning" role="alert"><AlertCircle size={16} /><span>{jobError}</span></div>}
      {selectedJob ? <UploadStatus job={selectedJob} retrying={retrying} canRetry={!!(selectedJob.source_id && ["needs_review", "failed"].includes(selectedJob.status) && canUpload && !active && sources.find((s) => s.source_id === selectedJob.source_id)?.subject === "general_policy")}
        onRetry={() => void retryComparison(selectedJob)} onFindings={() => onFindings(selectedJob.source_id!)}
        onInspect={() => navigate({ document: selectedJob.source_id!, page: 1, zoom: 100 })}
        onImportSlack={canUpload ? () => setSavedSlackOpen(true) : undefined}
        onUpload={canUpload && selectedJob.kind !== "slack" ? () => setOpenUpload(true) : undefined} /> : <div className="dialog-body">{jobError ? <ErrorState error={jobError} retry={() => setReadRevision((n) => n + 1)} /> : <Loading label="Opening processing job…" />}</div>}
    </Modal>}
    {slackOpen && <SlackConnection office={office} onClose={() => setSlackOpen(false)} onJob={id => { setSlackOpen(false); navigate({ uploadJob: id }); void load(); }} />}
    <ImportSlack key={office} open={savedSlackOpen} office={office} config={session?.uploads?.[office]} onClose={() => setSavedSlackOpen(false)} onQueued={queued} />
    <UploadPdf open={openUpload} office={office} sources={sources} config={session?.uploads?.[office]} shortcutsEnabled={shortcutsEnabled} onClose={() => setOpenUpload(false)} onQueued={queued} />
    {view.versionSource && !openUpload && !savedSlackOpen && !slackOpen && <Suspense fallback={<Loading label="Opening version comparison…"/>}><SourceComparison office={office} view={view} navigate={navigate} shortcutsEnabled={shortcutsEnabled} onClose={()=>navigate({versionSource:""})} onInspect={(id,passage)=>navigate({document:id,page:passage?.page||1,zoom:100},false)}/></Suspense>}
    {view.document && <DocumentDialog office={office} sourceId={view.document} view={view} navigate={navigate} onClose={() => navigate({ document: "" })} onVerify={onVerify} onCompare={view.versionSource ? undefined : compareVersions} />}
  </>;
}

export function DocumentDialog({ office, sourceId, view, navigate, onClose, onVerify, onCompare, evidence }: {
  office: Office; sourceId: string; view: View; navigate: (patch: Partial<View>) => void; onClose: () => void;
  onCompare?: (sourceId:string)=>void;
  onVerify?: (sourceId: string) => void;
  evidence?: Pick<Evidence, "source_id" | "quote" | "page" | "section">;
}) {
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setDetail(null); setError("");
    api<SourceDetail>(`${office}/sources/${encodeURIComponent(sourceId)}`, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setDetail(data); })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [office, sourceId]);
  return <Modal title="Inspect source" onClose={onClose} className="source-preview-dialog library-source-dialog">
    <div className="dialog-body">
      {error ? <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{error}</span></div> : !detail ? <Loading label="Opening source…" /> : <>
        <div className="library-source-title"><h3>{sourceTitle(detail.source)}</h3><span className="source-version">{detail.source.version_label}</span></div>
        <p className="library-source-context">{humanize(detail.source.authority)} · Published {date(detail.source.publication_time)} · Effective {date(detail.source.effective_from)}</p>
        <Suspense fallback={<Loading label="Loading document viewer…" />}><SourcePreview office={office} source={detail.source} evidence={evidence} pageNumber={view.page} zoom={view.zoom} onPageChange={(page) => navigate({ page })} onZoomChange={(zoom) => navigate({ zoom })} /></Suspense>
        <details className="library-source-metadata"><summary>Source details</summary><dl><dt>Policy category</dt><dd>{detail.source.policy_family ? humanize(detail.source.policy_family) : "Not specified"}</dd><dt>Applies to</dt><dd>{scopeLabel(detail.source.manifest.scope)}</dd><dt>Access</dt><dd>{detail.source.sensitivity === "restricted" ? "Restricted readers" : "Office readers"}</dd><dt>Hosted processing</dt><dd>{detail.source.hosted_model ? "Permitted" : "Not permitted"}</dd><dt>Office export</dt><dd>{detail.source.office_export ? "Permitted" : "Not permitted"}</dd><dt>Added</dt><dd>{date(detail.source.ingested_at, true)}</dd></dl></details>
      </>}
    </div>
    <footer className="dialog-footer"><span className="upload-save-status">Integrity verification has not been run here.</span>{detail && <>{onCompare&&<button className="button secondary" onClick={()=>onCompare(sourceId)}><GitCompareArrows size={15}/>Compare versions</button>}{onVerify && <button className="button secondary" onClick={() => onVerify(sourceId)}><Check size={15} />Verify source</button>}<a className="button secondary" href={`/api/${office}/sources/${encodeURIComponent(sourceId)}/content`} download><ArrowDownToLine size={15} />Download original</a></>}</footer>
  </Modal>;
}
