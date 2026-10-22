import { useEffect, useState } from "react";
import { AlertCircle, ArrowRight, ArrowUpFromLine, Check, Clock3, FileSearch, GitCompareArrows, LoaderCircle, Save, ShieldCheck, Sparkles, Timer, RefreshCw, MessageSquare } from "lucide-react";
import { date } from "./presentation";
import { durationLabel, elapsedMilliseconds, isProcessing, jobDescription, jobLabels, jobDisplayLabel, jobDisplayState, processingWarnings, stageLabels } from "./uploads";
import type { UploadJob } from "./types";

export function JobBadge({ job }: { job: UploadJob }) {
  const state=jobDisplayState(job);
  const Icon = isProcessing(job) ? (job.status === "running" ? LoaderCircle : Clock3) : ["succeeded","reviewed","acknowledged"].includes(state) ? Check : AlertCircle;
  return <span className={`job-badge job-${state}`}><Icon size={13} className={job.status === "running" ? "spin" : ""} />{jobDisplayLabel(job)}</span>;
}

export default function UploadStatus({ job, canRetry, retrying, onRetry, onInspect, onFindings, onUpload, onImportSlack }: {
  job: UploadJob; canRetry: boolean; retrying: boolean; onRetry: () => void;
  onInspect: () => void; onFindings: () => void; onUpload?: () => void; onImportSlack?: () => void;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    setNow(Date.now());
    if (!isProcessing(job)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job.job_id, job.status]);
  const progress = job.progress;
  const recordedStages = progress?.stages || [];
  const stages = job.kind === "policy_comparison" ? ["comparison", "publication"] : ["reading", "extraction", "validation", "comparison", "publication"];
  const current = job.status === "running" ? progress?.current_stage : null;
  const icons = { reading: FileSearch, extraction: Sparkles, validation: ShieldCheck, comparison: GitCompareArrows, publication: Save };
  return <>
    <div className="dialog-body upload-status-body">
      <div className="upload-status-title"><h3>{job.display_name || job.source_identity || (job.kind === "slack" ? "Slack processing" : "PDF processing")}</h3><div><span className="source-version">{job.version_label || "Version not recorded"}</span><JobBadge job={job} /></div></div>
      <div className="job-metrics" aria-live="off">
        <div><Timer size={17} /><span>Total elapsed<strong>{durationLabel(elapsedMilliseconds(job.created_at, job.finished_at, now))}</strong></span></div>
        <div><Clock3 size={17} /><span>{(job.attempts || 1) > 1 ? "Before latest attempt" : "Time in queue"}<strong>{durationLabel(elapsedMilliseconds(job.created_at, job.started_at || job.finished_at, now))}</strong></span></div>
      </div>
      <p className="job-current-stage" role="status">{current ? <><LoaderCircle size={15} className="spin" />{stageLabels[current] || "Processing"}</> : <><Clock3 size={15} />{job.status === "queued" ? "Waiting for the office worker" : job.status === "running" ? "Processing — stage not recorded" : job.status === "failed" ? "Processing stopped" : "Processing finished"}</>}</p>
      {recordedStages.length ? <ol className="job-stage-list" aria-label="Processing stages">{stages.map((key) => {
        const stage = recordedStages.find((s) => s.key === key);
        const running = current === key;
        const Icon = stage?.status === "completed" ? Check : stage?.status === "failed" ? AlertCircle : icons[key as keyof typeof icons];
        return <li key={key} className={`job-stage ${running ? "stage-active" : stage ? `stage-${stage.status}` : "stage-pending"}`} aria-current={running ? "step" : undefined}>
          <span className="job-stage-icon"><Icon size={16} /></span>
          <div><strong>{stageLabels[key]}</strong><span>{running ? "In progress" : stage?.status === "completed" ? "Completed" : stage?.status === "failed" ? "Failed" : stage?.status === "interrupted" ? "Interrupted" : isProcessing(job) ? "Not started" : "Not recorded"}
            {stage?.total !== undefined && ` · ${stage.completed || 0} / ${stage.total} pairs`}</span>
            {running && !!stage?.total && <progress aria-label="Policy pairs compared" value={stage.completed || 0} max={stage.total} />}</div>
          <time aria-live="off">{stage ? durationLabel(stage.elapsed_ms ?? (running ? elapsedMilliseconds(stage.started_at, null, now) : null)) : "—"}</time>
        </li>;
      })}</ol> : <p className="job-progress-unavailable">{job.status === "queued" ? "Stage timings will appear when processing starts." : "Stage timings were not recorded for this earlier upload."}</p>}
      <p className="selected-upload-description" role="status">{jobDescription(job)}</p>
      {jobDisplayState(job)!=="withdrawn" && !!job.review_summary?.total && !!job.review_reason && !isProcessing(job) && job.status!=="failed" && <div className="job-processing-warnings"><strong>Processing warnings</strong><p>{processingWarnings(job)}</p></div>}
      <div className="upload-result-actions">
        {job.source_id && <><button className="text-button" onClick={onFindings}>View findings<ArrowRight size={14} /></button><button className="text-button" onClick={onInspect}>Inspect source</button></>}
      </div>
      <details className="job-technical"><summary>Processing details</summary><dl>
        <dt>Original processing result</dt><dd>{jobLabels[job.status]}</dd><dt>Job</dt><dd>{job.job_id}</dd><dt>Mode</dt><dd>{job.mode}</dd>
        <dt>Attempts</dt><dd>{job.attempts ?? "Not recorded"}{job.max_attempts ? ` of ${job.max_attempts}` : ""}</dd>
        <dt>Submitted</dt><dd>{date(job.created_at, true)}</dd>{job.finished_at && <><dt>Finished</dt><dd>{date(job.finished_at, true)}</dd></>}
        {job.error_code && <><dt>Error</dt><dd>{job.error_code}</dd></>}
      </dl>{!!progress?.previous_attempts?.length && <p>Stage timings above are for the latest attempt. Total elapsed includes earlier attempts.</p>}</details>
    </div>
    {(canRetry || onUpload || onImportSlack) && <footer className="dialog-footer upload-status-footer">
      {onImportSlack && <button className="button secondary" onClick={onImportSlack}><MessageSquare size={15} />Import saved Slack</button>}
      {onUpload && <button className="button secondary" onClick={onUpload}><ArrowUpFromLine size={15} />Upload another PDF</button>}
      {canRetry && <button className="button primary" disabled={retrying} onClick={onRetry}><RefreshCw size={15} className={retrying ? "spin" : ""} />{retrying ? "Retrying comparison…" : "Retry comparison"}</button>}
    </footer>}
  </>;
}
