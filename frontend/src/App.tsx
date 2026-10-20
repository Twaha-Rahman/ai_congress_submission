import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { AlertCircle, ArrowDownWideNarrow, ArrowLeft, ArrowRight, BookOpen, Check, ChevronDown, CircleCheck, Globe2, Inbox, LayoutList, LoaderCircle, LockKeyhole, RefreshCw, Search, Shield, X } from 'lucide-react';
import { api, ApiError, getFinding, reviewFinding } from './api';
import { EmptyState, ErrorState, Loading, Modal, ReviewBadge } from './components';
import FindingDetail from './FindingDetail';
import { date, findingTitle, humanize, orderFindings, scopeLabel, typeLabels } from './presentation';
import type { Claim, Finding, Office, ReviewAction, ReviewEvent, Session, Source, WorkspaceData } from './types';

interface View { office: Office; finding: string; search: string; state: string; type: string; severity: string }
function readView(): View {
  const p = new URLSearchParams(window.location.search);
  return { office: p.get('office') === 'frankfurt' ? 'frankfurt' : 'dhaka', finding: p.get('finding') || '', search: p.get('q') || '', state: p.get('state') || 'all', type: p.get('type') || 'all', severity: p.get('severity') || 'all' };
}
type Detail = { office: Office; id: string; finding: Finding; reviews: ReviewEvent[] };

