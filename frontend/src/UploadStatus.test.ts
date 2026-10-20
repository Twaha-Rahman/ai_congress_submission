import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import UploadStatus from "./UploadStatus.tsx";
import type { UploadJob } from "./types";

const noop = () => {};
const job = { job_id: "old-job", kind: "pdf", status: "needs_review", mode: "live",
  created_at: "2026-10-20T00:00:00Z", started_at: "2026-10-20T00:00:01Z",
  finished_at: "2026-10-20T00:02:46Z", source_identity: "Travel policy", version_label: "v1" } as UploadJob;

test("older jobs with empty or absent telemetry remain readable", () => {
  for (const progress of [undefined, {}]) {
    const html = renderToStaticMarkup(createElement(UploadStatus, { job: { ...job, progress } as UploadJob,
      canRetry: false, retrying: false, onRetry: noop, onInspect: noop, onFindings: noop }));
    assert.match(html, /Stage timings were not recorded/);
    assert.match(html, /2m 46s/);
  }
});

test("running job shows the actual stage and pair counts", () => {
  const html = renderToStaticMarkup(createElement(UploadStatus, { job: { ...job, status: "running", finished_at: null,
    progress: { attempt: 1, current_stage: "comparison", stages: [{ key: "comparison", status: "running",
      started_at: job.started_at!, finished_at: null, elapsed_ms: null, completed: 4, total: 24 }] } },
    canRetry: false, retrying: false, onRetry: noop, onInspect: noop, onFindings: noop }));
  assert.match(html, /Comparing policies/);
  assert.match(html, /4 \/ 24 pairs/);
  assert.match(html, /aria-current="step"/);
});
