import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, ArrowUpFromLine, Check, FileText, LoaderCircle, LockKeyhole, Plus, X } from "lucide-react";
import { api, ApiError } from "./api";
import { Modal, ShortcutHint } from "./components";
import Select from "./Select";
import type { Office, Session, Source, SourceDetail, UploadJob } from "./types";
import { blankDraft, buildPolicyManifest, fileSize, maxPdfBytes, validatePdf, type PolicyDraft } from "./uploads";

export default function UploadPdf({ open, office, sources, config, shortcutsEnabled, onClose, onQueued }: {
  open: boolean; office: Office; sources: Source[];
  config?: NonNullable<Session["uploads"]>[Office]; shortcutsEnabled: boolean;
  onClose: () => void; onQueued: (job: UploadJob) => void;
}) {
  const [draft, setDraft] = useState(blankDraft);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [replaceId, setReplaceId] = useState("");
  const [replacement, setReplacement] = useState<SourceDetail | null>(null);
  const [replacementError, setReplacementError] = useState("");
  const [loadingReplacement, setLoadingReplacement] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const name = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const fileVersion = useRef(0);
  const saveLock = useRef(false);
  const dragDepth = useRef(0);
  const savedNewDraft = useRef<PolicyDraft | null>(null);
  const limit = config?.maxBytes || maxPdfBytes;
  const hosted = config?.processing !== "local";
  const canSubmit = !!file && !fileError && !checking && !saving && !loadingReplacement && (!replaceId || !!replacement);

  function edit<K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }
  useEffect(() => {
    if (!replaceId) { setReplacement(null); setReplacementError(""); setLoadingReplacement(false); return; }
    const controller = new AbortController();
    setLoadingReplacement(true); setReplacement(null); setReplacementError("");
    api<SourceDetail>(`${office}/sources/${encodeURIComponent(replaceId)}`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        const m = result.source.manifest;
        if (result.source.subject !== "general_policy" || m.scope.kind !== "policy") throw new Error("Choose a general-policy PDF to replace.");
        setReplacement(result);
        setDraft((d) => ({ ...d, name: m.source_identity, family: m.policy_family,
          scope: m.scope.description, attributes: Object.entries(m.scope.attributes).map(([key, value]) => ({ key, value })),
          version: /^v\d+$/.test(m.version_label) ? `v${Number(m.version_label.slice(1)) + 1}` : "",
        }));
        setLoadingReplacement(false);
      }).catch((e) => { if (!controller.signal.aborted) { setReplacementError(e.message); setLoadingReplacement(false); } });
    return () => controller.abort();
  }, [replaceId, office]);

  async function choose(files: File[]) {
    const version = ++fileVersion.current;
    setFile(null); setFileError(""); setError("");
    if (files.length !== 1) { setChecking(false); setFileError("Choose one PDF at a time."); return; }
    setChecking(true);
    const next = files[0];
    try {
      const message = await validatePdf(next, limit);
      if (version !== fileVersion.current) return;
      setFileError(message);
      if (!message) {
        setFile(next);
        setDraft((d) => ({ ...d, name: d.name || next.name.replace(/\.pdf$/i, "").replace(/[_-]+/g, " ").slice(0, 128) }));
        requestAnimationFrame(() => name.current?.focus());
      }
    } catch { if (version === fileVersion.current) setFileError("This file could not be read. Choose it again."); }
    finally { if (version === fileVersion.current) setChecking(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !config?.enabled || saveLock.current) return;
    setError("");
    let submitted = false;
    try {
      if (hosted && !draft.hosted) throw new Error("Allow hosted model processing to analyze this PDF with the configured model.");
      const manifest = buildPolicyManifest(draft, replacement ? {
        manifest: replacement.source.manifest, clauses: replacement.clauses.map((c) => c.clause_id),
      } : undefined);
      const form = new FormData();
      form.set("file", file!); form.set("manifest", JSON.stringify(manifest));
      saveLock.current = true; setSaving(true);
      submitted = true;
      const result = await api<{ job: UploadJob }>(`${office}/ingestions/pdf`, { method: "POST", body: form });
      if (!result.job?.job_id) throw new Error("The office did not confirm a processing job. Check recent uploads before trying again.");
      setFile(null); setDraft(blankDraft()); setReplaceId(""); savedNewDraft.current = null;
      onQueued(result.job);
    } catch (e) {
      setError((e instanceof Error ? e.message : "The upload could not be completed.") +
        (submitted && (!(e instanceof ApiError) || e.status >= 500) ? " Check recent uploads before retrying; the office may have received the file." : ""));
      requestAnimationFrame(() => errorRef.current?.focus());
    } finally { saveLock.current = false; setSaving(false); }
  }
  if (!open) return null;
  return <Modal title="Upload PDF" onClose={onClose} busy={saving} className="upload-dialog">
    <form onSubmit={submit} onKeyDown={(e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); if (canSubmit) e.currentTarget.requestSubmit(); }
    }}>
      <div className="upload-scroll"><fieldset disabled={saving} className="upload-fields">
        <div className="dialog-body upload-body">
          <div className="upload-office"><span className="small-dot dot-policy" />{office === "dhaka" ? "Dhaka" : "Frankfurt"} office<span>PDF · up to {Math.round(limit / (1024 * 1024))} MB</span></div>
          <input ref={input} type="file" accept=".pdf,application/pdf" className="sr-only" tabIndex={-1} aria-label="Choose PDF file"
            onChange={(e) => { void choose(Array.from(e.target.files || [])); e.target.value = ""; }} />
          <div className={`upload-dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
            onDragEnter={(e) => { e.preventDefault(); if (!saving) { dragDepth.current++; setDragging(true); } }}
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }}
            onDragLeave={(e) => { e.preventDefault(); if (--dragDepth.current <= 0) { dragDepth.current = 0; setDragging(false); } }}
            onDrop={(e) => { e.preventDefault(); dragDepth.current = 0; setDragging(false); if (!saving) void choose(Array.from(e.dataTransfer.files)); }}>
            <button type="button" className="upload-file-button" onClick={() => input.current?.click()} aria-describedby="pdf-file-help pdf-file-error">
              <span className="upload-file-icon">{checking ? <LoaderCircle size={23} className="spin" /> : file ? <FileText size={23} /> : <ArrowUpFromLine size={23} />}</span>
              <span><strong>{file ? file.name : checking ? "Checking file…" : "Choose a PDF or drop it here"}</strong><span>{file ? `${fileSize(file.size)} · Click to change` : "Select a file from your laptop"}</span></span>
              {file && <Check size={18} className="upload-file-check" />}
            </button>
          </div>
          <p className="upload-hint" id="pdf-file-help">Text-based PDFs only. Scans and password-protected files are not supported.</p>
          <p id="pdf-file-error" className="upload-file-error" role="status">{fileError || "\u00a0"}</p>

          <div className="upload-form-grid">
            <div className="upload-field span-two"><span className="upload-label">Version relationship</span>
              <Select label="Version relationship" value={replaceId} options={[
                { value: "", label: "Independent document — no replacement" },
                ...sources.filter((s) => s.source_type === "pdf" && s.subject === "general_policy").map((s) => ({ value: s.source_id, label: `Replaces ${s.source_identity} · ${s.version_label}` })),
              ]} onChange={(value) => {
                if (!replaceId && value) savedNewDraft.current = draft;
                if (replaceId && !value && savedNewDraft.current) setDraft(savedNewDraft.current);
                setReplaceId(value);
              }} />
              {replaceId && <p className="upload-hint">Replaces the selected version in full. Its policy name, category and scope are retained.</p>}
              {loadingReplacement && <p className="upload-hint" role="status">Loading earlier version…</p>}
              {replacementError && <p className="upload-inline-error" role="alert">{replacementError}</p>}
            </div>
            <label className="upload-field"><span className="upload-label">Policy name <span>Required</span></span>
              <input ref={name} value={draft.name} onChange={(e) => edit("name", e.target.value)} required maxLength={128} readOnly={!!replaceId} placeholder="Travel expenses policy" autoComplete="off" />
            </label>
            <label className="upload-field"><span className="upload-label">Version <span>Required</span></span>
              <input value={draft.version} onChange={(e) => edit("version", e.target.value)} required maxLength={128} placeholder="v2" autoComplete="off" />
            </label>
            <label className="upload-field"><span className="upload-label">Policy category <span>Required</span></span>
              <input value={draft.family} onChange={(e) => edit("family", e.target.value)} required maxLength={128} readOnly={!!replaceId} placeholder="Travel, leave, purchasing…" autoComplete="off" />
            </label>
            <div className="upload-field"><span className="upload-label">Source authority</span><Select label="Source authority" value={draft.authority}
              options={[{ value: "policy", label: "Policy" }, { value: "procedure", label: "Operating procedure" }]}
              onChange={(value) => edit("authority", value as PolicyDraft["authority"])} /></div>
            <label className="upload-field"><span className="upload-label">Publication date <span>Required</span></span>
              <input type="date" value={draft.published} onChange={(e) => edit("published", e.target.value)} required />
            </label>
            <label className="upload-field"><span className="upload-label">Effective from <span>{replaceId ? "Required" : "Optional"}</span></span>
              <input type="date" value={draft.effective} onChange={(e) => edit("effective", e.target.value)} required={!!replaceId} />
            </label>
            <label className="upload-field span-two"><span className="upload-label">Applies to <span>Required</span></span>
              <textarea rows={2} value={draft.scope} onChange={(e) => edit("scope", e.target.value)} required maxLength={1000} readOnly={!!replaceId} placeholder="Who and what this policy covers, including location or team" />
            </label>
          </div>
          <p className="upload-hint">Dates use UTC. An unknown effective date can require manual review.</p>

          <details className="upload-advanced"><summary>Additional settings</summary>
            <div className="upload-form-grid">
              <label className="upload-field"><span className="upload-label">Stops applying before <span>Optional</span></span><input type="date" value={draft.until} onChange={(e) => edit("until", e.target.value)} /></label>
              <div className="upload-field"><span className="upload-label">Who can read this source</span><Select label="Source access" value={draft.sensitivity}
                options={[{ value: "demo_shareable", label: "Office readers" }, { value: "restricted", label: "Restricted readers" }]}
                onChange={(value) => edit("sensitivity", value as PolicyDraft["sensitivity"])} /></div>
              <div className="upload-field span-two"><span className="upload-label">Specific scope labels <span>Optional</span></span>
                {draft.attributes.map((row, index) => <div className="scope-label-row" key={index}>
                  <input aria-label={`Scope label ${index + 1}`} placeholder="country, team…" value={row.key} readOnly={!!replaceId} maxLength={128} onChange={(e) => edit("attributes", draft.attributes.map((r, i) => i === index ? { ...r, key: e.target.value } : r))} />
                  <input aria-label={`Scope value ${index + 1}`} placeholder="Value" value={row.value} readOnly={!!replaceId} maxLength={500} onChange={(e) => edit("attributes", draft.attributes.map((r, i) => i === index ? { ...r, value: e.target.value } : r))} />
                  {!replaceId && <button type="button" className="icon-button" aria-label={`Remove scope label ${index + 1}`} onClick={() => edit("attributes", draft.attributes.filter((_, i) => i !== index))}><X size={16} /></button>}
                </div>)}
                {!replaceId && <button type="button" className="text-button" onClick={() => edit("attributes", [...draft.attributes, { key: "", value: "" }])}><Plus size={14} />Add scope label</button>}
                <p className="upload-hint">Use consistent labels and values across documents. Conditions and exceptions are read from the PDF.</p>
              </div>
            </div>
          </details>

          <div className="upload-processing">
            <div><LockKeyhole size={16} /><strong>{hosted ? "Hosted model processing" : "Office model processing"}</strong></div>
            {hosted ? <label className="upload-consent"><input type="checkbox" checked={draft.hosted} onChange={(e) => edit("hosted", e.target.checked)} required />
              <span>Allow this PDF’s text to be sent to the configured hosted model for extraction and comparison.</span></label>
              : <p>The configured office model processes this PDF. Hosted processing is disabled for this source.</p>}
            <p className="upload-hint">This source stays in the {office === "dhaka" ? "Dhaka" : "Frankfurt"} office and is not exported to other offices.</p>
          </div>
          {error && <div className="notice warning" ref={errorRef} tabIndex={-1} role="alert"><AlertCircle size={17} /><span>{error}</span></div>}
        </div>
      </fieldset></div>
      <footer className="dialog-footer">
        <span className="upload-save-status" role="status">{saving ? "Sending PDF to the office…" : "\u00a0"}</span>
        <button type="button" className="button secondary" disabled={saving} onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={!canSubmit || !config?.enabled} aria-keyshortcuts="Control+Enter Meta+Enter">
          {saving ? <LoaderCircle size={16} className="spin" /> : <ArrowUpFromLine size={16} />}Upload PDF
          {shortcutsEnabled && <ShortcutHint>⌘ / Ctrl ↵</ShortcutHint>}
        </button>
      </footer>
    </form>
  </Modal>;
}
