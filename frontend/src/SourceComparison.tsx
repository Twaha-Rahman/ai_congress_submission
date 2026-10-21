import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, ArrowLeftRight, ArrowUpRight, FileText, GitCompareArrows, Link, Search, X } from "lucide-react";
import { api } from "./api";
import { EmptyState, ErrorState, Loading, Modal, ShortcutHint } from "./components";
import { versionTextRuns } from "./sourceVersions";
import Select from "./Select";
import ShareLink from "./ShareLink";
import { date, humanize, sourceTitle } from "./presentation";
import { downloadJson } from "./verification";
import type { Office, Source, VersionDiff, VersionPassage } from "./types";
import type { View } from "./viewState";
import "./sourceComparison.css";

export function metadataValue(value: unknown): string {
  if(value===null||value===undefined)return "Not set";
  if(typeof value==="boolean")return value?"Yes":"No";
  if(typeof value==="string")return /^\d{4}-\d{2}-\d{2}T/.test(value)?date(value,true).replace(" UTC",`:${value.slice(17,19)}${value.match(/\.\d+/)?.[0]||""} UTC`):value;
  if(Array.isArray(value))return value.length?value.map(metadataValue).join(" · "):"None";
  if(typeof value==="object")return Object.entries(value).map(([key,item])=>`${humanize(key)}: ${metadataValue(item)}`).join("\n");
  return String(value);
}
export default function SourceComparison({office,view,navigate,shortcutsEnabled,onInspect,onClose}:{
  office:Office;view:View;navigate:(patch:Partial<View>,replace?:boolean)=>void;shortcutsEnabled:boolean;
  onInspect:(id:string,passage?:VersionPassage)=>void;onClose:()=>void;
}) {
  const [versions,setVersions]=useState<Source[]|null>(null),[diff,setDiff]=useState<VersionDiff|null>(null);
  const [error,setError]=useState(""),[versionError,setVersionError]=useState(""),[revision,setRevision]=useState(0),[pending,setPending]=useState(false),[sharing,setSharing]=useState(false);
  const search=useRef<HTMLInputElement>(null);
  useEffect(()=>{const abort=new AbortController();setVersions(null);setVersionError("");
    api<{sources:Source[]}>(`${office}/sources/${encodeURIComponent(view.versionSource)}/versions`,{signal:abort.signal}).then(result=>{if(!abort.signal.aborted)setVersions(result.sources);}).catch(e=>{if(!abort.signal.aborted)setVersionError(e.message);});return()=>abort.abort();
  },[office,view.versionSource,revision]);
  useEffect(()=>{
    if(!versions?.length||view.versionBase&&view.versionNext)return;
    const selected=versions.find(source=>source.source_id===view.versionSource)||versions[0];
    const index=versions.indexOf(selected),older=versions[index+1]||versions.find(source=>source.source_id!==selected.source_id);
    if(older)navigate({versionBase:view.versionBase||older.source_id,versionNext:view.versionNext||selected.source_id},true);
  },[versions,view.versionBase,view.versionNext,view.versionSource]);
  useEffect(()=>{
    setDiff(null);setError("");if(!view.versionBase||!view.versionNext||!versions)return;
    if(!versions.some(source=>source.source_id===view.versionBase)||!versions.some(source=>source.source_id===view.versionNext)){setError("One of these versions is unavailable to this workspace.");return;}
    const abort=new AbortController();setPending(true);
    api<VersionDiff>(`${office}/sources/${encodeURIComponent(view.versionBase)}/diff?other=${encodeURIComponent(view.versionNext)}`,{signal:abort.signal}).then(result=>{if(!abort.signal.aborted)setDiff(result);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setPending(false);});return()=>abort.abort();
  },[office,versions,view.versionBase,view.versionNext]);
  useEffect(()=>{
    function key(event:KeyboardEvent){
      if(!shortcutsEnabled||view.document||event.defaultPrevented||event.repeat||event.isComposing||event.ctrlKey||event.metaKey||event.altKey||!document.querySelector("dialog.version-dialog[open]"))return;
      if(event.target instanceof Element&&event.target.closest("input, textarea, [role=combobox], [role=listbox]"))return;
      if(event.key==="/"){event.preventDefault();search.current?.focus();}
      if(event.key==="S"){event.preventDefault();setSharing(true);}
      if(event.key==="E"&&diff){event.preventDefault();downloadJson(diff,`${office}-source-versions.json`);}
    }
    document.addEventListener("keydown",key);return()=>document.removeEventListener("keydown",key);
  },[shortcutsEnabled,view.document,diff,office]);
  const visible=useMemo(()=>diff?.passages.map((passage,index)=>({...passage,index})).filter(passage=>(view.versionFilter==="all"||view.versionFilter==="changes"&&passage.kind!=="unchanged"||passage.kind===view.versionFilter)&&(!view.versionSearch.trim()||[passage.before?.text,passage.after?.text,passage.before?.section,passage.after?.section].some(value=>value?.toLocaleLowerCase().includes(view.versionSearch.trim().toLocaleLowerCase()))))||[],[diff,view.versionFilter,view.versionSearch]);
  const options=versions?.map(source=>({value:source.source_id,label:`${source.version_label} · Added ${date(source.ingested_at)}`}))||[];
  const changes=diff?diff.counts.added+diff.counts.removed+diff.counts.changed:0;
  const title=versions?.[0]?sourceTitle(versions[0]):"";
  if(view.document)return null;
  return <Modal title="Compare source versions" onClose={onClose} className="version-dialog">
    <div className="dialog-body version-body">
      {versionError?<ErrorState error={versionError} retry={()=>setRevision(n=>n+1)}/>:!versions?<Loading label="Loading accessible versions…"/>:versions.length<2?<EmptyState icon={<GitCompareArrows size={28}/>} title="One version available">{title} has no other accessible version to compare.</EmptyState>:<>
        <div className="version-source-heading"><FileText size={19}/><h3>{title}</h3></div>
        <div className="version-selection"><label>Base<Select label="Base version" value={view.versionBase} options={options.filter(option=>option.value!==view.versionNext)} onChange={value=>navigate({versionBase:value},false)}/></label><button className="icon-button version-swap" aria-label="Swap compared versions" title="Swap versions" onClick={()=>navigate({versionBase:view.versionNext,versionNext:view.versionBase},false)}><ArrowLeftRight size={18}/></button><label>Compared<Select label="Compared version" value={view.versionNext} options={options.filter(option=>option.value!==view.versionBase)} onChange={value=>navigate({versionNext:value},false)}/></label></div>
        {error?<ErrorState error={error} retry={()=>setRevision(n=>n+1)}/>:pending||!diff?<Loading label="Comparing preserved text…"/>:<>
          <div className="version-overview"><span>{diff.same_file?"Identical original files":diff.same_text?"Original files differ · parsed text is identical":"Original files and parsed text differ"}</span><span>{diff.explicit_replacement?`Replacement declared for ${diff.before.version_label}`:"No replacement of the base version is declared by the compared version"}</span></div>
          <div className="version-counts" aria-label="Passage changes">{(["added","removed","changed","unchanged"] as const).map(kind=><button key={kind} className={`version-count ${view.versionFilter===kind?"selected":""}`} aria-pressed={view.versionFilter===kind} onClick={()=>navigate({versionFilter:view.versionFilter===kind?"changes":kind})}><strong>{diff.counts[kind]}</strong>{humanize(kind)}</button>)}</div>
          <details className="version-metadata" key={`${view.versionBase}:${view.versionNext}`}><summary>Metadata changes <span>{diff.metadata.length}</span></summary>{diff.metadata.length?<div className="version-metadata-table"><div className="version-metadata-header"><span>Field</span><span>Base · {diff.before.version_label}</span><span>Compared · {diff.after.version_label}</span></div>{diff.metadata.map(change=><div key={change.field} className="version-metadata-row"><strong>{humanize(change.field)}</strong><div><span className="version-mobile-label">Base</span>{metadataValue(change.before)}</div><div><span className="version-mobile-label">Compared</span>{metadataValue(change.after)}</div></div>)}</div>:<p>No changes to authority, applicability, dates or permissions.</p>}</details>
          <div className="version-text-heading"><h3>Parsed text</h3><span>{visible.length} of {diff.passages.length} aligned passages</span></div>
          <div className="version-tools"><div className="search-input"><Search size={16}/><input ref={search} type="search" aria-label="Search compared passages" aria-keyshortcuts={shortcutsEnabled?"/":undefined} value={view.versionSearch} onChange={e=>navigate({versionSearch:e.target.value},true)} placeholder="Search passages…"/>{view.versionSearch&&<button className="icon-button" aria-label="Clear passage search" onClick={()=>{navigate({versionSearch:""});search.current?.focus();}}><X size={14}/></button>}{shortcutsEnabled&&!view.versionSearch&&<ShortcutHint>/</ShortcutHint>}</div><Select label="Passage changes" value={view.versionFilter} options={[{value:"changes",label:"Changes only"},{value:"all",label:"All passages"},...(["added","removed","changed","unchanged"] as const).map(value=>({value,label:humanize(value)}))]} onChange={value=>navigate({versionFilter:value as View["versionFilter"]})}/></div>
          <div className="version-column-headings"><span>Base <span className="source-version">{diff.before.version_label}</span></span><span>Compared <span className="source-version">{diff.after.version_label}</span></span></div>
          {visible.length?<ol className="version-passages">{visible.map(passage=><li key={passage.index} className={`version-passage change-${passage.kind}`}><div className="version-passage-status"><span>{humanize(passage.kind)}</span></div>{(["before","after"] as const).map(side=>{const part=passage[side],source=diff[side];return <section key={side} className={`version-passage-side ${side}`} aria-label={`${side==="before"?"Base":"Compared"} passage ${passage.index+1}`}><div className="version-passage-location"><span>{part?`Page ${part.page}${part.section?` · § ${part.section}`:""}`:"No passage"}</span>{part&&<button className="text-button" onClick={()=>onInspect(source.source_id,part)}>Inspect<ArrowUpRight size={13}/></button>}</div>{part?<p>{versionTextRuns(passage,side,view.versionSearch).map((run,index)=>run.kind==="unchanged"&&!run.matched?<span key={index}>{run.text}</span>:<mark key={index} className={`${run.kind!=="unchanged"?`diff-${run.kind}`:""}${run.matched?" search-match":""}`}>{run.text}</mark>)}</p>:<p className="version-missing">—</p>}</section>;})}</li>)}</ol>:<EmptyState icon={<GitCompareArrows size={26}/>} title={changes===0&&!view.versionSearch?"No text changes":"No passages match"} children={null} action={<button className="button secondary" onClick={()=>navigate({versionFilter:"all",versionSearch:""})}>Show all passages</button>}/>}
        </>}
      </>}
    </div>
    <footer className="dialog-footer version-footer"><button className="button secondary" onClick={()=>setSharing(true)} aria-keyshortcuts={shortcutsEnabled?"Shift+S":undefined}><Link size={15}/><span className="version-desktop-label">Share comparison</span><span className="version-mobile-label">Share</span>{shortcutsEnabled&&<ShortcutHint>Shift+S</ShortcutHint>}</button>{diff&&<><button className="button secondary" onClick={()=>downloadJson(diff,`${office}-source-versions.json`)} aria-keyshortcuts={shortcutsEnabled?"Shift+E":undefined}><ArrowDownToLine size={15}/><span className="version-desktop-label">Export comparison</span><span className="version-mobile-label">Export</span>{shortcutsEnabled&&<ShortcutHint>Shift+E</ShortcutHint>}</button><button className="button secondary" onClick={()=>onInspect(diff.before.source_id)}>Inspect {diff.before.version_label}</button><button className="button secondary" onClick={()=>onInspect(diff.after.source_id)}>Inspect {diff.after.version_label}</button></>}</footer>
    {sharing&&<div className="version-share"><div><strong>Comparison link</strong><button type="button" className="icon-button" aria-label="Close comparison link" onClick={()=>setSharing(false)}><X size={15}/></button></div><ShareLink/></div>}
  </Modal>;
}
