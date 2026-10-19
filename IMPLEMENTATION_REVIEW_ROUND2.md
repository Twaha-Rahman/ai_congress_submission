# Implementation review — round 2

Date: 2026-10-19. This report reviews the updated implementation after the R1–R10 repair pass. It supplements, rather than replaces, `IMPLEMENTATION_REVIEW.md`.

The repair pass makes meaningful improvements. The original forged-root attack, use of invalidly signed exports, ordinary-reader access to privileged saved answers, hosted-model permission bypass, first-rule-only retention aggregation, and byte-insensitive version deduplication now have relevant fixes. Docker's declared mounts and build contents are also substantially improved.

The remaining findings below were independently reproduced. Passing the supplied tests and evaluation does not cover these combinations of paths.

## Verification performed

| Check | Independently observed result |
|---|---|
| `.venv/bin/python -m pytest` | **77 passed in 1.12 seconds** |
| Full replay evaluation on isolated ports 18090–18092 and separate review databases | **166/166 checks passed**, 41/41 labels; TP 30, FP 0, FN 0 |
| `docker compose config --quiet` | Passed |
| Focused probes with temporary databases, real rules/ingestion/query code, direct authenticated-principal route calls, and mocked HTTP transport | Findings F1–F7 below |

Evaluation results are saved in `evidence/review_round2_eval.json`; probe observations are in `evidence/review_round2_probes.jsonl`. The probe named `different_valid_date_replaces_snapshot` actually varies the source `known_at` cutoff; the other target and `valid_at` remain unchanged. Both are query-context fields that the selector needs to respect.

The evaluation launched and stopped its own local HTTP services without resetting the ordinary demo databases. No paid model calls were made. Docker containers were not started or rebuilt in this review, and a backup-laptop rehearsal was not performed. Application and test source files were not changed.

## Status of the original findings

| Original finding | Current assessment |
|---|---|
| R1 — API authorization | Saved-answer/bundle reauthorization and office checks repaired; lineage still leaks restricted finding metadata (F7) |
| R2 — Merkle root binding | Original attack repaired; comparison transport has a separate signature problem (F4) |
| R3 — Invalid export use | Original rejection path repaired; explicit historical cutoffs are still rewritten (F5) |
| R4 — Hosted processing permission | Required permission now reaches the model service and blocks transport; another egress endpoint bypasses office export permission (F1) |
| R5 — Extraction semantics | Reversed bounds/operators addressed; omitted bounds still accepted (F2) |
| R6 — Retention aggregation | Original contradictory-requirements case repaired and tested in both ingestion orders |
| R7 — Imported claim freshness | Snapshot mechanism added; selection still conflates different query contexts (F3) |
| R8 — Filesystem isolation | Compose/Dockerfile configuration repaired and syntactically valid; running-container isolation not independently repeated here |
| R9 — Incomplete replacement | Previous revisions are preserved with a pending state; pending state is not filtered by historical time (F6) |
| R10 — Version identity | Original file-byte and trusted-metadata checks repaired |

## F1 — P1: comparison responses bypass office-export permission

