import { useEffect, useRef, useState } from "react";
import { AlertCircle, Check, Clock3, ExternalLink, Hash, LoaderCircle, MessageSquare, Pause, Play, Plus, Pencil, RefreshCw, Trash2, Wifi, WifiOff, ArrowLeft } from "lucide-react";
import { api } from "./api";
import { Modal } from "./components";
import Select from "./Select";
import { date, humanize } from "./presentation";
import type { Office } from "./types";
import "./slack.css";

type Channel = { channel_id: string; channel_name: string; policy_family: string; scope: { kind: "policy"; description: string; attributes: Record<string, string> }; sensitivity: string; hosted_model: boolean; office_export: boolean };
type Connection = { configured: boolean; state: string; paused: boolean; workspace: { id: string | null; name: string | null }; error: string | null; channels: Channel[]; counts: Record<string, number>; last_event_at: string | null; coverage_gap_at?: string | null; recent: { event_id: string; channel_id: string; status: string; reason: string | null; job_id: string | null; received_at: string }[] };
const emptyChannel = (): Channel => ({ channel_id: "", channel_name: "Channel", policy_family: "", scope: { kind: "policy", description: "", attributes: {} }, sensitivity: "restricted", hosted_model: false, office_export: false });

export default function SlackConnection({ office, onClose, onJob }: { office: Office; onClose: () => void; onJob: (id: string) => void }) {
  const [data, setData] = useState<Connection>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState<Channel>();
  const [editing, setEditing] = useState(false);
  const sequence = useRef(0);
  const current = useRef(true);
  async function load() {
    const n = ++sequence.current; setLoading(true);
    try { const next = await api<Connection>(`${office}/integrations/slack`); if (current.current && n === sequence.current) { setData(next); setError(""); } }
    catch (e) { if (current.current && n === sequence.current) setError(e instanceof Error ? e.message : "Slack status could not be loaded."); }
    finally { if (current.current && n === sequence.current) setLoading(false); }
  }
  useEffect(() => { current.current = true; void load(); return () => { current.current = false; sequence.current++; }; }, [office]);
  useEffect(() => { const timer = window.setInterval(() => { if (!document.hidden && !draft && !saving) void load(); }, 10000); return () => clearInterval(timer); }, [office, draft, saving]);
  async function change(body: unknown) {
    if (saving) return;
    sequence.current++; setLoading(false); setSaving(true); setError(""); setMessage("");
    try { const next = await api<Connection>(`${office}/integrations/slack`, { method: "POST", body: JSON.stringify(body) }); if (current.current) { setData(next); setDraft(undefined); setMessage("Settings saved."); } }
    catch (e) { if (current.current) setError(e instanceof Error ? e.message : "Slack settings could not be saved."); }
    finally { if (current.current) setSaving(false); }
  }
  const state = !data ? "Loading" : data.paused ? "Paused" : data?.state === "connected" ? "Connected" : data?.state === "connecting" ? "Connecting" : data?.configured ? "Disconnected" : "Not configured";
  return <Modal title="Slack connection" className="slack-dialog" onClose={onClose}>
    <div className="slack-body">
      <div className="slack-heading"><div><MessageSquare size={20} /><div><h3>{data?.workspace.name || `${humanize(office)} office`}</h3><span className="slack-status">{state === "Connected" ? <Wifi size={13} /> : state === "Paused" ? <Pause size={13} /> : <WifiOff size={13} />}{state}</span></div></div><button className="icon-button" aria-label="Refresh Slack status" title="Refresh Slack status" disabled={loading || saving} onClick={() => void load()} aria-busy={loading}><RefreshCw size={16} className={loading ? "spin" : ""} /></button></div>
      <div className="slack-feedback" aria-live="polite">{error || data?.error ? <span role="alert"><AlertCircle size={14} />{error || data?.error}</span> : message ? <span><Check size={14} />{message}</span> : null}</div>
      {!data && loading ? <p className="slack-loading"><LoaderCircle size={17} className="spin" />Loading connection…</p> : data && !data.configured ? <p className="slack-unconfigured">Slack app credentials have not been configured for this office.</p> : data && <>
        {draft ? <form onSubmit={event => { event.preventDefault(); void change({ action: "save_channel", channel: draft }); }}>
          <div className="slack-section-heading"><button type="button" className="text-button" disabled={saving} onClick={() => setDraft(undefined)}><ArrowLeft size={14} />Channels</button><h4>{editing ? "Edit channel" : "Add channel"}</h4></div>
          <fieldset disabled={saving} className="slack-fields">
            <label>Channel ID<input autoFocus={!editing} readOnly={editing} required pattern="C[A-Z0-9]{2,30}" placeholder="C0123456789" value={draft.channel_id} onChange={e => setDraft({ ...draft, channel_id: e.target.value.trim().toUpperCase() })} autoComplete="off" /></label>
            <label>Policy family<input autoFocus={editing} required maxLength={128} placeholder="People operations" value={draft.policy_family} onChange={e => setDraft({ ...draft, policy_family: e.target.value })} /></label>
            <label>Applies to<input required maxLength={1000} placeholder="Dhaka office employees" value={draft.scope.description} onChange={e => setDraft({ ...draft, scope: { ...draft.scope, description: e.target.value } })} /></label>
            <div><label>Readers</label><Select label="Slack source readers" value={draft.sensitivity} onChange={value => setDraft({ ...draft, sensitivity: value })} options={[{ value: "restricted", label: "Restricted readers" }, { value: "demo_shareable", label: "Office readers" }]} /></div>
            <label className="slack-check"><input type="checkbox" checked={draft.hosted_model} onChange={e => setDraft({ ...draft, hosted_model: e.target.checked })} />Allow hosted-model processing</label>
            <label className="slack-check"><input type="checkbox" checked={draft.office_export} onChange={e => setDraft({ ...draft, office_export: e.target.checked })} />Allow structured claim export to other offices</label>
          </fieldset>
          <div className="slack-form-actions"><button type="button" className="button secondary" disabled={saving} onClick={() => setDraft(undefined)}>Cancel</button><button className="button primary" disabled={saving}>{saving ? <LoaderCircle size={15} className="spin" /> : <Plus size={15} />}{editing ? "Save changes" : "Monitor channel"}</button></div>
        </form> : <>
          <div className="slack-summary"><span><Clock3 size={14} />{data.last_event_at ? `Last event ${date(data.last_event_at, true)}` : "No events received"}</span><span>{(data.counts.pending || 0) + (data.counts.queued || 0) + (data.counts.running || 0)} pending</span></div>
          {data.coverage_gap_at && <p className="slack-gap"><AlertCircle size={14} />Connection interrupted {date(data.coverage_gap_at, true)}. Messages sent while offline may be missing.</p>}
          <div className="slack-section-heading"><h4>Monitored channels <span>{data.channels.length}</span></h4><button className="button secondary" disabled={saving} onClick={() => { setMessage(""); setEditing(false); setDraft(emptyChannel()); }}><Plus size={14} />Add channel</button></div>
          {!data.channels.length ? <p className="slack-empty">Add a public channel the Slack app has joined.</p> : <ul className="slack-channel-list">{data.channels.map(channel => <li key={channel.channel_id}><Hash size={16} /><div><strong>{channel.channel_name}</strong><p>{channel.policy_family} · {channel.scope.description}</p><small>{channel.sensitivity === "restricted" ? "Restricted readers" : "Office readers"} · {channel.hosted_model ? "Hosted processing allowed" : "Local processing only"}{channel.office_export ? " · Export allowed" : ""}</small></div><button className="icon-button" title={`Edit ${channel.channel_name}`} aria-label={`Edit ${channel.channel_name}`} disabled={saving} onClick={() => { setEditing(true); setMessage(""); setDraft(channel); }}><Pencil size={15} /></button><button className="icon-button" title={`Stop monitoring ${channel.channel_name}`} aria-label={`Stop monitoring ${channel.channel_name}`} disabled={saving} onClick={() => void change({ action: "remove_channel", channel_id: channel.channel_id })}><Trash2 size={15} /></button></li>)}</ul>}
          <div className="slack-pause"><button className="button secondary" disabled={saving} onClick={() => void change({ action: data.paused ? "resume" : "pause" })}>{saving ? <LoaderCircle size={14} className="spin" /> : data.paused ? <Play size={14} /> : <Pause size={14} />}{data.paused ? "Resume processing" : "Pause processing"}</button></div>
          {!!data.recent.length && <section className="slack-activity"><h4>Recent activity</h4><ul>{data.recent.map(event => <li key={event.event_id}><div><strong>{data.channels.find(c => c.channel_id === event.channel_id)?.channel_name || event.channel_id}</strong><span>{humanize(event.status)}</span></div>{event.reason && <p>{event.reason}</p>}<div><time dateTime={event.received_at}>{date(event.received_at, true)}</time>{event.job_id && <button className="text-button" onClick={() => onJob(event.job_id!)}>View processing<ExternalLink size={12} /></button>}</div></li>)}</ul></section>}
        </>}
      </>}
    </div>
  </Modal>;
}
