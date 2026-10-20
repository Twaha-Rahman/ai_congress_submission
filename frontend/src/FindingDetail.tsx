import { useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Clock3,
  FileText,
  Fingerprint,
  History,
  Info,
  LockKeyhole,
  MessageSquare,
  Scale,
  Shield,
  SquareArrowOutUpRight,
} from "lucide-react";
import type {
  Claim,
  Evidence,
  Finding,
  Office,
  ReviewAction,
  ReviewEvent,
  Session,
  Source,
} from "./types";
import {
  date,
  explanation,
  findingTitle,
  findingTag,
  humanize,
  ruleSummary,
  scopeContext,
  scopeLabel,
  sourceTitle,
  typeLabels,
} from "./presentation";
import { Modal, ReviewBadge, SeverityBadge } from "./components";

type Tab = "evidence" | "timeline" | "reviews";
interface Props {
  finding: Finding;
  sources: Source[];
  claims: Claim[];
  reviews: ReviewEvent[];
  office: Office;
  session: Session | null;
  busy: boolean;
  onReview: (action: ReviewAction) => void;
  onSearchTag: (tag: string) => void;
  shortcutsEnabled: boolean;
}

export default function FindingDetail({
  finding,
  sources,
  claims,
  reviews,
  office,
  session,
  busy,
  onReview,
  onSearchTag,
  shortcutsEnabled,
}: Props) {
  const [tab, setTab] = useState<Tab>("evidence");
  const [sourceEvidence, setSourceEvidence] = useState<Evidence | null>(null);
  const sourceMap = new Map(sources.map((s) => [s.source_id, s]));
  const claimMap = new Map(claims.map((c) => [c.revision_id, c]));
  const sortedEvidence = [...finding.evidence].sort((a, b) => {
    const rank = { policy: 0, procedure: 1, informal: 2 };
    return (
      rank[sourceMap.get(a.source_id)?.authority || "informal"] -
      rank[sourceMap.get(b.source_id)?.authority || "informal"]
    );
  });
  const selectedSource = sourceEvidence
    ? sourceMap.get(sourceEvidence.source_id)
    : undefined;
  const modes = [
    ...new Set(
      finding.claim_revision_ids
        .map((id) => claimMap.get(id)?.extraction_mode)
        .filter(Boolean),
    ),
  ];
  return (
    <article
      className="finding-detail"
      aria-labelledby="finding-title"
      aria-busy={busy}
    >
      <div className="finding-kicker">
        <span>{typeLabels[finding.finding_type]}</span>
        <button
          className="finding-tag"
          title={`Search ${findingTag(finding)}`}
          aria-label={`Search finding ${findingTag(finding)}`}
          onClick={() => onSearchTag(findingTag(finding))}
        >
          {findingTag(finding)}
        </button>
      </div>
      <div className="detail-heading">
        <h2 id="finding-title" tabIndex={-1}>
          {findingTitle(finding)}
        </h2>
        <div className="badge-row">
          <SeverityBadge severity={finding.severity} />
          <ReviewBadge state={finding.review_state} />
        </div>
      </div>
      <p className="finding-explanation">{explanation(finding)}</p>

      {finding.superseded_by_snapshot_id && (
        <div className="notice warning">
          <Info size={17} />
          <span>
            This snapshot has been superseded. Refresh the workspace before
            recording a review.
          </span>
        </div>
      )}

      <section className="scope-card" aria-label="Affected scope">
        <div className="scope-icon">
          <Scale size={21} strokeWidth={1.5} />
        </div>
        <div>
          <span className="eyebrow">Affected scope</span>
          <strong>{scopeLabel(finding.affected_scope)}</strong>
          <p>{scopeContext(finding.affected_scope)}</p>
        </div>
        <div className="scope-date">
          <span className="eyebrow">Applies from</span>
          <span>{date(finding.affected_valid_interval.start)}</span>
          {finding.affected_valid_interval.end && (
            <small>
              Until {date(finding.affected_valid_interval.end)} (exclusive)
            </small>
          )}
        </div>
      </section>

      <div className="detail-tabs" role="tablist" aria-label="Finding details">
        {(
          [
            ["evidence", "Compare evidence", BookOpen],
            ["timeline", "Chronology", Clock3],
            ["reviews", "Review history", History],
          ] as const
        ).map(([key, label, Icon], index, all) => (
          <button
            key={key}
            role="tab"
            id={`tab-${key}`}
            aria-label={label}
            aria-controls={`panel-${key}`}
            aria-selected={tab === key}
            aria-keyshortcuts={
              shortcutsEnabled
                ? { evidence: "E", timeline: "T", reviews: "H" }[key]
                : undefined
            }
            tabIndex={tab === key ? 0 : -1}
            onKeyDown={(event) => {
              let next = index;
              if (event.key === "ArrowRight") next = (index + 1) % all.length;
              else if (event.key === "ArrowLeft")
                next = (index + all.length - 1) % all.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = all.length - 1;
              else return;
              event.preventDefault();
              setTab(all[next][0]);
              document.getElementById(`tab-${all[next][0]}`)?.focus();
            }}
            onClick={() => setTab(key)}
          >
            <Icon size={15} />
            <span>{label}</span>
            {key === "reviews" && reviews.length > 0 && (
              <span className="tab-count" aria-hidden="true">
                {reviews.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div
        className="tab-panel"
        id={`panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        tabIndex={0}
      >
        {tab === "evidence" && (
          <>
            <div className="section-caption">
              <p>Read the sources side by side.</p>
              <span>{sortedEvidence.length} evidence references</span>
            </div>
            <div className="evidence-grid">
              {sortedEvidence.map((evidence, index) => (
                <EvidenceCard
                  key={`${evidence.clause_id}-${index}`}
                  evidence={evidence}
                  source={sourceMap.get(evidence.source_id)}
                  claim={claimMap.get(evidence.claim_revision_id)}
                  onInspect={() => setSourceEvidence(evidence)}
                />
              ))}
              {!sortedEvidence.length && (
                <p className="muted">
                  No evidence passages are available for this finding.
                </p>
              )}
            </div>
            {finding.authority_basis && (
              <div className="authority-note">
                <Shield size={16} />
                <p>
                  <strong>
                    Authority basis: {humanize(finding.authority_basis)}.
                  </strong>{" "}
                  Authority comes from source metadata. Extraction mode and
                  review status do not change which source governs.
                </p>
              </div>
            )}
          </>
        )}
        {tab === "timeline" && (
          <Chronology finding={finding} sources={sources} />
        )}
        {tab === "reviews" && (
          <div className="review-history">
            <p className="section-intro">
              Decisions are recorded with a reason. Original evidence is
              preserved.
            </p>
            {!reviews.length ? (
              <div className="history-empty">
                <History size={24} />
                <h3>No review decisions yet</h3>
                <p>This finding is ready for a reviewer to assess.</p>
              </div>
            ) : (
              [...reviews].reverse().map((event) => (
                <section className="history-event" key={event.event_id}>
                  <div className="history-event-heading">
                    <ReviewBadge state={event.new_state} />
                    <time dateTime={event.created_at}>
                      {date(event.created_at, true)}
                    </time>
                  </div>
                  <p>{event.reason}</p>
                  <span className="muted">
                    {humanize(event.actor)} · {humanize(event.prior_state)}{" "}
                    <ArrowRight size={12} /> {humanize(event.new_state)}
                  </span>
                  {event.snapshot_id &&
                    event.snapshot_id !== finding.snapshot_id && (
                      <small className="muted">
                        Decision recorded against an earlier snapshot.
                      </small>
                    )}
                </section>
              ))
            )}
          </div>
        )}
      </div>

      <section className="review-bar" aria-label="Review this finding">
        <div>
          <span className="eyebrow">Next step</span>
          <h3>
            {finding.review_state === "open"
              ? "Record your assessment"
              : "Update the review decision"}
          </h3>
          <p>A review records your decision; it does not edit the sources.</p>
        </div>
        {session?.canReview ? (
          <div className="review-actions">
            <button
              className="button secondary"
              disabled={busy || !!finding.superseded_by_snapshot_id}
              onClick={() => onReview("dismiss")}
              aria-keyshortcuts={shortcutsEnabled ? "D" : undefined}
            >
              Dismiss{" "}
              {shortcutsEnabled && (
                <span className="action-shortcut" aria-hidden="true">
                  D
                </span>
              )}
            </button>
            <button
              className="button secondary"
              disabled={busy || !!finding.superseded_by_snapshot_id}
              onClick={() => onReview("resolve")}
              aria-keyshortcuts={shortcutsEnabled ? "R" : undefined}
            >
              Resolve{" "}
              {shortcutsEnabled && (
                <span className="action-shortcut" aria-hidden="true">
                  R
                </span>
              )}
            </button>
            <button
              className="button primary"
              disabled={busy || !!finding.superseded_by_snapshot_id}
              onClick={() => onReview("acknowledge")}
              aria-keyshortcuts={shortcutsEnabled ? "A" : undefined}
            >
              <Check size={16} />
              Acknowledge{" "}
              {shortcutsEnabled && (
                <span className="action-shortcut" aria-hidden="true">
                  A
                </span>
              )}
            </button>
          </div>
        ) : (
          <span className="read-only">
            <LockKeyhole size={15} />
            Read-only access
          </span>
        )}
      </section>

      <footer className="detail-footer">
        <span>
          <Fingerprint size={14} />
          Signed snapshot · verification not run here
        </span>
        <span>Extraction: {modes.length ? modes.join(" / ") : "unknown"}</span>
      </footer>
      <details className="technical-details">
        <summary>
          Snapshot details <ChevronRight size={14} />
        </summary>
        <dl>
          <dt>Finding</dt>
          <dd>{finding.finding_id}</dd>
          <dt>Snapshot</dt>
          <dd>{finding.snapshot_id}</dd>
          <dt>Snapshot hash</dt>
          <dd>{finding.snapshot_hash}</dd>
          <dt>Signing key</dt>
          <dd>{finding.key_id}</dd>
          <dt>Explanation code</dt>
          <dd>{finding.explanation_code}</dd>
          <dt>Detected at</dt>
          <dd>{date(finding.created_at, true)}</dd>
        </dl>
        <p>
          A signature commits to the snapshot. It does not establish that a
          policy is correct or legally sufficient.
        </p>
      </details>

      {sourceEvidence && (
        <Modal
          title="Source evidence"
          className="source-dialog"
          onClose={() => setSourceEvidence(null)}
        >
          <div className="dialog-body">
            <span className="eyebrow">Original passage</span>
            <h3 className="source-dialog-title">
              {sourceTitle(selectedSource)}
            </h3>
            <div className="badge-row">
              <span className="badge neutral">
                {selectedSource?.version_label || "Unknown version"}
              </span>
              <span className="badge neutral">
                {selectedSource
                  ? humanize(selectedSource.authority)
                  : "Unknown authority"}
              </span>
              {selectedSource?.sensitivity === "restricted" && (
                <span className="badge neutral">
                  <LockKeyhole size={12} />
                  Restricted
                </span>
              )}
            </div>
            <blockquote className="source-quote">
              {sourceEvidence.quote}
            </blockquote>
            <dl className="source-facts">
              <dt>Location</dt>
              <dd>
                {selectedSource?.source_type === "slack"
                  ? "Saved Slack event"
                  : `Page ${sourceEvidence.page}`}
                {sourceEvidence.section
                  ? ` · Section ${sourceEvidence.section}`
                  : ""}
              </dd>
              <dt>Published</dt>
              <dd>{date(selectedSource?.publication_time, true)}</dd>
              <dt>Effective from</dt>
              <dd>{date(selectedSource?.effective_from)}</dd>
              <dt>Known to Meridian</dt>
              <dd>{date(selectedSource?.ingested_at, true)}</dd>
              <dt>Extraction mode</dt>
              <dd>
                {claimMap.get(sourceEvidence.claim_revision_id)
                  ?.extraction_mode || "Unknown"}
              </dd>
            </dl>
            <div className="notice">
              <Info size={17} />
              <span>
                This is the preserved evidence quote. File integrity
                verification is a separate check and has not been run in this
                workspace.
              </span>
            </div>
            <details className="technical-details">
              <summary>
                Evidence identifiers <ChevronRight size={14} />
              </summary>
              <dl>
                <dt>Source</dt>
                <dd>{sourceEvidence.source_id}</dd>
                <dt>Claim revision</dt>
                <dd>{sourceEvidence.claim_revision_id}</dd>
                <dt>Clause</dt>
                <dd>{sourceEvidence.clause_id}</dd>
                <dt>Manifest root</dt>
                <dd>{sourceEvidence.manifest_root}</dd>
                <dt>Text range</dt>
                <dd>
                  {sourceEvidence.start_char}–{sourceEvidence.end_char}
                </dd>
              </dl>
            </details>
          </div>
          <footer className="dialog-footer">
            <button
              className="button secondary"
              onClick={() => setSourceEvidence(null)}
            >
              Close
            </button>
            <a
              className="button primary"
              href={`/api/${office}/sources/${encodeURIComponent(sourceEvidence.source_id)}/content`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ArrowDownToLine size={16} />
              Download original
              <SquareArrowOutUpRight size={13} />
            </a>
          </footer>
        </Modal>
      )}
    </article>
  );
}

function EvidenceCard({
  evidence,
  source,
  claim,
  onInspect,
}: {
  evidence: Evidence;
  source?: Source;
  claim?: Claim;
  onInspect: () => void;
}) {
  const formal = source?.authority === "policy";
  const Icon = source?.source_type === "slack" ? MessageSquare : FileText;
  return (
    <section className={`evidence-card ${formal ? "formal-evidence" : ""}`}>
      <div className="evidence-role">
        <span>
          <span
            className={`small-dot ${formal ? "dot-policy" : "dot-guidance"}`}
          />
          {source
            ? {
                policy: "Policy requirement",
                procedure: "Operating procedure",
                informal: "Informal guidance",
              }[source.authority]
            : "Evidence passage"}
        </span>
        {source?.sensitivity === "restricted" && (
          <LockKeyhole size={13} aria-label="Restricted source" />
        )}
      </div>
      <header>
        <div className="source-file-icon">
          <Icon size={19} strokeWidth={1.5} />
        </div>
        <div>
          <h3>{sourceTitle(source)}</h3>
          <p>
            {source?.version_label || "Version unknown"} <span>·</span>{" "}
            {source?.source_type === "slack"
              ? "Saved message"
              : `Page ${evidence.page}${evidence.section ? ` · § ${evidence.section}` : ""}`}
          </p>
        </div>
      </header>
      <div className="rule-summary">{ruleSummary(claim)}</div>
      <blockquote>{evidence.quote}</blockquote>
      <div className="evidence-card-bottom">
        <span>
          {source?.source_type === "slack" ? "Published" : "Effective"}{" "}
          {date(
            source?.source_type === "slack"
              ? source.publication_time
              : claim?.valid_from || source?.effective_from,
          )}
        </span>
        <button
          className="text-button"
          onClick={onInspect}
          aria-label={`Inspect ${sourceTitle(source)} ${source?.version_label || ""}`}
        >
          Inspect source <ArrowRight size={14} />
        </button>
      </div>
    </section>
  );
}

function Chronology({
  finding,
  sources,
}: {
  finding: Finding;
  sources: Source[];
}) {
  const involved = new Set(finding.evidence.map((e) => e.source_id));
  const direct = sources.filter((s) => involved.has(s.source_id));
  // Include only explicit replacement links; do not infer history from version strings.
  const historical = sources.filter((s) =>
    direct.some(
      (current) =>
        current.supersedes?.supersedes_source_identity === s.source_identity &&
        current.supersedes?.supersedes_version_label === s.version_label,
    ),
  );
  const relevant = [
    ...new Map(
      [...direct, ...historical].map((s) => [s.source_id, s]),
    ).values(),
  ];
  const events = relevant
    .flatMap((source) => {
      const result = [];
      if (source.publication_time)
        result.push({
          time: source.publication_time,
          title: `${sourceTitle(source)} · ${source.version_label}`,
          note:
            source.source_type === "slack"
              ? "Guidance published in a saved Slack message."
              : "Source published.",
          source,
        });
      if (source.source_type !== "slack" && source.effective_from)
        result.push({
          time: source.effective_from,
          title: `${source.version_label} becomes effective`,
          note: source.supersedes
            ? `Explicitly replaces ${source.supersedes.supersedes_version_label} in the declared scope.`
            : "Effective date declared by the source manifest.",
          source,
        });
      return result;
    })
    .sort((a, b) => a.time.localeCompare(b.time));
  return (
    <div className="chronology">
      <p className="section-intro">
        Source dates explain when rules apply. Knowledge dates show when
        Meridian received them.
      </p>
      <ol className="timeline">
        {events.map((event, i) => (
          <li key={`${event.source.source_id}-${i}`}>
            <span className="timeline-point" />
            <time dateTime={event.time}>{date(event.time)}</time>
            <h3>{event.title}</h3>
            <p>{event.note}</p>
          </li>
        ))}
      </ol>
      <div className="knowledge-note">
        <Clock3 size={18} />
        <div>
          <h3>Known to Meridian</h3>
          {relevant.map((source) => (
            <p key={source.source_id}>
              {sourceTitle(source)} · {source.version_label}
              <span>{date(source.ingested_at, true)}</span>
            </p>
          ))}
          <p>
            Finding detected<span>{date(finding.created_at, true)}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