Location: [comparison handler](meridian/office_api/main.py#L713), particularly the engine invocation at line 733. The engine's source filter at `meridian/queries/engine.py` checks restricted sensitivity, not whether local facts are permitted to leave the office.

**Reproduction:** ingest the Frankfurt seven-year policy as `demo_shareable` but with `permissions.office_export=false`. Invoke `/v1/comparisons` as the correctly scoped Frankfurt service principal. The handler returns `answered`, the seven-year requirement, its governing facts, policy family, and citation identifiers to the inter-office caller. The ordinary claim-export endpoint would withhold that source.

This is a derivative-data disclosure: removing the literal quote does not prevent the policy's content from being exported as an answer or rule summary. The comparison route is part of the actual gateway path, not an unused administrator endpoint.

**Required fix:** apply an explicit derivative export policy to the comparison result before transport. If non-exportable local policy is allowed to support a narrowly approved predicate, define that permission and predicate contract explicitly; the current `office_export=false` contract does not grant it. Do not return general rule values, prose, or identifiers under an assumed exception. Audit the actual comparison response through the same outbound policy boundary.

**Regression gate:** a shareable-but-non-exportable source cannot reveal its rule through `/v1/federation/claims`, `/v1/comparisons`, or gateway responses. Test sensitivity and export permission independently.

## F2 — P1: dropping a threshold still creates an accepted false rule

Location: [_amount_direction_findings](meridian/extraction/validate.py#L268), especially the skip for missing/zero bounds at line 280.

**Reproduction:** use the existing validation-test clause:

> A business loan in USD with an amount greater than USD 25,000 requires at least two approvals from the credit committee.

Submit the correct two-approval requirement but scope it to `(0, infinity)` rather than `(25000, infinity)`. The validator accepts it with **no reviews**. The manifest's broad loan scope covers the incorrect proposal, and the bound-checking loop has no nonzero proposed bound to check.

The fix now verifies the direction of a bound when the model supplies one. It does not require a bound stated in the source to be present in the extracted claim. A model omission can therefore extend a policy to loans the clause never covered.

**Required fix:** parse the supported source applicability constraints independently and compare them with the complete proposed scope. A dropped lower/upper bound, a missing condition, or an unsupported interpretation must require review. Checking only the proposed fields cannot establish that the source's restrictions were preserved.

**Regression gate:** omission of either side of a source amount band must be rejected/reviewed, alongside the already-tested reversed direction and inclusivity cases.

## F3 — P1: historical exports can erase the current remote snapshot

Locations: [_latest_snapshot_by_origin](meridian/federation/exchange.py#L407) and [select_remote_snapshots](meridian/federation/exchange.py#L425).

The selector groups snapshots only by origin within a subject. It does not select by the stored `target_fingerprint`, source `valid_at`, or source `known_at`. Every complete response becomes the latest snapshot for that entire origin/subject, even though an export is only complete for the subquery that produced it.

**Reproduction:**

1. Import Dhaka's five-year procedure at the current source knowledge snapshot. Frankfurt correctly reports the gap against its seven-year policy.
2. Ask Dhaka the same question with source `known_at` in January, before Dhaka learned that procedure. This produces a legitimate, signed empty export.
3. Import that historical export later, then repeat the current Frankfurt question.

The current answer now omits the procedure and its gap because the later receipt of a historical empty export replaced the current snapshot. No actual source policy changed. The earlier current snapshot's remote citation count is one; afterward it is zero.

**Required fix:** bind snapshot eligibility to the complete query context. Explicit snapshot IDs should be checked against the comparison's target and relevant source time parameters. A response to a historical or different-scope query must not retire current knowledge outside that response's context. Keep recipient receipt time separate from source snapshot time.

**Regression gate:** interleave current and historical queries, two targets, empty exports, and concurrent requests. Each current query must retain the correct facts or explicitly request a fresh matching snapshot; it must not silently use an unrelated latest response.

## F4 — P2: the transmitted comparison answer cannot verify against its signature

Location: [post-signing quote removal](meridian/office_api/main.py#L744).

The handler generates and signs an answer containing citation quotes, removes those quotes from the returned object, and returns the original hash and signature beside the altered object. The transport note explicitly discloses this behavior, but disclosure does not provide the receiver with verifiable answer bytes.

**Reproduction:** hash the canonical `answer` returned by `/v1/comparisons` and verify its attached signature using the pinned Frankfurt key. Both the hash comparison and Ed25519 verification fail. The gateway therefore cannot authenticate the exact answer it receives with the attached signature.

**Required fix:** define an export-safe answer projection, apply authorized redactions first, then hash and sign that exact projection. Retain the full local answer as a separate signed record if needed, with a clear relation between the two. Verify the exported answer at the gateway.

**Regression gate:** a normal comparison response verifies without access to undisclosed source text; changing any returned fact, citation reference, time scope, or result causes failure.

## F5 — P1: explicit known_at is advanced to import receipt time

Location: [import_then_compare](meridian/gateway_api/orchestrator.py#L170), especially the timestamp rewrite at line 215.

**Reproduction:** supply an explicit `known_at=2026-03-10T12:00:00Z`; have the import return a receipt five seconds later. The outgoing comparator request uses `known_at=2026-03-10T12:00:05Z` instead. For a genuinely historical query, the same code can move the cutoff months forward.

This was added intentionally to make a newly received snapshot eligible, and the remediation test currently asserts that behavior. However, the same timestamp filters the requesting office's local policies. Advancing it can introduce policies that the office did not know at the requested cutoff. The system is then answering a different temporal question.

**Required fix:** preserve an explicitly requested historical knowledge cutoff. If no suitable recipient snapshot existed then, return partial/abstained or implement a clearly documented historical reconstruction using separately named source snapshot and recipient receipt parameters. For a default current query, capture an appropriate execution snapshot explicitly without treating that as permission to rewrite a user's historical cutoff.

**Regression gate:** introduce a local policy between the requested cutoff and import receipt; it must not appear in an answer requested as of the earlier time. Update the existing regression that currently requires timestamp advancement.

## F6 — P2: pending replacement warnings leak into earlier history

Locations: [pending marker selection](meridian/queries/engine.py#L200) and `OfficeStore.pending_replacements` in `meridian/storage/store.py`.

**Reproduction:** ingest v2, then an unvalidated v3 effective February 1 and learned in February. Ask about January 15 with `valid_at=January 15` and `known_at=January 15`. The answer becomes `needs_review` and warns about the later pending replacement, even though neither the replacement's effective date nor its knowledge time belongs to that snapshot.

The pending-marker lookup ignores both query time parameters; it only matches affected old revision IDs. It also needs the same sensitivity checks as the source that created the marker.

**Required fix:** make pending replacement state temporal and authorized. Filter it by replacement effective scope/date, backend receipt time, requested knowledge cutoff, and source access. Preserve old snapshots when a pending replacement is subsequently resolved.

**Regression gate:** January queries remain unchanged after learning a pending February replacement; current affected queries still require review; hidden pending sources do not expose their existence to readers.

## F7 — P2: lineage exposes findings the direct API now correctly hides

Location: [graph traversal](meridian/queries/lineage.py#L39). Also inspect sensitivity derivation when finding/answer nodes are created.

**Reproduction:** seed the existing restricted credit note plus public lending policies, then generate a public-reader answer with restricted claims excluded. Its lineage graph includes **two finding node IDs** whose underlying comparisons reference the restricted credit note. Those findings are filtered out by the repaired direct findings endpoint.

The traversal omits restricted nodes from its returned node set but still traverses their edges. Finding nodes are marked unrestricted, so their IDs, labels, severity metadata, and connections can remain visible through a public graph root. No restricted source quote was observed in this probe; the leak is existence/metadata.

**Required fix:** authorize each reachable node and its provenance before adding it or expanding its edges. Derived finding and answer nodes must inherit source restrictions. Stop traversal at an unauthorized node; removing dangling edges afterward is insufficient.

**Regression gate:** the public answer's lineage cannot contain IDs or metadata for findings/answers the same caller could not retrieve directly. Test with mixed public/restricted graph components and a privileged-created answer linked through a shared public source.

## Recommended next pass

Keep the repaired structure. Add regression cases for these seven observations, fix the comparison export/signing boundary and snapshot semantics, then rerun the same offline suite and full isolated evaluation. Retain the genuine OpenRouter extraction and backup-laptop rehearsal as separate acceptance work: neither was performed by this review.
