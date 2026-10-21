import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  ArrowDownWideNarrow,
  ArrowLeft,
  ArrowRight,
  Check,
  CircleCheck,
  Globe2,
  Inbox,
  LayoutList,
  LoaderCircle,
  LockKeyhole,
  Search,
  Shield,
  Keyboard,
  X,
  Files,
  MessageSquare,
  Activity as ActivityIcon,
} from "lucide-react";
import { api, ApiError, getFinding, reviewFinding } from "./api";
import {
  EmptyState,
  ErrorState,
  Loading,
  Modal,
  ReviewBadge,
  ShortcutHint,
  AutoRefreshButton,
} from "./components";
import FindingDetail from "./FindingDetail";
import Highlight, { QueueMatchContext } from "./Highlight";
import Select from "./Select";
import ThemeSelect from "./ThemeSelect";
import Sources from "./Sources";
import Verification from "./Verification";
import Questions from "./Questions";
import Comparisons from "./Comparisons";
import Activity from "./Activity";
import { reviewQueue, unreviewedFindings } from "./reviewQueue";
import {
  useKeyboardShortcuts,
  useShortcutPreference,
} from "./useKeyboardShortcuts";
import { shortcutDescriptions } from "./shortcuts";
import {
  date,
  findingTitle,
  findingTag,
  humanize,
  orderFindings,
  sortOptions,
  type FindingSort,
  scopeLabel,
  typeLabels,
} from "./presentation";
import {
  pinSelection,
  readView,
  selectedFinding,
  viewSearch,
  type DetailTab,
  type View,
} from "./viewState";
import type {
  Claim,
  Finding,
  Office,
  ReviewAction,
  ReviewEvent,
  Session,
  Source,
  WorkspaceData,
} from "./types";

type Detail = {
  office: Office;
  id: string;
  finding: Finding;
  reviews: ReviewEvent[];
};

function readBrowserView() {
  const result = readView(window.location.search);
  if (
    !new URLSearchParams(window.location.search).has("pane") &&
    window.matchMedia("(min-width: 761px)").matches
  )
    result.pane = "detail";
  return result;
}

