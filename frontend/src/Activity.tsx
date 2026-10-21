import { useCallback, useEffect, useRef, useState } from "react";
import { Activity as ActivityIcon, AlertCircle, ArrowRight, ArrowUpRight, Clock3, Download, FileText, Globe2, Keyboard, Link, LoaderCircle, LockKeyhole, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { api } from "./api";
import { mergeActivity } from "./activityRecords";
import { AutoRefreshButton, EmptyState, ErrorState, Loading, Modal, ShortcutHint } from "./components";
import DateInput from "./DateInput";
import Highlight from "./Highlight";
import { matchingExcerpt } from "./searchHighlight";
import Select from "./Select";
import ShareLink from "./ShareLink";
import { date, humanize } from "./presentation";
import { fileSize } from "./uploads";
import { downloadJson } from "./verification";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import type { ActivityEvent, ActivityPage, Office, Session } from "./types";
import type { View } from "./viewState";
import "./activity.css";

const transferSize = (bytes: number) => bytes < 1024 ? `${bytes} B` : fileSize(bytes);
const categories = [{value:"all",label:"All activity"},{value:"transfer",label:"Data transfers"},{value:"processing",label:"Processing"},{value:"review",label:"Review decisions"},{value:"source",label:"Published sources"},{value:"withdrawal",label:"Source withdrawals"}];
const outcomes = ["delivered", "failed", "blocked", "timeout", "queued", "running", "succeeded", "needs_review", "acknowledged", "resolved", "dismissed", "published", "withdrawn", "reviewed"];
const icons = { transfer: Globe2, processing: Clock3, review: ShieldCheck, source: FileText, withdrawal: FileText };
function matchContext(event: ActivityEvent, query: string) {
  const value=query.trim().toLocaleLowerCase();
  if(!value||[event.title,event.description].some(text=>text?.toLocaleLowerCase().includes(value)))return "";
  return matchingExcerpt([event.id,event.outcome,...Object.values(event.details).map(item=>typeof item==="object"?JSON.stringify(item):String(item??""))].find(text=>text.toLocaleLowerCase().includes(value))||"",query);
}
const categoryName = { transfer: "Data transfer", processing: "Processing snapshot", review: "Review decision", source: "Source published", withdrawal: "Source withdrawn" };
export function activityQuery(view: View) {
  const params = new URLSearchParams({category:view.activityCategory, outcome:view.activityOutcome, q:view.activitySearch, limit:"40"});
  if(view.activitySince) params.set("since", `${view.activitySince}:00Z`);
  if(view.activityUntil) params.set("until", `${view.activityUntil}:59.999999Z`);
  return params.toString();
}
export default function Activity({ office, view, session, sessionError, shortcutsEnabled, navigate, onHelp, onSource, onJob, onFinding }: {
  office: Office; view: View; session: Session | null; sessionError: string; shortcutsEnabled: boolean;
  navigate: (patch: Partial<View>, replace?: boolean) => void; onHelp: () => void;
  onSource: (id:string) => void; onJob: (id:string) => void; onFinding: (id:string) => void;
}) {
  const [data, setData] = useState<ActivityPage | null>(null);
  const [pending, setPending] = useState(false), [appending, setAppending] = useState(false), [error, setError] = useState("");
  const [detail, setDetail] = useState<ActivityEvent | null>(null), [detailError, setDetailError] = useState("");
  const [sharing, setSharing] = useState(false);
  const [detailRevision,setDetailRevision]=useState(0);
  const search = useRef<HTMLInputElement>(null), request = useRef(0), controller = useRef<AbortController | null>(null), loadingMore = useRef(false), fetching = useRef(false), loadedQuery = useRef("");
  const canRead = !!session?.activity;
  const query = activityQuery(view);
  const load = useCallback(async (cursor = "") => {
    if (cursor && (loadingMore.current || fetching.current)) return;
    if (!cursor) controller.current?.abort();
    const abort = new AbortController(); controller.current = abort;
    const sequence = ++request.current; loadingMore.current = !!cursor;
    fetching.current = true;
    setPending(!cursor); setAppending(!!cursor); setError("");
    try {
      const page = await api<ActivityPage>(`${office}/activity?${query}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, {signal:abort.signal});
      if (sequence !== request.current || abort.signal.aborted) return;
      const sameQuery = loadedQuery.current === query;
      setData(previous => mergeActivity(previous,page,!!cursor,sameQuery && !!previous && previous.events.length>40));
      loadedQuery.current = query;
    } catch(e) { if (!abort.signal.aborted && sequence === request.current) setError(e instanceof Error ? e.message : "Activity could not be loaded."); }
    finally { if(sequence === request.current) { loadingMore.current = false; fetching.current = false; setPending(false); setAppending(false); } }
  },[office,query]);
  useEffect(() => {
    if (!canRead) return;
    controller.current?.abort(); ++request.current; setPending(true); setError("");
    const timer = window.setTimeout(() => void load(), 250);
    return () => { clearTimeout(timer); controller.current?.abort(); ++request.current; };
  },[load,canRead]);
  useEffect(() => {
    if (!canRead || !view.autoRefresh) return;
    const timer = window.setInterval(() => { if (!document.hidden && !document.querySelector("dialog[open], input:focus, [role=combobox][aria-expanded=true]") && !fetching.current) void load(); },10000);
    return () => clearInterval(timer);
  },[load,canRead,view.autoRefresh]);
  useEffect(() => {
    setDetailError(""); setDetail(null);
    if(!view.activityId || !canRead) return;
    const current = data?.events.find(event => event.id === view.activityId);
    if(current) {setDetail(current);return;}
    const abort = new AbortController();
    api<{event:ActivityEvent}>(`${office}/activity/${encodeURIComponent(view.activityId)}`,{signal:abort.signal}).then(result => {if(!abort.signal.aborted)setDetail(result.event);}).catch(e => {if(!abort.signal.aborted)setDetailError(e.message);});
    return () => abort.abort();
  },[view.activityId,office,canRead,data,detailRevision]);
  function exportLoaded() { if(data)downloadJson({office, filters:Object.fromEntries(new URLSearchParams(loadedQuery.current)), ...data},`${office}-activity.json`); }
  useKeyboardShortcuts(shortcutsEnabled && canRead,{search:()=>search.current?.focus(),refresh:()=>navigate({autoRefresh:!view.autoRefresh}),export:exportLoaded,share:()=>setSharing(true),help:onHelp});
  if(!session&&sessionError) return <ErrorState error={sessionError} retry={()=>window.location.reload()}/>;
  if(!session) return <Loading label="Checking activity access…" />;
  if(!canRead) return <EmptyState icon={<LockKeyhole size={28}/>} title="Audit access required">This workspace does not have permission to view activity.</EmptyState>;
  const stats = data?.summary;
  return <section className="activity-workspace">
    <div className="page-heading sources-heading"><h1>Activity</h1><div className="page-actions">
      <button className="button secondary shortcuts-button" onClick={onHelp}><Keyboard size={16}/>Shortcuts<ShortcutHint>F1</ShortcutHint></button>
      <AutoRefreshButton enabled={view.autoRefresh} refreshing={pending} shortcutsEnabled={shortcutsEnabled} title="Refreshes activity every 10 seconds." onToggle={()=>navigate({autoRefresh:!view.autoRefresh})}/>
      <button className="button secondary" disabled={!data} onClick={exportLoaded} aria-keyshortcuts={shortcutsEnabled ? "Shift+E":undefined}><Download size={15}/>Export loaded{shortcutsEnabled&&<ShortcutHint>Shift+E</ShortcutHint>}</button>
      <button className="button secondary" onClick={()=>setSharing(true)} aria-keyshortcuts={shortcutsEnabled ? "Shift+S":undefined}><Link size={15}/>Share view{shortcutsEnabled&&<ShortcutHint>Shift+S</ShortcutHint>}</button>
    </div></div>
    <div className="activity-summary" aria-label="Office transfer totals">
      <div><span><Globe2 size={16}/>Office transfers</span><strong>{stats ? stats.office_to_office_events.toLocaleString():"—"}</strong><small>{stats ? transferSize(stats.office_to_office_bytes):"—"} sent</small></div>
      <div><span><ArrowUpRight size={16}/>Hosted requests</span><strong>{stats ? stats.hosted_model_events.toLocaleString():"—"}</strong><small>{stats ? transferSize(stats.hosted_model_request_bytes):"—"} sent</small></div>
      <div><span><AlertCircle size={16}/>Blocked / failed transfers</span><strong>{stats ? `${stats.blocked_exports} / ${stats.failed_transfers}`:"—"}</strong><small>Office totals</small></div>
      <div><span><FileText size={16}/>Raw text between offices</span><strong>{stats ? transferSize(stats.raw_source_text_bytes_between_offices):"—"}</strong><small>Office totals</small></div>
    </div>
    <div className="activity-filters">
      <div className="search-input"><Search size={17}/><input ref={search} type="search" maxLength={200} value={view.activitySearch} aria-label="Search activity" placeholder="Search names, requests or reasons…" onChange={e=>navigate({activitySearch:e.target.value},true)} onKeyDown={e=>{if(e.key==="Escape")e.currentTarget.blur();}}/>{view.activitySearch ? <button className="icon-button" aria-label="Clear activity search" onClick={()=>{navigate({activitySearch:""});search.current?.focus();}}><X size={15}/></button>:shortcutsEnabled&&<ShortcutHint>/</ShortcutHint>}</div>
      <Select label="Activity type" value={view.activityCategory} options={categories} onChange={value=>navigate({activityCategory:value as View["activityCategory"]})}/>
      <Select label="Activity outcome" value={view.activityOutcome} options={[{value:"all",label:"All outcomes"},...outcomes.map(value=>({value,label:humanize(value)}))]} onChange={value=>navigate({activityOutcome:value})}/>
      <div className="activity-date-range"><label className="activity-date">From · UTC<DateInput type="datetime-local" value={view.activitySince} onChange={e=>navigate({activitySince:e.target.value})}/>{view.activitySince&&<button className="text-button" onClick={()=>navigate({activitySince:""})}>Clear start date</button>}</label>
      <label className="activity-date">To · UTC<DateInput type="datetime-local" value={view.activityUntil} min={view.activitySince} onChange={e=>navigate({activityUntil:e.target.value})}/>{view.activityUntil&&<button className="text-button" onClick={()=>navigate({activityUntil:""})}>Clear end date</button>}</label></div>
    </div>
    <div className="activity-list-status"><span role="status" title={error}>{error && <span className="sr-only">{error}</span>}{pending ? "Refreshing activity…" : error && data ? "Refresh failed · showing previous results" : data ? `${data.events.length} records loaded${data.next_cursor ? " · more available":""}`:""}</span><button className="icon-button" aria-label="Refresh activity" disabled={pending||appending} onClick={()=>void load()}><RefreshCw size={17} className={pending?"spin":""}/></button></div>
    {!data ? pending ? <Loading label="Loading activity…"/>:error ? <ErrorState error={error} retry={()=>void load()}/>:null : data.events.length ? <ol className="activity-records">{data.events.map(event=>{const Icon=icons[event.category];return <li key={event.id}><button className="activity-record" onClick={()=>navigate({activityId:event.id},false)}><span className="activity-record-icon"><Icon size={18}/></span><span className="activity-record-body"><span className="activity-record-type">{categoryName[event.category]}</span><strong><Highlight text={event.title||"Source"} query={view.activitySearch}/></strong><span className="activity-record-description"><Highlight text={event.description} query={view.activitySearch}/></span>{matchContext(event,view.activitySearch)&&<span className="activity-match-context"><Highlight text={matchContext(event,view.activitySearch)} query={view.activitySearch}/></span>}</span><span className="activity-record-meta"><span className={`activity-outcome outcome-${event.outcome}`}>{humanize(event.outcome)}</span><time dateTime={event.created_at}>{date(event.created_at,true)}</time></span><ArrowRight size={15}/></button></li>;})}</ol>:<EmptyState icon={<ActivityIcon size={27}/>} title={data.next_cursor?"No matches in this page":"No activity found"} children={null} action={<button className="button secondary" onClick={()=>navigate({activitySearch:"",activityCategory:"all",activityOutcome:"all",activitySince:"",activityUntil:""})}>Clear filters</button>}/>}
    {data?.next_cursor&&<div className="activity-more"><button className="button secondary" disabled={pending||appending} onClick={()=>void load(data.next_cursor)}>{appending&&<LoaderCircle className="spin" size={15}/>}Load more activity</button></div>}
    {view.activityId&&<Modal title="Activity details" onClose={()=>navigate({activityId:""})} className="activity-detail-dialog"><div className="dialog-body">{detailError?<ErrorState error={detailError} retry={()=>setDetailRevision(n=>n+1)}/>:!detail?<Loading label="Opening activity…"/>:<><div className="activity-detail-heading"><h3>{detail.title||"Source"}</h3><span className={`activity-outcome outcome-${detail.outcome}`}>{humanize(detail.outcome)}</span></div><p className="activity-detail-date">{categoryName[detail.category]} · {date(detail.created_at,true)}</p><dl className="activity-details"><dt>Event ID</dt><dd>{detail.id}</dd>{Object.entries(detail.details).map(([key,value])=><div key={key}><dt>{humanize(key)}</dt><dd>{value===null||value==="" ? "—":typeof value==="object"?<pre>{JSON.stringify(value,null,2)}</pre>:String(value)}</dd></div>)}</dl></>}</div>{detail&&<footer className="dialog-footer"><button className="button secondary" onClick={()=>downloadJson(detail,`${office}-${detail.id.replace(":","-")}.json`)}><Download size={15}/>Export record</button>{detail.category==="review"?<button className="button secondary" onClick={()=>onFinding(detail.target_id)}>Open finding<ArrowRight size={15}/></button>:(detail.category==="source"||detail.category==="withdrawal")?<button className="button secondary" onClick={()=>onSource(detail.target_id)}>Inspect source<ArrowRight size={15}/></button>:detail.category==="processing"?<button className="button secondary" onClick={()=>onJob(detail.target_id)}>View processing<ArrowRight size={15}/></button>:typeof detail.details.request_id==="string"&&<button className="button secondary" onClick={()=>navigate({activitySearch:detail.details.request_id as string,activityId:"",activityCategory:"all",activityOutcome:"all",activitySince:"",activityUntil:""})}>Show request activity<Search size={15}/></button>}</footer>}</Modal>}
    {sharing&&<Modal title="Share Activity view" onClose={()=>setSharing(false)}><div className="dialog-body"><ShareLink/></div></Modal>}
  </section>;
}
