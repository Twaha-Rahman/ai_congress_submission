import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, ArrowDownToLine, ArrowUpFromLine, Check, Clock3, Hash, LoaderCircle, LockKeyhole, MessageSquare } from "lucide-react";
import { api, ApiError } from "./api";
import { Modal, SubmitShortcutHint } from "./components";
import Select from "./Select";
import { date, humanize } from "./presentation";
import { downloadJson } from "./verification";
import { fileSize } from "./uploads";
import { parseSavedSlack, buildSavedSlackManifest, maxSlackBytes, type SavedSlackData } from "../shared/slackImport.mjs";
import type { Office, Session, UploadJob } from "./types";
import "./slackImport.css";

const blank = () => ({ name: "", version: "v1", family: "", scope: "", sensitivity: "restricted", hosted: false });
export default function ImportSlack({ open, office, config, onClose, onQueued }: {
  open: boolean; office: Office; config?: NonNullable<Session["uploads"]>[Office];
  onClose: () => void; onQueued: (job: UploadJob) => void;
}) {
  const [draft, setDraft] = useState(blank);
  const [file, setFile] = useState<File>();
  const [saved, setSaved] = useState<SavedSlackData>();
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const name = useRef<HTMLInputElement>(null);
  const alert = useRef<HTMLDivElement>(null);
  const version = useRef(0);
  const depth = useRef(0);
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; version.current++; }; }, []);
  const hosted = config?.processing !== "local";
  const canSubmit = !!saved && !checking && !saving && !!config?.enabled;
  const rangeLabel = saved ? [...new Set([date(saved.oldest, true), date(saved.newest, true)])].join(" — ") : "";
  function edit(key: keyof ReturnType<typeof blank>, value: string | boolean) { setDraft(current => ({ ...current, [key]: value })); }
  async function choose(files: File[]) {
    const n = ++version.current;
    setFile(undefined); setSaved(undefined); setFileError(""); setError(""); setChecking(false);
    if (files.length !== 1) { setFileError("Choose one saved Slack JSON file at a time."); return; }
    const next = files[0];
    if (!next.size || next.size > maxSlackBytes) { setFileError(!next.size ? "This file is empty." : "Choose a saved Slack file smaller than 5 MB."); return; }
    setChecking(true);
    try {
      const parsed = parseSavedSlack(new TextDecoder("utf-8", { fatal: true }).decode(await next.arrayBuffer()));
      if (!mounted.current || n !== version.current) return;
      setFile(next); setSaved(parsed);
      setDraft(current => ({ ...current, name: current.name || next.name.replace(/\.json$/i, "").replace(/[_-]+/g, " ").slice(0, 128) }));
      requestAnimationFrame(() => name.current?.focus());
    } catch (e) {
      if (mounted.current && n === version.current) setFileError(e instanceof TypeError ? "The file must contain UTF-8 JSON text." : e instanceof Error ? e.message : "This saved file could not be read.");
    } finally { if (mounted.current && n === version.current) setChecking(false); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || lock.current) return;
    setError(""); let sent = false;
    try {
      if (hosted && !draft.hosted) throw new Error("Allow hosted-model processing to import these messages with the configured model.");
      const manifest = buildSavedSlackManifest({ source_identity: draft.name, version_label: draft.version,
        policy_family: draft.family, scope: { kind: "policy", description: draft.scope, attributes: {} },
        sensitivity: draft.sensitivity, permissions: { hosted_model: hosted && draft.hosted } }, saved!.newest);
      lock.current = true; setSaving(true); sent = true;
      const result = await api<{ job: UploadJob }>(`${office}/ingestions/slack`, { method: "POST", body: JSON.stringify({ manifest, payload: saved!.payload }) });
      if (!mounted.current) return;
      if (!result.job?.job_id) throw new Error("The office did not confirm a processing job.");
      setDraft(blank()); setFile(undefined); setSaved(undefined); onQueued(result.job);
    } catch (e) {
      if (!mounted.current) return;
      setError((e instanceof Error ? e.message : "The saved messages could not be imported.") +
        (sent && (!(e instanceof ApiError) || e.status >= 500) ? " Check recent activity before retrying; the office may have received the import." : ""));
      requestAnimationFrame(() => alert.current?.focus());
    } finally { lock.current = false; if (mounted.current) setSaving(false); }
  }
  if (!open) return null;
  return <Modal title="Import saved Slack" onClose={onClose} busy={saving} className="upload-dialog slack-import-dialog">
    <form onSubmit={submit} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); if (canSubmit) event.currentTarget.requestSubmit(); } }}>
      <div className="upload-scroll"><fieldset disabled={saving} className="upload-fields"><div className="dialog-body upload-body">
        <div className="upload-office"><span><MessageSquare size={14} />{humanize(office)} office</span><span>JSON · up to 5 MB</span></div>
        <input ref={input} type="file" accept=".json,application/json" className="sr-only" tabIndex={-1} aria-label="Choose saved Slack JSON file" onChange={event => { void choose(Array.from(event.target.files || [])); event.target.value = ""; }} />
        <div className={`upload-dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
          onDragEnter={event => { event.preventDefault(); if (!saving) { depth.current++; setDragging(true); } }}
          onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
          onDragLeave={event => { event.preventDefault(); if (--depth.current <= 0) { depth.current = 0; setDragging(false); } }}
          onDrop={event => { event.preventDefault(); depth.current = 0; setDragging(false); if (!saving) void choose(Array.from(event.dataTransfer.files)); }}>
          <button type="button" className="upload-file-button" onClick={() => input.current?.click()} aria-describedby="slack-file-help slack-file-error"><span className="upload-file-icon">{checking ? <LoaderCircle size={23} className="spin" /> : file ? <MessageSquare size={23} /> : <ArrowUpFromLine size={23} />}</span><span><strong>{file ? file.name : checking ? "Checking messages…" : "Choose saved Slack JSON or drop it here"}</strong><span>{file ? `${fileSize(file.size)} · Click to change` : "Select a saved event or message batch"}</span></span>{file && <Check className="upload-file-check" size={18} />}</button>
        </div>
        <div className="slack-file-help"><p className="upload-hint" id="slack-file-help">Up to 200 text messages from one channel. Full workspace ZIP exports are not supported.</p><button type="button" className="text-button" onClick={() => downloadJson({ channel: { id: "C_EXAMPLE", name: "team-guidance" }, event: { type: "message", ts: "2026-10-21T09:00:00Z", user: "U_EXAMPLE", text: "Employees submit travel expenses through the company portal." } }, "saved-slack-example.json")}><ArrowDownToLine size={13} />Download example</button></div>
        <p id="slack-file-error" className="upload-file-error" role="status">{fileError || "\u00a0"}</p>
        {saved && <section className="slack-import-summary" aria-label="Saved message preview"><div><span><Hash size={14} />{saved.channelLabel.replace(/^#/, "")}</span><span><MessageSquare size={14} />{saved.count} {saved.count === 1 ? "message" : "messages"}</span></div><p title={`${saved.oldest} — ${saved.newest}`}><Clock3 size={14} />{rangeLabel}</p><details><summary>Preview messages</summary><ol>{saved.payload.events.slice(0, 3).map((message, i) => <li key={i}>{message.text.length > 240 ? `${message.text.slice(0, 240)}…` : message.text}</li>)}</ol>{saved.count > 3 && <small>{saved.count - 3} more messages</small>}</details></section>}
        <div className="upload-form-grid">
          <label className="upload-field"><span className="upload-label">Source name<span>Required</span></span><input ref={name} required maxLength={128} value={draft.name} onChange={e => edit("name", e.target.value)} placeholder="Team guidance — October" /></label>
          <label className="upload-field"><span className="upload-label">Version<span>Required</span></span><input required maxLength={128} value={draft.version} onChange={e => edit("version", e.target.value)} /></label>
          <label className="upload-field"><span className="upload-label">Policy category<span>Required</span></span><input required maxLength={128} value={draft.family} onChange={e => edit("family", e.target.value)} placeholder="People operations" /></label>
          <div className="upload-field"><span className="upload-label">Who can read this source</span><Select label="Saved Slack source access" value={draft.sensitivity} options={[{ value: "restricted", label: "Restricted readers" }, { value: "demo_shareable", label: "Office readers" }]} onChange={value => edit("sensitivity", value)} /></div>
          <label className="upload-field span-two"><span className="upload-label">Applies to<span>Required</span></span><textarea required maxLength={1000} rows={2} value={draft.scope} onChange={e => edit("scope", e.target.value)} placeholder="Who and what these messages cover" /></label>
        </div>
        <div className="slack-import-authority"><MessageSquare size={14} />Informal guidance<span>Message dates come from the saved file · UTC</span></div>
        {hosted && <div className="upload-processing"><div><LockKeyhole size={16} /><strong>Hosted model processing</strong></div><label className="upload-consent"><input type="checkbox" checked={draft.hosted} onChange={e => edit("hosted", e.target.checked)} required /><span>Allow these messages to be sent to the configured hosted model for extraction and comparison.</span></label></div>}
        {error && <div className="notice warning" ref={alert} tabIndex={-1} role="alert"><AlertCircle size={17} /><span>{error}</span></div>}
      </div></fieldset></div>
      <footer className="dialog-footer"><span className="upload-save-status" role="status">{saving ? "Sending saved messages…" : "\u00a0"}</span><button type="button" className="button secondary" disabled={saving} onClick={onClose}>Cancel</button><button className="button primary slack-import-submit" type="submit" disabled={!canSubmit} aria-keyshortcuts="Control+Enter Meta+Enter">{saving ? <LoaderCircle className="spin" size={15} /> : <ArrowUpFromLine size={15} />}{saving ? "Importing…" : "Import messages"}<SubmitShortcutHint /></button></footer>
    </form>
  </Modal>;
}