export default function App() {
  const [screen, setScreen] = useState<"findings" | "sources" | "verification" | "questions" | "comparisons" | "activity">(() => window.location.pathname === "/activity" ? "activity" : window.location.pathname === "/comparisons" ? "comparisons" : window.location.pathname === "/questions" ? "questions" : window.location.pathname === "/sources" ? "sources" : window.location.pathname === "/verification" ? "verification" : "findings");
  const isActivity = screen === "activity";
  const isComparisons = screen === "comparisons";
  const isQuestions = screen === "questions";
  const isSources = screen === "sources";
  const isVerification = screen === "verification";
  const isFindings = screen === "findings";
  const [uploadRequest, setUploadRequest] = useState(0);
  const [view, setView] = useState<View>(readBrowserView);
  const [session, setSession] = useState<Session | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [queueCount,setQueueCount]=useState<{office:Office;value:number}|null>(null);
  const [workspace, setWorkspace] = useState<
    (WorkspaceData & { office: Office }) | null
  >(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [reviewAction, setReviewAction] = useState<ReviewAction | null>(null);
  const [notice, setNotice] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [shortcutsEnabled, setShortcutsEnabled] = useShortcutPreference();
  const searchRef = useRef<HTMLInputElement>(null);
  const sortRef = useRef<HTMLButtonElement>(null);
  const officeRef = useRef<HTMLButtonElement>(null);
  const pendingKeyboardFocus = useRef(false);
  const data = workspace?.office === view.office ? workspace : null;

  function navigate(patch: Partial<View>, replace = false) {
    const next = { ...pinSelection(view, selectedRecord), ...patch };
    const url = new URL(window.location.href);
    url.pathname = `/${screen}`;
    url.search = viewSearch(next);
    window.history[replace ? "replaceState" : "pushState"]({}, "", url);
    setView(next);
  }
  function openScreen(nextScreen: "findings" | "sources" | "verification" | "questions" | "comparisons" | "activity", patch: Partial<View> = {}) {
    const next = { ...pinSelection(view, selectedRecord), ...patch };
    const url = new URL(window.location.href);
    url.pathname = `/${nextScreen}`;
    url.search = viewSearch(next);
    window.history.pushState({}, "", url);
    setScreen(nextScreen);
    setView(next);
    setReviewAction(null);
    setShowShortcuts(false);
    requestAnimationFrame(() => document.getElementById("workspace")?.focus({ preventScroll: true }));
  }
  function openUpload() {
    if (session?.uploads?.[view.office]?.enabled) {
      if (!isSources) openScreen("sources", { source: "", document: "", versionSource: "" });
      setUploadRequest((n) => n + 1);
    }
  }
  useEffect(() => {
    const handler = () => {
      const next = readBrowserView();
      setScreen(window.location.pathname === "/activity" ? "activity" : window.location.pathname === "/comparisons" ? "comparisons" : window.location.pathname === "/questions" ? "questions" : window.location.pathname === "/sources" ? "sources" : window.location.pathname === "/verification" ? "verification" : "findings");
      setView(next);
      setNotice("");
      setReviewAction(null);
      setShowShortcuts(false);
    };
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  useEffect(() => {
    document.title = `${isActivity ? "Activity" : isComparisons ? "Cross-office" : isQuestions ? "Questions" : isSources ? "Sources" : isVerification ? "Verification" : "Findings"} · Meridian`;
  }, [screen]);
  useEffect(() => {
    const controller = new AbortController();
    api<Session>("session", { signal: controller.signal })
      .then(setSession)
      .catch((error) => {
        if (error.name !== "AbortError") { setError(error.message); setSessionError(error.message); }
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!isFindings) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([
      api<{ findings: Finding[] }>(`${view.office}/findings`, {
        signal: controller.signal,
      }),
      api<{ sources: Source[] }>(`${view.office}/sources`, {
        signal: controller.signal,
      }),
      api<{ claims: Claim[] }>(`${view.office}/claims`, {
        signal: controller.signal,
      }),
    ])
      .then(([f, s, c]) => {
        setWorkspace({
          office: view.office,
          findings: orderFindings(f.findings),
          sources: s.sources,
          claims: c.claims,
        });
        setLoading(false);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setError(error.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [view.office, revision, isFindings]);

  const visible = useMemo(() => reviewQueue(data?.findings||[],view), [data, view.search, view.type, view.severity, view.sort, view.forSource]);
  const unreviewedCount=isFindings&&data ? unreviewedFindings(data.findings).length : queueCount?.office===view.office ? queueCount.value : data ? unreviewedFindings(data.findings).length : null;
  useEffect(()=>{if(isFindings&&data)setQueueCount({office:view.office,value:unreviewedFindings(data.findings).length});},[data,isFindings,view.office]);
  useEffect(()=>{
    if(isFindings)return;
    const controller=new AbortController();
    let sequence=0;
    const loadCount=()=>{const current=++sequence;return api<{findings:Finding[]}>(`${view.office}/findings?review_state=open`,{signal:controller.signal})
      .then(result=>{if(!controller.signal.aborted&&sequence===current)setQueueCount({office:view.office,value:unreviewedFindings(result.findings).length});})
      .catch(()=>{});};
    void loadCount();
    const refresh=()=>{if(!document.hidden&&!document.querySelector("dialog[open], input:focus, textarea:focus, [role=combobox][aria-expanded=true]"))void loadCount();};
    window.addEventListener("focus",refresh);document.addEventListener("visibilitychange",refresh);
    const timer=view.autoRefresh?window.setInterval(refresh,10000):undefined;
    return()=>{controller.abort();window.removeEventListener("focus",refresh);document.removeEventListener("visibilitychange",refresh);if(timer)clearInterval(timer);};
  },[view.office,isFindings,view.autoRefresh]);
  const selection = selectedFinding(view, data?.findings || [], visible);
  const selectedId = selection.id;
  const selectedRecord = data?.findings.find(
    (f) => f.finding_id === selectedId,
  );
  // Pin the initial implicit selection too, before sort/polling can change the queue.
  useEffect(() => {
    if (
      isFindings && selectedRecord &&
      (view.finding !== selectedId ||
        view.tag !== findingTag(selectedRecord).slice(1))
    )
      navigate({}, true);
  }, [selectedRecord, selectedId, view.finding, view.tag, isFindings]);
  useEffect(() => {
    if (
      !isFindings || !view.autoRefresh ||
      loading ||
      detailLoading ||
      reviewAction ||
      showShortcuts ||
      view.source
    )
      return;
    const timer = window.setInterval(() => {
      const editing = document.activeElement?.closest(
        "input, textarea, [contenteditable=true], [role=combobox][aria-expanded=true]",
      );
      if (!document.hidden && !editing) setRevision((n) => n + 1);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [
    view.autoRefresh,
    loading,
    detailLoading,
    reviewAction,
    showShortcuts,
    view.source,
    isFindings,
  ]);
  useEffect(() => {
    if (!isFindings) return;
    if (!selectedId) {
      setDetail(null);
      setDetailError("");
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    setDetailError("");
    setDetailLoading(true);
    getFinding(view.office, selectedId, controller.signal)
      .then((result) => {
        setDetail({ office: view.office, id: selectedId, ...result });
        setDetailLoading(false);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setDetailError(
            error instanceof ApiError && error.status === 404
              ? "This finding is unavailable in this office or your current access scope."
              : error.message,
          );
          setDetailLoading(false);
        }
      });
    return () => controller.abort();
  }, [view.office, selectedId, revision, isFindings]);
  const current =
    detail?.office === view.office && detail.id === selectedId ? detail : null;
  useEffect(() => {
    if (pendingKeyboardFocus.current && current && !detailLoading) {
      document.getElementById("finding-title")?.focus({ preventScroll: true });
      pendingKeyboardFocus.current = false;
    }
  }, [current, detailLoading]);
  const filtered = !!(
    view.search || view.forSource ||
    view.type !== "all" ||
    view.severity !== "all"
  );

  function selectFinding(finding: Finding) {
    navigate({
      finding: finding.finding_id,
      tag: findingTag(finding).slice(1),
      pane: "detail",
      source: "",
      sourceMode: "details",
      page: 1,
      zoom: 100,
    });
    setNotice("");
    if (window.matchMedia("(max-width: 760px)").matches)
      requestAnimationFrame(() =>
        document
          .getElementById("workspace")
          ?.scrollIntoView({ block: "start" }),
      );
  }
  function filter(patch: Partial<View>) {
    navigate(
      {
        ...patch,
        finding: "",
        tag: "",
        pane: "queue",
        source: "",
        sourceMode: "details",
        tab: "evidence",
        page: 1,
      },
      true,
    );
  }
  function clearFilters() {
    filter({ search: "", state: "all", type: "all", severity: "all", forSource: "" });
  }
  function retry() {
    setRevision((n) => n + 1);
  }
  function toggleAutoRefresh() {
    navigate({ autoRefresh: !view.autoRefresh }, true);
    if (
      !view.autoRefresh &&
      !loading &&
      !reviewAction &&
      !showShortcuts &&
      !view.source
    )
      retry();
  }

  function focusSearch() {
    navigate({ pane: "queue" }, true);
    requestAnimationFrame(() => {
      searchRef.current?.focus();
      searchRef.current?.select();
    });
  }
  function moveFinding(direction: number) {
    const index = visible.findIndex((f) => f.finding_id === selectedId);
    const next =
      visible[Math.max(0, Math.min(visible.length - 1, index + direction))];
    if (!next) return;
    pendingKeyboardFocus.current =
      window.matchMedia("(max-width: 760px)").matches;
    selectFinding(next);
    requestAnimationFrame(() => {
      const element = window.matchMedia("(max-width: 760px)").matches
        ? document.querySelector<HTMLElement>("#finding-title")
        : document.querySelector<HTMLElement>(
            `[data-finding-id="${next.finding_id}"]`,
          );
      element?.focus({ preventScroll: true });
      if (element?.matches(".finding-list-item"))
        element.scrollIntoView({ block: "nearest" });
    });
  }
  function reviewWithShortcut(action: ReviewAction) {
    // Background reads do not block reviewing the displayed snapshot.
    // The review API checks its expected snapshot before saving a decision.
    if (
      current &&
      !detailError &&
      !error &&
      session?.canReview &&
      !current.finding.superseded_by_snapshot_id
    ) {
      navigate({ pane: "detail" }, true);
      setReviewAction(action);
    }
  }
  function switchTab(tab: DetailTab) {
    if (!current || detailError || error) return;
    navigate({ pane: "detail", tab }, true);
    requestAnimationFrame(() => {
      const button = document.getElementById(`tab-${tab}`);
      // Direct shortcuts use the selected tab's underline as the focus cue.
      if (button) button.dataset.shortcutFocus = "true";
      button?.focus();
    });
  }
  function openSelect(ref: typeof sortRef) {
    navigate({ pane: "queue" }, true);
    requestAnimationFrame(() => {
      ref.current?.focus();
      if (ref.current?.getAttribute("aria-expanded") === "false")
        ref.current.click();
    });
  }
  useKeyboardShortcuts(shortcutsEnabled, {
    ...(isFindings ? {
    search: focusSearch,
    next: () => moveFinding(1),
    previous: () => moveFinding(-1),
    acknowledge: () => reviewWithShortcut("acknowledge"),
    resolve: () => reviewWithShortcut("resolve"),
    dismiss: () => reviewWithShortcut("dismiss"),
    evidence: () => switchTab("evidence"),
    timeline: () => switchTab("timeline"),
    reviews: () => switchTab("reviews"),
    sort: () => openSelect(sortRef),
    refresh: toggleAutoRefresh,
    verify: () => { if (current && !detailError) openScreen("verification", { verifyKind: "finding", verifyTab: "trace", verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyId: current.id, verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "" }); },
    } : {}),
    office: () => openSelect(officeRef),
    upload: openUpload,
    help: () => setShowShortcuts(true),
  });

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="/findings"
          onClick={(event) => {
            event.preventDefault();
            openScreen("findings", {
              finding: "",
              tag: "",
              source: "",
              tab: "evidence",
              pane: "queue",
              search: "",
              state: "all",
              type: "all",
              severity: "all",
            });
          }}
        >
          <img src="/meridian.svg" width="34" height="34" alt="" />
          <span>
            meridian<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="sidebar-workspace">
          <span className="workspace-avatar">M</span>
          <div>
            <strong>Meridian Trade Finance</strong>
            <span>Institutional memory</span>
          </div>
        </div>
        <div className="sidebar-label">Workspace</div>
        <nav aria-label="Workspace">
          <a
            className={`nav-item ${isFindings ? "active" : ""}`}
            href={`/findings?office=${view.office}`}
            aria-current={isFindings ? "page" : undefined}
            onClick={(event) => {
              event.preventDefault();
              openScreen("findings");
            }}
          >
            <LayoutList size={18} />
            <span>Findings</span>
            {unreviewedCount!==null && <span className="nav-count" title="Unreviewed findings" aria-label={`${unreviewedCount} unreviewed findings`}>{unreviewedCount}</span>}
          </a>
          <a className={`nav-item ${isQuestions ? "active" : ""}`}
            href={`/questions${viewSearch(view)}`} aria-current={isQuestions ? "page" : undefined}
            onClick={(event) => { event.preventDefault(); openScreen("questions"); }}>
            <MessageSquare size={18} /><span>Questions</span>
          </a>
          <a className={`nav-item ${isComparisons ? "active" : ""}`}
            href={`/comparisons${viewSearch(view)}`} aria-current={isComparisons ? "page" : undefined}
            onClick={event => { event.preventDefault(); openScreen("comparisons", { document: "", compareCitation: "" }); }}>
            <Globe2 size={18} /><span>Cross-office</span>
          </a>
          <a className={`nav-item ${isSources ? "active" : ""}`}
            href={`/sources${viewSearch(view)}`} aria-current={isSources ? "page" : undefined}
            onClick={(event) => { event.preventDefault(); openScreen("sources"); }}>
            <Files size={18} /><span>Sources</span>
          </a>
          <a className={`nav-item ${isVerification ? "active" : ""}`}
            href={`/verification${viewSearch(view)}`} aria-current={isVerification ? "page" : undefined}
            onClick={(event) => { event.preventDefault(); openScreen("verification"); }}>
            <Shield size={18} /><span>Verification</span>
          </a>
          {session?.activity && <a className={`nav-item ${isActivity ? "active" : ""}`} href={`/activity${viewSearch(view)}`} aria-current={isActivity ? "page" : undefined} onClick={event => { event.preventDefault(); openScreen("activity"); }}><ActivityIcon size={18}/><span>Activity</span></a>}
        </nav>
        <div className="sidebar-context">
          <div className="office-select">
            <Select
              label="Office"
              icon={<Globe2 size={16} />}
              triggerRef={officeRef}
              shortcut={shortcutsEnabled ? "O" : undefined}
              value={view.office}
              onChange={(value) => {
                navigate({
                  office: value as Office,
                  finding: "",
                  tag: "",
                  source: "",
                  tab: "evidence",
                  pane: "queue",
                  page: 1,
                  document: "",
                  uploadJob: "",
                  activityId: "", versionSource: "", versionBase: "", versionNext: "", versionSearch: "",
                  forSource: "",
                  questionId: "", questionSearch: "", questionPane: "compose", questionPanel: "ask", questionCitation: "",
                  verifyId: "", verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all",
                });
                setNotice("");
              }}
              options={[
                { value: "dhaka", label: "Dhaka office" },
                { value: "frankfurt", label: "Frankfurt office" },
              ]}
            />
          </div>
          <ThemeSelect shortcutsEnabled={shortcutsEnabled} />
          <div className="sidebar-account" role="group" aria-label={session ? `${humanize(session.role)} access` : "Connecting"} title={session ? `${humanize(session.role)} access` : "Connecting"}>
            <span className="role-label">
              {session ? humanize(session.role) : "Connecting…"}
            </span>
            <span className="avatar" aria-hidden="true">
              {session?.role === "reader" ? "AN" : "CR"}
            </span>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <nav className="mobile-workspace-nav" aria-label="Workspace">
          <a href={`/findings${viewSearch(view)}`} aria-current={isFindings ? "page" : undefined} onClick={(e) => { e.preventDefault(); openScreen("findings"); }}><LayoutList size={16} />Findings</a>
          <a href={`/questions${viewSearch(view)}`} aria-current={isQuestions ? "page" : undefined} onClick={(e) => { e.preventDefault(); openScreen("questions"); }}><MessageSquare size={16} />Questions</a>
          <a href={`/comparisons${viewSearch(view)}`} aria-current={isComparisons ? "page" : undefined} onClick={e => { e.preventDefault(); openScreen("comparisons", { document: "", compareCitation: "" }); }}><Globe2 size={16} />Cross-office</a>
          <a href={`/sources${viewSearch(view)}`} aria-current={isSources ? "page" : undefined} onClick={(e) => { e.preventDefault(); openScreen("sources"); }}><Files size={16} />Sources</a>
          <a href={`/verification${viewSearch(view)}`} aria-current={isVerification ? "page" : undefined} onClick={(e) => { e.preventDefault(); openScreen("verification"); }}><Shield size={16} />Verification</a>
          {session?.activity && <a href={`/activity${viewSearch(view)}`} aria-current={isActivity ? "page" : undefined} onClick={event=>{event.preventDefault();openScreen("activity");}}><ActivityIcon size={16}/>Activity</a>}
        </nav>
        <main id="workspace" className="workspace" tabIndex={-1}>
          {isActivity ? <Activity key={view.office} office={view.office} view={view} session={session} sessionError={sessionError} shortcutsEnabled={shortcutsEnabled}
            navigate={(patch,replace=true)=>navigate(patch,replace)} onHelp={()=>setShowShortcuts(true)}
            onSource={id=>openScreen("sources",{document:id,page:1,zoom:100,activityId:"",versionSource:""})}
            onJob={id=>openScreen("sources",{uploadJob:id,document:"",activityId:"",versionSource:""})}
            onFinding={id=>openScreen("findings",{finding:id,tag:"",source:"",pane:"detail",activityId:"",document:""})}
          /> : isComparisons ? <Comparisons key={view.office} view={view} session={session} sessionError={sessionError}
            navigate={(patch, replace = true) => navigate(patch, replace)} shortcutsEnabled={shortcutsEnabled} onHelp={() => setShowShortcuts(true)}
            onVerify={(office, id) => openScreen("verification", { office, verifyKind: "answer", verifyId: id, verifyTab: "check", verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "" })}
            onAnswer={(office, id) => openScreen("questions", { office, questionId: id || "", questionPanel: "recent", questionPane: id ? "answer" : "compose", questionCitation: "", document: "" })}
          /> : isQuestions ? <Questions key={view.office} office={view.office} session={session} sessionError={sessionError} view={view}
            navigate={(patch, replace = true) => navigate(patch, replace)} shortcutsEnabled={shortcutsEnabled}
            onHelp={() => setShowShortcuts(true)}
            onVerify={(id) => openScreen("verification", { verifyKind: "answer", verifyId: id, verifyTab: "check", verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "" })}
            onFinding={(id) => openScreen("findings", { finding: id, tag: "", source: "", pane: "detail", document: "" })}
          /> : isVerification ? <Verification key={view.office} office={view.office} view={view}
            navigate={(patch, replace = true) => navigate(patch, replace)} shortcutsEnabled={shortcutsEnabled}
            onHelp={() => setShowShortcuts(true)}
            onFinding={(id) => openScreen("findings", { finding: id, tag: "", source: "", pane: "detail", document: "" })}
          /> : isSources ? <Sources key={view.office} office={view.office} session={session}
            view={view} navigate={(patch, replace = true) => navigate(patch, replace)}
            shortcutsEnabled={shortcutsEnabled} onHelp={() => setShowShortcuts(true)}
            uploadRequest={uploadRequest}
            onUploadOpened={() => setUploadRequest(0)}
            onVerify={(id) => openScreen("verification", { verifyKind: "source", verifyTab: "check", verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyId: id, verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "" })}
            onFindings={(sourceId) => openScreen("findings", { forSource: sourceId, finding: "", tag: "", search: "", state: "all", type: "all", severity: "all", source: "", pane: "queue" })}
          /> : <>
          <div className="page-heading">
            <h1>Findings</h1>
            <div className="page-actions">
              <button
                className="button secondary shortcuts-button"
                aria-label="Keyboard shortcuts"
                title="Keyboard shortcuts (F1)"
                onClick={() => setShowShortcuts(true)}
                aria-keyshortcuts={shortcutsEnabled ? "F1 Shift+/" : "F1"}
              >
                <Keyboard size={16} />
                <span>Shortcuts</span>
                <ShortcutHint>F1</ShortcutHint>
              </button>
              <AutoRefreshButton enabled={view.autoRefresh} refreshing={loading} onToggle={toggleAutoRefresh}
                shortcutsEnabled={shortcutsEnabled} title="Checks every 10 seconds; pauses while editing or inspecting sources." />
            </div>
          </div>

          {view.forSource && <div className="notice"><Files size={17} /><span>Findings for {data?.sources.find((s) => s.source_id === view.forSource)?.source_identity || "the selected source"}</span><button className="text-button" onClick={() => filter({ forSource: "" })}>Show all findings</button></div>}
          {notice && (
            <div className="notice success" role="status">
              <CircleCheck size={18} />
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {error ? (
            <div className="workspace-error">
              <ErrorState error={error} retry={retry} />
            </div>
          ) : !data ? (
            <Loading />
          ) : (
            <>
              <div
                className={`investigation-layout ${view.pane === "detail" ? "show-detail" : ""}`}
              >
                <section className="queue" aria-label="Findings queue">
                  <div className="queue-heading">
                    <h2>
                      Review queue <span>{visible.length}</span>
                    </h2>
                    <Select
                      label="Sort"
                      shortcut={shortcutsEnabled ? "S" : undefined}
                      compact
                      triggerRef={sortRef}
                      icon={<ArrowDownWideNarrow size={15} />}
                      value={view.sort}
                      options={sortOptions.filter(option=>option.value!=="status")}
                      onChange={(value) =>
                        navigate({ sort: value as FindingSort }, true)
                      }
                    />
                  </div>
                  <label className="search-input">
                    <Search size={16} />
                    <span className="sr-only">Search findings</span>
                    <input
                      ref={searchRef}
                      placeholder="Search findings or #ID…"
                      aria-label="Search findings"
                      aria-keyshortcuts={shortcutsEnabled ? "/ Escape" : "Escape"}
                      value={view.search}
                      onChange={(event) =>
                        filter({ search: event.target.value })
                      }
                      onKeyDown={(event) => {
                        if (
                          event.key !== "Escape" ||
                          event.nativeEvent.isComposing ||
                          event.ctrlKey ||
                          event.metaKey ||
                          event.altKey ||
                          event.shiftKey
                        )
                          return;
                        event.preventDefault();
                        event.stopPropagation();
                        const target =
                          document.querySelector<HTMLElement>(
                            ".finding-list-item.selected",
                          ) || document.getElementById("workspace");
                        target?.focus({ preventScroll: true });
                        if (target?.matches(".finding-list-item"))
                          target.scrollIntoView({ block: "nearest" });
                      }}
                    />
                    {shortcutsEnabled && (
                      <span className="search-shortcuts" aria-hidden="true">
                        <ShortcutHint className="search-idle">/</ShortcutHint>
                        <ShortcutHint className="search-editing">Esc</ShortcutHint>
                      </span>
                    )}
                    {view.search && (
                      <button
                        className="icon-button"
                        aria-label="Clear search"
                        onClick={() => {
                          filter({ search: "" });
                          searchRef.current?.focus();
                        }}
                      >
                        <X size={14} />
                      </button>
                    )}
                  </label>
                  <div className="queue-filters">
                    <div>
                      <span>Severity</span>
                      <Select
                        label="Severity"
                        value={view.severity}
                        onChange={(value) => filter({ severity: value })}
                        options={[
                          { value: "all", label: "All severities" },
                          { value: "high", label: "High" },
                          { value: "review", label: "Interpretation" },
                          { value: "info", label: "Informational" },
                        ]}
                      />
                    </div>
                  </div>
                  <div className="type-filter">
                    <Select
                      label="Finding type"
                      value={view.type}
                      onChange={(value) => filter({ type: value })}
                      options={[
                        { value: "all", label: "All finding types" },
                        ...Object.entries(typeLabels).map(([value, label]) => ({
                          value,
                          label,
                        })),
                      ]}
                    />
                  </div>
                  <div className="queue-results" aria-live="polite">
                    <span>
                      {visible.length}{" "}
                      {visible.length === 1 ? "finding" : "findings"}
                    </span>
                    {shortcutsEnabled && (
                      <span
                        className="queue-navigation"
                        aria-hidden="true"
                        title="J: next finding · K: previous finding"
                      >
                        <ShortcutHint>J</ShortcutHint>
                        <ShortcutHint>K</ShortcutHint>
                        <span>navigate</span>
                      </span>
                    )}
                    {filtered && (
                      <button className="text-button" onClick={clearFilters}>
                        Clear filters
                      </button>
                    )}
                  </div>
                  <ul className="finding-list">
                    {visible.map((f) => (
                      <li key={f.finding_id}>
                        <button
                          className={`finding-list-item ${f.finding_id === selectedId ? "selected" : ""}`}
                          data-finding-id={f.finding_id}
                          aria-current={
                            f.finding_id === selectedId ? "true" : undefined
                          }
                          onClick={() => selectFinding(f)}
                        >
                          <div className="list-item-meta">
                            <span
                              className={`list-type ${f.severity === "high" ? "attention-text" : ""}`}
                            >
                              {f.severity === "high" && (
                                <span className="small-dot" />
                              )}
                              <Highlight
                                text={typeLabels[f.finding_type]}
                                query={view.search}
                              />
                            </span>
                            <ArrowRight size={14} />
                          </div>
                          <h3>
                            <Highlight text={findingTitle(f)} query={view.search} />
                          </h3>
                          <p>
                            <Highlight text={scopeLabel(f.affected_scope)} query={view.search} />
                          </p>
                          <QueueMatchContext finding={f} query={view.search} />
                          <div className="list-item-footer">
                            <ReviewBadge state={f.review_state} />
                            <span className="queue-finding-tag">
                              <Highlight
                                text={findingTag(f)}
                                query={view.search}
                                identifier
                              />
                            </span>
                            <time dateTime={f.created_at}>
                              {date(f.created_at).replace(/ \d{4}$/, "")}
                            </time>
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {!visible.length && (
                    <div className="queue-empty">
                      <Inbox size={26} />
                      <h3>
                        {unreviewedCount ? "No matching findings" : data.findings.length ? "All findings reviewed" : "No findings yet"}
                      </h3>
                      <p>
                        {unreviewedCount ? "Try a different search or clear the filters." : data.findings.length ? "No unreviewed findings remain." : "Findings will appear here after sources are processed."}
                      </p>
                      {filtered && (
                        <button className="text-button" onClick={clearFilters}>
                          Clear filters <ArrowRight size={14} />
                        </button>
                      )}
                    </div>
                  )}
                  <p className="queue-footnote">
                    <LockKeyhole size={12} />
                    Only evidence you can access is shown.
                  </p>
                </section>

                <div className="detail-container">
                  <button
                    className="text-button back-to-list"
                    onClick={() => {
                      navigate({ pane: "queue" });
                    }}
                  >
                    <ArrowLeft size={16} />
                    Back to findings
                  </button>
                  {view.finding &&
                    !visible.some((f) => f.finding_id === view.finding) &&
                    current && (
                      <div className="notice">
                        <AlertCircle size={17} />
                        <span>
                          {current.finding.review_state!=="open" ? "Reviewed finding" : "This finding is outside the current filters."}
                        </span>
                        <button
                          className="text-button"
                          onClick={() =>
                            navigate(
                              {
                                finding: "",
                                tag: "",
                                source: "",
                                pane: "queue",
                              },
                              true,
                            )
                          }
                        >
                          {current.finding.review_state!=="open" ? "Review queue" : "View results"}
                        </button>
                      </div>
                    )}
                  {data && (selection.ambiguous || selection.missingTag) ? (
                    <EmptyState
                      title={
                        selection.ambiguous
                          ? "This tag matches more than one finding"
                          : "Finding unavailable"
                      }
                    >
                      {selection.ambiguous
                        ? "Select the finding from the queue. Its full identifier will be included in the link."
                        : "This finding tag is unavailable in this office or your current access scope."}
                    </EmptyState>
                  ) : detailError ? (
                    <ErrorState
                      title="Finding unavailable"
                      error={detailError}
                      retry={retry}
                    />
                  ) : selectedId && !current ? (
                    <Loading label="Opening evidence…" />
                  ) : current ? (
                    <FindingDetail
                      key={`${view.office}-${selectedId}`}
                      finding={current.finding}
                      reviews={current.reviews}
                      sources={data.sources}
                      claims={data.claims}
                      office={view.office}
                      session={session}
                      onReview={setReviewAction}
                      onVerify={() => openScreen("verification", { verifyKind: "finding", verifyTab: "trace", verifyScope: "focused", verifyPane: "browse", verifyGroup: "", verifyId: current.id, verifyNode: "", verifyPassage: "", verifySearch: "", verifyChecks: "all", document: "" })}
                      shortcutsEnabled={shortcutsEnabled}
                      tab={view.tab}
                      onTabChange={(tab) => navigate({ tab }, true)}
                      sourceClause={view.source}
                      sourceMode={view.sourceMode}
                      sourcePage={view.page}
                      sourceZoom={view.zoom}
                      onSourceChange={(
                        source,
                        sourceMode = "details",
                        page = 1,
                        zoom = 100,
                      ) =>
                        navigate(
                          { source, sourceMode, page, zoom, pane: "detail" },
                          true,
                        )
                      }
                    />
                  ) : (
                    <EmptyState
                      icon={<Inbox size={28} />}
                      title={
                        filtered
                          ? "Nothing matches these filters"
                          : "No unreviewed findings"
                      }
                      action={
                        filtered ? (
                          <button
                            className="button secondary"
                            onClick={clearFilters}
                          >
                            Clear filters
                          </button>
                        ) : undefined
                      }
                    >
                      {filtered
                        ? "Adjust your search to find another issue."
                        : null}
                    </EmptyState>
                  )}
                </div>
              </div>
            </>
          )}
          </>}
        </main>
      </div>
      {showShortcuts && (
        <Modal
          title="Keyboard shortcuts"
          onClose={() => setShowShortcuts(false)}
          className="shortcuts-dialog"
        >
          <div className="dialog-body">
            <p className="dialog-description">
              Shortcuts pause while you type, use a dropdown, or have a dialog
              open. Review actions open a form; they never submit a decision
              immediately.
            </p>
            <dl className="shortcut-list">
              {shortcutDescriptions.map((item) => (
                <div key={item.keys}>
                  <dt>{item.label}</dt>
                  <dd>
                    <kbd>{item.keys}</kbd>
                  </dd>
                </div>
              ))}
            </dl>
            <label className="shortcut-preference">
              <input
                type="checkbox"
                checked={shortcutsEnabled}
                onChange={(event) => setShortcutsEnabled(event.target.checked)}
              />
              <span>
                Enable single-key shortcuts
                <small>
                  Turn off to avoid conflicts with assistive tools. F1 and
                  normal keyboard navigation still work.
                </small>
              </span>
            </label>
          </div>
        </Modal>
      )}
      {reviewAction && current && (
        <ReviewDialog
          action={reviewAction}
          finding={current.finding}
          office={view.office}
          onClose={() => setReviewAction(null)}
          onSaved={(state) => {
            setReviewAction(null);
            setNotice(
              `Review saved · ${humanize(state)}. The source evidence has been preserved.`,
            );
            setDetail((old) =>
              old
                ? { ...old, finding: { ...old.finding, review_state: state } }
                : old,
            );
            setWorkspace((old) =>
              old
                ? {
                    ...old,
                    findings: old.findings.map((f) =>
                      f.finding_id === current.id
                        ? { ...f, review_state: state }
                        : f,
                    ),
                  }
                : old,
            );
            retry();
          }}
        />
      )}
    </div>
  );
}

function ReviewDialog({
  action,
  finding,
  office,
  onClose,
  onSaved,
}: {
  action: ReviewAction;
  finding: Finding;
  office: Office;
  onClose: () => void;
  onSaved: (state: Finding["review_state"]) => void;
}) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const explanations = {
    acknowledge:
      "Record that you have seen and assessed this finding. It will remain available for follow-up.",
    resolve:
      "Explain what addressed the issue, such as corrected guidance or an updated procedure.",
    dismiss:
      "Explain why this finding needs no further action. The evidence and your decision remain in the record.",
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await reviewFinding(
        office,
        finding.finding_id,
        action,
        reason.trim(),
        finding.claim_revision_ids,
        finding.snapshot_id,
      );
      onSaved(result.new_state);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message +
              (error instanceof ApiError && error.status >= 500
                ? " Refresh the finding before retrying if the outcome is uncertain."
                : "")
          : "The review could not be saved.",
      );
      setSaving(false);
    }
  }
  return (
    <Modal
      title={`${humanize(action)} finding`}
      onClose={onClose}
      busy={saving}
    >
      <form
        onSubmit={submit}
        onKeyDown={(event) => {
          if (
            (event.ctrlKey || event.metaKey) &&
            event.key === "Enter" &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            if (reason.trim() && !saving) event.currentTarget.requestSubmit();
          }
        }}
      >
        <div className="dialog-body">
          <p className="review-dialog-finding">{findingTitle(finding)}</p>
          <p className="dialog-description">{explanations[action]}</p>
          <label className="reason-label" htmlFor="review-reason">
            Reason <span aria-hidden="true">Required</span>
          </label>
          <textarea
            id="review-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
            maxLength={4000}
            rows={5}
            placeholder="Describe your assessment and any action taken…"
            disabled={saving}
            aria-describedby="review-reason-help"
          />
          <p className="field-help" id="review-reason-help">
            Saved to review history under your configured reviewer identity.
          </p>
          {error && (
            <div className="notice warning" role="alert">
              <AlertCircle size={17} />
              <span>{error}</span>
            </div>
          )}
        </div>
        <footer className="dialog-footer">
          <button
            type="button"
            className="button secondary"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={!reason.trim() || saving}
            aria-keyshortcuts="Control+Enter Meta+Enter"
          >
            {saving ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Check size={16} />
            )}
            {saving ? "Saving review…" : `${humanize(action)} finding`}
          </button>
          <span className="submit-shortcut-hint">Ctrl / ⌘ + Enter</span>
        </footer>
      </form>
    </Modal>
  );
}
