import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, ArchiveX, LoaderCircle } from "lucide-react";
import { api, ApiError } from "./api";
import { Loading, Modal } from "./components";
import Select from "./Select";
import { date, sourceTitle } from "./presentation";
import type { Office, Source } from "./types";
import type { WithdrawalPreview, WithdrawalScope } from "./sourceWithdrawal";

export default function WithdrawSource({
  office,
  source,
  onClose,
  onWithdrawn,
}: {
  office: Office;
  source: Source;
  onClose: () => void;
  onWithdrawn: (ids: string[]) => void;
}) {
  const [scope, setScope] = useState<WithdrawalScope>("version"),
    [preview, setPreview] = useState<WithdrawalPreview | null>(null),
    [revision, setRevision] = useState(0);
  const [reason, setReason] = useState(""),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setPreview(null);
    api<WithdrawalPreview>(
      `${office}/sources/${encodeURIComponent(source.source_id)}/withdrawal?scope=${scope}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setPreview(value);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [office, source.source_id, scope, revision]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || loading || !preview?.version_count) return;
    if (!reason.trim()) {
      setError("Enter a reason for withdrawing this source.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api<{ withdrawn_source_ids: string[] }>(
        `${office}/sources/${encodeURIComponent(source.source_id)}/withdrawal`,
        {
          method: "POST",
          body: JSON.stringify({
            scope,
            reason: reason.trim(),
            expected_snapshot: preview.snapshot,
          }),
        },
      );
      onWithdrawn(result.withdrawn_source_ids);
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 409) setRevision((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Withdraw source"
      onClose={onClose}
      busy={busy}
      className="withdraw-source-dialog"
    >
      <form
        ref={form}
        onSubmit={submit}
        aria-busy={busy}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            (event.ctrlKey || event.metaKey) &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            form.current?.requestSubmit();
          }
        }}
      >
        <div className="dialog-body withdraw-source-body">
          <div className="withdraw-source-title">
            <h3>{sourceTitle(source)}</h3>
            <span className="source-version">{source.version_label}</span>
          </div>
          <fieldset disabled={busy} className="withdraw-fields">
            <div className="withdraw-field">
              <label>Versions to withdraw</label>
              <Select
                label="Versions to withdraw"
                value={scope}
                options={[
                  {
                    value: "version",
                    label: `This version · ${source.version_label}`,
                  },
                  { value: "all_versions", label: "All uploaded versions" },
                ]}
                onChange={(value) => {
                  setScope(value as WithdrawalScope);
                  setError("");
                }}
              />
            </div>
            <section
              className="withdraw-impact"
              aria-label="Withdrawal impact"
              aria-live="polite"
            >
              {loading ? (
                <Loading label="Checking affected records…" />
              ) : preview ? (
                <>
                  <dl>
                    <div>
                      <dt>Versions to withdraw</dt>
                      <dd>{preview.version_count}</dd>
                    </div>
                    <div>
                      <dt>Findings to make historical</dt>
                      <dd>{preview.finding_count}</dd>
                    </div>
                    <div>
                      <dt>Processing jobs to stop</dt>
                      <dd>{preview.job_count}</dd>
                    </div>
                  </dl>
                  <ul aria-label="Selected source versions">
                    {preview.versions.map((version) => (
                      <li key={version.source_id}>
                        <strong>{version.version_label}</strong>
                        <span>
                          {version.status === "withdrawn"
                            ? "Already withdrawn"
                            : `Added ${date(version.ingested_at)}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {preview.answer_count > 0 && (
                    <p>
                      {preview.answer_count} saved{" "}
                      {preview.answer_count === 1
                        ? "answer keeps its"
                        : "answers keep their"}{" "}
                      historical citations.
                    </p>
                  )}
                  {preview.version_count === 0 && (
                    <p>These versions are already withdrawn.</p>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setError("");
                    setRevision((n) => n + 1);
                  }}
                >
                  Retry impact check
                </button>
              )}
            </section>
            <div className="withdraw-field">
              <label htmlFor="withdraw-reason">Reason</label>
              <textarea
                id="withdraw-reason"
                name="reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={1000}
                required
                rows={3}
              />
            </div>
          </fieldset>
          <p className="withdraw-consequence">
            Withdrawn versions are excluded from current evidence. Documents and
            history are retained.
          </p>
          <div className="withdraw-error" role="alert">
            {error && (
              <>
                <AlertCircle size={16} />
                <span>{error}</span>
              </>
            )}
          </div>
        </div>
        <footer className="dialog-footer">
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={
              busy || loading || !preview?.version_count || !reason.trim()
            }
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <ArchiveX size={16} />
            )}
            Withdraw {scope === "all_versions" ? "versions" : "source"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