export default function App() {
  const [view, setView] = useState<View>(readView);
  const [session, setSession] = useState<Session | null>(null);
  const [workspace, setWorkspace] = useState<(WorkspaceData & { office: Office }) | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [reviewAction, setReviewAction] = useState<ReviewAction | null>(null);
  const [notice, setNotice] = useState('');
  const [mobileDetail, setMobileDetail] = useState(!!view.finding);
  const searchRef = useRef<HTMLInputElement>(null);
  const data = workspace?.office === view.office ? workspace : null;

  function navigate(patch: Partial<View>, replace = false) {
    const next = { ...view, ...patch };
    const url = new URL(window.location.href);
    url.pathname = '/findings'; url.search = '';
    for (const [key, value] of Object.entries(next)) {
      if (value && value !== 'all') url.searchParams.set(key === 'search' ? 'q' : key, value);
    }
    window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
    setView(next);
  }
  useEffect(() => {
    const handler = () => { const next = readView(); setView(next); setMobileDetail(!!next.finding); setNotice(''); };
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api<Session>('session', { signal: controller.signal }).then(setSession).catch(error => { if (error.name !== 'AbortError') setError(error.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    Promise.all([
      api<{ findings: Finding[] }>(`${view.office}/findings`, { signal: controller.signal }),
      api<{ sources: Source[] }>(`${view.office}/sources`, { signal: controller.signal }),
      api<{ claims: Claim[] }>(`${view.office}/claims`, { signal: controller.signal }),
    ]).then(([f, s, c]) => {
      setWorkspace({ office: view.office, findings: orderFindings(f.findings), sources: s.sources, claims: c.claims });
      setLoading(false);
    }).catch(error => {
      if (error.name !== 'AbortError') { setError(error.message); setLoading(false); }
    });
    return () => controller.abort();
  }, [view.office, revision]);

  const visible = useMemo(() => {
    const query = view.search.trim().toLowerCase();
    return (data?.findings || []).filter(f =>
      (view.state === 'all' || f.review_state === view.state)
      && (view.type === 'all' || f.finding_type === view.type)
      && (view.severity === 'all' || f.severity === view.severity)
      && (!query || [findingTitle(f), typeLabels[f.finding_type], scopeLabel(f.affected_scope), f.finding_id, ...f.evidence.map(e => e.quote)].join(' ').toLowerCase().includes(query)),
    );
  }, [data, view.search, view.state, view.type, view.severity]);
  const selectedId = view.finding || visible[0]?.finding_id || '';
  useEffect(() => {
    if (!selectedId) { setDetail(null); setDetailError(''); setDetailLoading(false); return; }
    const controller = new AbortController();
    setDetailError(''); setDetailLoading(true);
    getFinding(view.office, selectedId, controller.signal).then(result => {
      setDetail({ office: view.office, id: selectedId, ...result });
      setDetailLoading(false);
    }).catch(error => {
      if (error.name !== 'AbortError') { setDetailError(error instanceof ApiError && error.status === 404 ? 'This finding is unavailable in this office or your current access scope.' : error.message); setDetailLoading(false); }
    });
    return () => controller.abort();
  }, [view.office, selectedId, revision]);
  const current = detail?.office === view.office && detail.id === selectedId ? detail : null;
  const needsAttention = data?.findings.filter(f => f.severity === 'high' && !['resolved', 'dismissed'].includes(f.review_state)).length || 0;
  const reviewed = data?.findings.filter(f => f.review_state !== 'open').length || 0;
  const filtered = !!(view.search || view.state !== 'all' || view.type !== 'all' || view.severity !== 'all');

  function selectFinding(finding: Finding) { navigate({ finding: finding.finding_id }); setMobileDetail(true); setNotice(''); }
  function filter(patch: Partial<View>) { navigate({ ...patch, finding: '' }, true); setMobileDetail(false); }
  function clearFilters() { filter({ search: '', state: 'all', type: 'all', severity: 'all' }); }
  function retry() { setRevision(n => n + 1); }

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">Skip to findings</a>
    <aside className="sidebar">
      <a className="brand" href="/findings" onClick={event => { event.preventDefault(); navigate({ finding: '', search: '', state: 'all', type: 'all', severity: 'all' }); setMobileDetail(false); }}><img src="/meridian.svg" width="34" height="34" alt="" /><span>meridian<span className="brand-dot">.</span></span></a>
      <div className="sidebar-workspace"><span className="workspace-avatar">M</span><div><strong>Meridian Trade Finance</strong><span>Institutional memory</span></div></div>
      <div className="sidebar-label">Workspace</div>
      <nav aria-label="Workspace"><a className="nav-item active" href={`/findings?office=${view.office}`} aria-current="page" onClick={event => { event.preventDefault(); navigate({ finding: '' }); setMobileDetail(false); }}><LayoutList size={18} /><span>Findings</span>{!!data?.findings.length && <span className="nav-count">{data.findings.length}</span>}</a></nav>
      <div className="sidebar-context"><BookOpen size={19} strokeWidth={1.5} /><p>Every finding starts<br />with its evidence.</p><span>Understand the change.<br />Make an informed decision.</span></div>
      <footer className="sidebar-footer"><Shield size={16} /><div><strong>Synthetic demo</strong><span>Fictional policies & people</span></div></footer>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><span className="mobile-brand"><img src="/meridian.svg" width="28" height="28" alt="Meridian" /></span><span>Workspace</span><ChevronDown className="breadcrumb-chevron" size={12} /><strong>Findings</strong></div><div className="topbar-context"><label className="office-select"><Globe2 size={16} /><span className="sr-only">Office</span><select aria-label="Office" value={view.office} onChange={event => { navigate({ office: event.target.value as Office, finding: '' }); setMobileDetail(false); setNotice(''); }}><option value="dhaka">Dhaka office</option><option value="frankfurt">Frankfurt office</option></select><ChevronDown size={13} /></label><span className="topbar-divider" /><span className="role-label">{session ? humanize(session.role) : 'Connecting…'}</span><span className="avatar" aria-hidden="true">{session?.role === 'reader' ? 'AN' : 'CR'}</span></div></header>

      <main id="workspace" className="workspace" tabIndex={-1}>
        <div className="page-heading"><div><div className="eyebrow page-eyebrow">Your office, in context</div><h1>Findings</h1><p>See what changed. Understand what needs your attention.</p></div><button className="button secondary refresh-button" onClick={retry} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} />{loading ? 'Refreshing' : 'Refresh'}</button></div>

        {notice && <div className="notice success" role="status"><CircleCheck size={18} /><span>{notice}</span><button className="icon-button" aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16} /></button></div>}
        {error ? <div className="workspace-error"><ErrorState error={error} retry={retry} /></div> : !data ? <Loading /> : <>
          <section className="summary-strip" aria-label="Findings overview"><div><span className="summary-icon attention"><AlertCircle size={18} /></span><strong>{needsAttention}</strong><span>need attention</span></div><span className="summary-divider" /><div><strong>{data.findings.length}</strong><span>total findings</span></div><span className="summary-divider" /><div><strong>{reviewed}</strong><span>reviewed</span></div><span className="summary-office"><span className="small-dot dot-policy" />{humanize(view.office)} evidence</span></section>

          <div className={`investigation-layout ${mobileDetail ? 'show-detail' : ''}`}>
            <section className="queue" aria-label="Findings queue">
              <div className="queue-heading"><h2>Review queue <span>{visible.length}</span></h2><ArrowDownWideNarrow size={16} aria-label="Sorted by severity, then newest" /></div>
              <label className="search-input"><Search size={16} /><span className="sr-only">Search findings</span><input ref={searchRef} placeholder="Search findings…" aria-label="Search findings" value={view.search} onChange={event => filter({ search: event.target.value })} />{view.search && <button className="icon-button" aria-label="Clear search" onClick={() => { filter({ search: '' }); searchRef.current?.focus(); }}><X size={14} /></button>}</label>
              <div className="queue-filters"><label><span>Review status</span><select aria-label="Review status" value={view.state} onChange={e => filter({ state: e.target.value })}><option value="all">All statuses</option><option value="open">Open</option><option value="acknowledged">Acknowledged</option><option value="resolved">Resolved</option><option value="dismissed">Dismissed</option></select></label><label><span>Severity</span><select aria-label="Severity" value={view.severity} onChange={e => filter({ severity: e.target.value })}><option value="all">All severities</option><option value="high">High</option><option value="review">Interpretation</option><option value="info">Informational</option></select></label></div>
              <label className="type-filter"><span className="sr-only">Finding type</span><select aria-label="Finding type" value={view.type} onChange={e => filter({ type: e.target.value })}><option value="all">All finding types</option>{Object.entries(typeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              <div className="queue-results" aria-live="polite"><span>{visible.length} {visible.length === 1 ? 'finding' : 'findings'}</span>{filtered && <button className="text-button" onClick={clearFilters}>Clear filters</button>}</div>
              <ul className="finding-list">{visible.map(f => <li key={f.finding_id}><button className={`finding-list-item ${f.finding_id === selectedId ? 'selected' : ''}`} aria-current={f.finding_id === selectedId ? 'true' : undefined} onClick={() => selectFinding(f)}><div className="list-item-meta"><span className={`list-type ${f.severity === 'high' ? 'attention-text' : ''}`}>{f.severity === 'high' && <span className="small-dot" />}{typeLabels[f.finding_type]}</span><ArrowRight size={14} /></div><h3>{findingTitle(f)}</h3><p>{scopeLabel(f.affected_scope)}</p><div className="list-item-footer"><ReviewBadge state={f.review_state} /><time dateTime={f.created_at}>{date(f.created_at).replace(/ \d{4}$/, '')}</time></div></button></li>)}</ul>
              {!visible.length && <div className="queue-empty"><Inbox size={26} /><h3>{data.findings.length ? 'No matching findings' : 'No findings yet'}</h3><p>{data.findings.length ? 'Try a different search or clear the filters.' : 'Findings will appear here after sources are processed.'}</p>{filtered && <button className="text-button" onClick={clearFilters}>Clear filters <ArrowRight size={14} /></button>}</div>}
              <p className="queue-footnote"><LockKeyhole size={12} />Only evidence you can access is shown.</p>
            </section>

            <div className="detail-container">
              <button className="text-button back-to-list" onClick={() => { navigate({ finding: '' }); setMobileDetail(false); }}><ArrowLeft size={16} />Back to findings</button>
              {view.finding && !visible.some(f => f.finding_id === view.finding) && current && <div className="notice"><AlertCircle size={17} /><span>This finding is outside the current filters.</span><button className="text-button" onClick={() => navigate({ finding: '' }, true)}>View results</button></div>}
              {detailError ? <ErrorState title="Finding unavailable" error={detailError} retry={retry} /> : selectedId && !current ? <Loading label="Opening evidence…" /> : current ? <FindingDetail key={`${view.office}-${selectedId}`} finding={current.finding} reviews={current.reviews} sources={data.sources} claims={data.claims} office={view.office} session={session} busy={loading || detailLoading} onReview={setReviewAction} /> : <EmptyState icon={<Inbox size={28} />} title={filtered ? 'Nothing matches these filters' : 'A clear queue'} action={filtered ? <button className="button secondary" onClick={clearFilters}>Clear filters</button> : undefined}>{filtered ? 'Adjust your search to find another issue.' : `There are no findings to investigate in ${humanize(view.office)}. New findings will appear after ingestion and comparison.`}</EmptyState>}
            </div>
          </div>
          <footer className="workspace-footer"><span>Meridian · Verifiable institutional memory</span><span>Source evidence, with context.</span></footer>
        </>}
      </main>
    </div>
    {reviewAction && current && <ReviewDialog action={reviewAction} finding={current.finding} office={view.office} onClose={() => setReviewAction(null)} onSaved={(state) => {
      setReviewAction(null); setNotice(`Review saved · ${humanize(state)}. The source evidence has been preserved.`);
      setDetail(old => old ? { ...old, finding: { ...old.finding, review_state: state } } : old);
      setWorkspace(old => old ? { ...old, findings: old.findings.map(f => f.finding_id === current.id ? { ...f, review_state: state } : f) } : old);
      retry();
    }} />}
  </div>;
}

function ReviewDialog({ action, finding, office, onClose, onSaved }: { action: ReviewAction; finding: Finding; office: Office; onClose: () => void; onSaved: (state: Finding['review_state']) => void }) {
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const explanations = {
    acknowledge: 'Record that you have seen and assessed this finding. It will remain available for follow-up.',
    resolve: 'Explain what addressed the issue, such as corrected guidance or an updated procedure.',
    dismiss: 'Explain why this finding needs no further action. The evidence and your decision remain in the record.',
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim() || saving) return;
    setSaving(true); setError('');
    try {
      const result = await reviewFinding(office, finding.finding_id, action, reason.trim(), finding.claim_revision_ids, finding.snapshot_id);
      onSaved(result.new_state);
    } catch (error) {
      setError(error instanceof Error ? error.message + (error instanceof ApiError && error.status >= 500 ? ' Refresh the finding before retrying if the outcome is uncertain.' : '') : 'The review could not be saved.'); setSaving(false);
    }
  }
  return <Modal title={`${humanize(action)} finding`} onClose={onClose} busy={saving}><form onSubmit={submit}><div className="dialog-body"><p className="review-dialog-finding">{findingTitle(finding)}</p><p className="dialog-description">{explanations[action]}</p><label className="reason-label" htmlFor="review-reason">Reason <span>Required</span></label><textarea id="review-reason" value={reason} onChange={e => setReason(e.target.value)} required maxLength={4000} rows={5} placeholder="Describe your assessment and any action taken…" disabled={saving} aria-describedby="review-reason-help" /><p className="field-help" id="review-reason-help">Saved to review history under your configured reviewer identity.</p>{error && <div className="notice warning" role="alert"><AlertCircle size={17} /><span>{error}</span></div>}</div><footer className="dialog-footer"><button type="button" className="button secondary" onClick={onClose} disabled={saving}>Cancel</button><button type="submit" className="button primary" disabled={!reason.trim() || saving}>{saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}{saving ? 'Saving review…' : `${humanize(action)} finding`}</button></footer></form></Modal>;
}
