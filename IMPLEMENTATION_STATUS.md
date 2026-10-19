# Implementation Status

Last updated: 2026-10-19

This file records actual progress and verification. It is not a projection or a plan.
The R1–R10 implementation-review remediations and their offline regressions are now
implemented. Two acceptance items remain open: a genuine hosted-model call
(`LLM_MODEL` and an OpenRouter key are not configured here) and a rehearsal on a second
laptop. Those are reported as open items, not as passed checks.

## Current status

| Area | Status |
|---|---|
| Stages 1-3: contracts, ingestion, history, queries, evidence | Implemented; offline gates passed |
| Stage 4: live/cached/replay adapter | Implemented; offline/fake-transport gate passed; one genuinely live uncached extraction NOT run |
| Stage 5: two offices and federation | Implemented; demo and evaluation gates passed |
| Stage 6: packaging, evaluation, demonstrations | Implemented and rehearsed offline on this laptop; live rehearsal and backup-laptop rehearsal NOT run |
| Overall delivery | **Not claimed fully complete** against every item in brief section 7 / plan section 12.3, because live and backup-laptop checks remain outstanding |

## Stage log

| Stage | Status | Gate result |
|---|---|---|
| 0. Repository inspection and fixed choices | Complete | Python 3.11.15 venv, pinned lock file, separate office/gateway APIs, no frontend, no local model server required |
| 1. Contracts, fixtures, pure rule functions | Complete | 82 offline tests; evaluation compares 41 labels across 10 complete scenarios |
| 2. Durable ingestion and one-office replay | Complete | PDF and Slack ingestion through HTTP APIs; duplicate delivery, changed bytes, restart recovery and authorization covered |
| 3. Temporal history, queries, signed evidence | Complete | Demo 2 history/tamper checks passed; bundle verification and source-copy checks passed |
| 4. Real model adapter and visible modes | Offline gate complete; live smoke blocked | Fake transport covers success/schema/malformed/hallucination/timeout/provider failure; live modes fail visibly without credentials |
| 5. Two offices and federation | Complete | Demo 3 5-year procedure vs 7-year policy gap; restricted export blocked; canary absent; outage probes passed in evaluation |
| 6. Packaging, evaluation, rehearsal | Offline gate complete; two rehearsals outstanding | Docker build/up and office-isolation probes passed; replay/cached demos and evaluation 166/166 passed; live and backup-laptop rehearsals not performed |

## Stage details and actual evidence

### Stage 0 - repository and environment

- Python 3.11.15 is available; the project virtualenv is `.venv`.
- Dependencies are pinned in `requirements.lock.txt`.
- Docker 29.9.1 and Docker Compose 5.6.0 are available on this host.
- `make setup` creates Ed25519 keys, pinned public keys, demo bearer tokens, runtime
  directories and a mode-0600 `.env`; it is idempotent and does not overwrite configured
  model values or keys.
- Each office receives only its own runtime directory and private-key directory, its
  own replay/cache assets, public-key pins and configuration. The gateway receives only
  its relay-log directory, public-key pins and configuration; raw corpus fixtures are
  excluded from the image and gateway mounts.

### Stage 1 - contracts, fixtures, and pure rules

Implemented:

- Strict Pydantic contracts for manifests, extraction proposals, claims, findings,
  answers, verification bundles and federation payloads.
- Integer minor units for money; normalized decimal strings for retention years;
  timezone-aware, half-open UTC intervals.
- Amount interval intersection, allowed-set comparison, scope intersection,
  supersession/staleness handling and classification.
- Development and held-out evaluation families split by whole policy family, never by
  random pairs sharing a source.

Verification:

```text
$ make test
65 passed in 0.61s
```

The suite includes constructed claims outside the demo wording: inclusive/exclusive
endpoints, singleton and empty intervals, minimum-vs-maximum conflicts, negation and
number normalization, incompatible scopes, canonical encoding and schema rejection.

### Stage 2 - durable ingestion and one-office replay

Implemented:

- Append-only migrations; immutable original source bytes; normalized source identity
  stored separately from content and file hashes.
- PDF extraction from preserved parser text and saved-Slack normalization.
- Durable jobs persisted before upload acknowledgement, one worker per office, bounded
  retries and startup recovery for interrupted `running` jobs.
- Transactional publication of source versions, claims and findings.
- Server-derived tenant/office authorization and uploader/reader/reviewer/service roles.
- Replay proposals pass through the real validators; the model cannot set authority,
  permissions, sensitivity or supersession.

Verification:

- `scripts/seed.py` ingests the five baseline sources through the normal APIs:
  4 Dhaka sources / 8 claims / 5 findings and 1 Frankfurt source / 1 claim.
- `tests/test_pipeline.py` verifies duplicate delivery is idempotent and changed bytes
  under an existing version identifier are rejected.
- `tests/test_jobs.py` verifies a restarted process requeues an unfinished job without
  losing its attempt count, and fails an interrupted job whose attempts are exhausted.
- `tests/test_authz.py` verifies unknown/missing tokens, tenant mismatch, restricted
  access and service identity restrictions.
- Docker seed output is recorded in `evidence/docker_validation.txt`.

### Stage 3 - temporal history, queries and signed evidence

Implemented:

- Separate `valid_at` (effective) and `known_at` (knowledge) axes.
- Explicit, scoped supersession from trusted manifests; signed append-only closure events;
  corrected history carried as new signed revisions and excluded from fresh findings.
- Deterministic FTS5 plus structured retrieval, scoped answers, citations, lineage and
  append-only review events.
- Canonical JSON, RFC 9162 Merkle trees, Ed25519 signatures and pinned-key verification.
- Per-component bundle verification: answer text/hash, answer signature, claim signatures,
  manifest signatures, clause inclusion and answer binding.
- Separate file identity from passage identity, so metadata-only edits differ from
  modified text.

Verification from the final replay rehearsal (`evidence/final_demo_replay.txt`):

```text
one high-severity stale guidance finding for (USD 25,000.00, USD 50,000.00]
explicit v2 replacement produced no active contradiction alert
history is version-correct on both axes (valid_at and known_at)
untouched bundle verifies against pinned keys
tampered answer fails: answer_signature, answer_text_hash
```

Source-copy verification reported file-hash failure for the metadata-only copy while
clause text and Merkle root still passed; the modified-text copy failed all four checks.
The 13 PASS assertions cover all three demo stories.

### Stage 4 - real model adapter and visible modes

Implemented:

- OpenRouter-compatible live provider with strict JSON schema, temperature/provider
  routing, bounded timeout/retries and usage/latency/route metadata.
- Versioned cache keys including model, endpoint, temperature, provider preferences,
  parser/prompt/schema versions and clause hashes.
- Explicit `live`, `cached` and `replay` modes, labelled in jobs, stage metadata and
  answers. Missing credentials, missing cache entries and missing replay data fail
  visibly; there is no fallback to another mode.
- Source text is treated as untrusted data. The model has no tools, and its output cannot
  alter manifests, authority or permissions.

Verification:

- Fake `httpx.MockTransport` tests cover success with usage metadata, malformed JSON,
  schema violation, hallucinated quote reaching the validator, timeout, transient 503
  retry and no-silent-fallback behavior.
- `make demo-live` exits 2 without credentials:

```text
live demo prerequisite missing: set LLM_MODEL and LLM_API_KEY (OpenRouter) in .env.
No replay fallback is performed.
exit_code=2
```

- A live-mode PDF ingestion and a live-mode Slack ingestion through the API were exercised
  on this host. Both jobs ended `failed` with mode `live`, error code `missing_credentials`
  and the reason `LLM_MODEL/LLM_API_KEY are not configured; live extraction was not
  attempted`. Evidence: `evidence/live_missing_credentials.txt` and
  `evidence/live_slack_missing_credentials.txt`.

Not executed: one genuinely uncached hosted-model extraction, with actual model/route,
latency and token usage recorded. No live result is fabricated or substituted here.

### Stage 5 - two offices and federation

Implemented:

- Same office code with separate databases, source volumes, credentials, keys and model
  settings for Dhaka and Frankfurt.
- Gateway orchestration, typed federation subqueries, source-office export policy,
  recipient signature verification and isolated `remote_claims`.
- Allowlisted structured claims only; opaque remote citations; `clause_inclusion =
  not_checked` when remote passage text was not transferred.
- Separate office-egress and hosted-model audit channels with measured payload bytes.
- Restricted evidence filtered before query computation, lineage and federation;
  service identities cannot download raw source content.

Verification from the final replay rehearsal:

```text
The planned operating procedure retains records for exactly 5 years from loan_closure,
which does not meet the requirement of at least 7 years (5 < 7).
typed federation produced the 5-year procedure vs 7-year policy gap
remote citation stays opaque; passage text did not cross the border
restricted-only export returned zero claims and an explicit denial reason
canary absent from office export and gateway relay log
raw_source_bytes_between_offices=0
```

Evaluation additionally passed an office-outage probe with a visible partial/abstained
result and a structured `503 office_unavailable` failure.

### Stage 6 - packaging, evaluation and demonstrations

Implemented:

- Dockerfile, Compose stack, local process supervisor, Makefile, README and `.env.example`.
- `make setup`, `test`, `up`, `down`, `local-up`, `local-down`, `seed`, `demo-replay`,
  `demo-cached`, `demo-live`, `evaluate`, `reset-demo` and `openapi`.
- OpenAPI export for 25 office operations and 4 gateway operations, including bearer
  authentication, request-body schemas for manually parsed endpoints, representative
  examples and nullable fields.
- Evaluation runner with isolated ports/databases, labelled corpus, per-scenario metrics,
  timing, model-use and resource observations.
- Reset guard rails: only the `meridian_demo` tenant and paths under `runtime/`; refuses
  while services are healthy; preserves keys, fixtures and exported evidence.

Docker validation (`evidence/docker_validation.txt`):

- Image build and `docker compose up -d` completed.
- Office `/health` and `/ready` returned healthy/ready for both regions.
- Gateway `/ready` returned true; gateway `/health` reports `"database_present":"false"`
  and `"raw_source_volumes":"none"`.
- `scripts/seed.py --mode replay --no-ensure` completed five ingestion jobs and produced
  the baseline inventory.
- Office query returned the two-approval answer with the v3 citation.
- Gateway query returned `answered` with one Dhaka contribution and zero Frankfurt
  contributions, and `no_raw_source_text_transferred: true`.
- Containers run as the host UID/GID, so generated runtime files are removable by
  `make reset-demo`; `docker compose down` followed by reset removed all five demo paths.
- `docker compose config` validates; the obsolete Compose `version` key was removed.

Evaluation (`make evaluate`, final run):

```text
scenarios       10 (41 labels)
findings        TP 30  FP 0  FN 0  precision 1.0  recall 1.0
label accuracy  type 1.0  scope 1.0  persistence 41/41
checks          166/166 passed
total wall      35.92 s
ingestion       10.17 s for 38 source events
startup         0.75-0.76 s per fresh scenario stack
resources       max service RSS 213.7 MB; evaluation process peak 67.7 MB
model use       38 replay extraction invocations; no provider/network calls
```

This is a small synthetic corpus authored by the implementation team. It is prototype
evidence, not an estimate of production accuracy.

## The three demonstrated stories

All three ran end to end in replay and cached modes. Each rehearsal had 13 PASS
assertions and left JSON evidence.

1. **The Catch.** Ingesting the March Slack guidance produced exactly one high-severity
   `stale_guidance` finding for `(USD 25,000.00, USD 50,000.00]`. The explicit v2 -> v3
   supersession produced no active contradiction. Evidence: `evidence/demo1_finding.json`.
2. **The Trace.** Boundary behavior was correct at USD 25,000, 25,000.01, 50,000 and
   50,000.01. January `valid_at` selected v2; `known_at` one microsecond before v3
   ingestion cited only v2; later ingestion did not rewrite history. The answer had a
   verifiable signature and real citations. The untouched bundle verified; the tampered
   answer failed `answer_text_hash` and `answer_signature`. Evidence:
   `evidence/demo2_bundle.json`, `evidence/final_demo_replay.txt`.
3. **The Border.** The gateway obtained a signed Dhaka export, Frankfurt verified and
   imported it, and the comparator produced a 5-year procedure vs 7-year policy
   `compliance_gap`. The remote citation was opaque, a restricted-only export was denied
   with `egress_denied_restricted_source`, service access to raw content returned 403,
   the restricted-text canary was absent from exports/relay logs, and measured
   office-to-office raw-source bytes were zero. Evidence:
   `evidence/demo3_federation.json`.

## Exact verification commands and outcomes

| Command | Actual outcome |
|---|---|
| `make setup` | Idempotent; existing keys/tokens/model values preserved; `.env` mode 0600 |
| `make test` | `65 passed in 0.61s` (offline; no paid calls) |
| `make demo-replay` | Reset + seed + all three stories complete; 13 PASS assertions |
| `make demo-cached` | Explicit cached extraction + all three stories complete; 13 PASS assertions |
| `make demo-live` | Exit 2: missing `LLM_MODEL` / `LLM_API_KEY`; no replay fallback |
| `make evaluate` | TP 30, FP 0, FN 0; precision/recall 1.0; type/scope 1.0; persistence 41/41; checks 166/166 |
| `make openapi` | 25 office operations + 4 gateway operations; Bearer auth and examples emitted |
| `make up` / `docker compose up -d` | 3 healthy containers; `/health` and `/ready` passed |
| `make seed` under Compose | 5 jobs succeeded; baseline inventory produced |
| `make down` then `make reset-demo` | Removed 5 demo paths; preserved keys, fixtures, evidence |

## Capability classification

### Implemented and exercised end to end

- PDF and saved-Slack ingestion through the HTTP APIs.
- Manifest trust boundary, evidence validation, review states, idempotence and restart
  recovery.
- Effective-time and knowledge-time history, explicit supersession, signed closures and
  carried-forward revisions.
- Deterministic findings, scoped queries, citations, lineage, review events and abstention.
- File/passage integrity, Merkle proofs, Ed25519 signatures, signed answers and
  per-component bundle verification.
- Restricted-evidence filtering across source, query, lineage, findings and federation.
- Two-office isolation, signed typed federation, gateway orchestration, remote-claim
  storage, opaque citations and `not_checked` clause inclusion.
- Docker Compose packaging, health/readiness, seed, query and reset.
- Offline evaluation, OpenAPI export and the three demonstrations.

### Implemented but replay-backed or synthetic in this environment

- Extraction proposals for all demos and evaluation scenarios come from versioned replay
  fixtures or the synthetic cache. They pass through the real validators, comparison
  engine, persistence and signing; they are not live model output.
- Evaluation metrics describe the committed synthetic corpus, not production data.
- Model metadata in replay knows no provider usage; the evaluation records zero network
  calls and does not invent tokens or cost.

### Implemented but not validated with the real external dependency

- Genuine OpenRouter extraction: the adapter is exercised only with a fake HTTP transport.
- Live uncached Slack extraction and its actual model route/latency/usage.
- Provider-side failures beyond the simulated transport cases (real rate limits, account
  quota, model deprecation, regional network behavior).

### Deferred / out of scope

- Production identity provider (the current bearer map is a demo mechanism).
- Horizontal scaling or multi-node SQLite; OCR/scanned PDFs; arbitrary chat exports.
- Subjects, currencies or conditions outside the two proposal subjects and USD scope.
- Buyer interviews, NRB participation, venue logistics and production compliance claims.

## External prerequisites and unmet acceptance checks

- **Live model:** `LLM_MODEL` and `LLM_API_KEY` (or office-specific equivalents) are not
  configured. Acceptance check 12.3 item 13 and the Stage 4 live gate therefore remain
  open. When configured, run `make demo-live` and record the actual route/model, latency
  and token usage.
- **Backup laptop:** only this primary host was rehearsed. Acceptance check 12.3 item 13
  explicitly requires a clean reset and replay on a backup laptop as well.
- **Human evidence:** buyer interviews, NRB collaboration, venue/connectivity planning and
  a manual-review time baseline were not performed and are not claimed.
- **Production security:** static demo principals/tokens and bind-mounted local keys are
  suitable for the hackathon demonstration, not a bank deployment.

## Environment facts observed

- Host: Linux, Python 3.11.15, Docker 29.9.1, Docker Compose 5.6.0.
- Live model credentials: absent at the last update.
- No local LLM or frontend is required for replay/cached operation.
- Docker containers use the host UID/GID (`MERIDIAN_UID` / `MERIDIAN_GID` from `.env`) so
  runtime files remain removable by the developer account.

## Evidence files

- `evidence/final_test.txt` - final offline test run.
- `evidence/final_demo_replay.txt` - full replay rehearsal.
- `evidence/final_demo_cached.txt` - full cached rehearsal.
- `evidence/final_evaluation.txt` and `evidence/evaluation_results.json` - evaluation run.
- `evidence/docker_validation.txt` - Compose health, readiness, seed and queries.
- `evidence/live_missing_credentials.txt` - live PDF path fails visibly.
- `evidence/live_slack_missing_credentials.txt` - live Slack path fails visibly.
- `evidence/demo1_finding.json`, `evidence/demo2_bundle.json`,
  `evidence/demo3_federation.json` - demo evidence.
- `docs/openapi/office.json`, `docs/openapi/gateway.json` - generated API documents.

## Implementation review R1–R10 remediation

Implemented in this pass:

- **R1 authorization:** every office endpoint now checks permission, tenant and office.
  Restricted findings, jobs and claim reviews are omitted for unprivileged callers;
  stored answers, bundles and lineage re-authorize each local cited source.
- **R2 evidence verification:** signed manifest wrapper fields and trusted metadata are
  bound to the authenticated payload; clause proofs are checked against its signed root
  and tree size; claim locators/quotes and answer citations are cross-bound. Missing
  local claim evidence fails verification; undisclosed remote evidence remains
  `not_checked`. Bundle construction no longer fabricates placeholder proofs.
- **R3 federation:** only verified exports enter federated answers. Import rejects
  request/origin/target/time binding mismatches, returns the exact snapshot ID and
  receipt time, and the gateway does not compare unless import succeeded.
- **R4 egress:** hosted extraction is denied before transport and cache writes unless
  the trusted manifest permits it or an approved loopback/private endpoint is used.
  Regression tests assert zero HTTP calls and zero transported source bytes on denial.
- **R5 extraction:** rule operators must be explicit and adjacent to the proposed value
  and unit; opposite directions and unsupported amount-bound direction/inclusivity are
  sent to review. Existing intended replay/evaluation patterns remain accepted.
- **R6 aggregation:** office and gateway retention answers intersect every applicable
  authoritative requirement, review empty intersections, compare all procedures, and
  cite every contributing rule. The held-out cross-border expectation now correctly
  states `needs_review` when the local seven-year minimum and four-year ceiling conflict.
- **R7 remote freshness:** each verified export is a complete recipient-side snapshot
  with receipt-time knowledge; current queries use only latest snapshots, while explicit
  unknown, future, incomplete or stale snapshot IDs are rejected.
- **R8 filesystem isolation:** office containers mount only their own runtime/key
  directories and office-specific replay/cache assets. The gateway mounts no fixtures,
  office data or private keys; fixtures are excluded from the Docker build context and
  image. The same-machine/geographic-simulation limitation remains.
- **R9 replacement safety:** replacement closures require validated rule coverage for
  every affected clause position. Zero/partial coverage preserves prior revisions and
  records a pending review; affected queries return `needs_review` with a specific
  pending-replacement warning.
- **R10 immutable identity:** duplicate delivery requires identical original bytes and
  canonical trusted metadata. Metadata-only file edits and manifest permission/effective
  date changes under the same identity/version are rejected.

Verification run after these changes:

```text
.venv/bin/python -m pytest -q       77 passed
make evaluate                       166/166 checks passed; 41/41 labels persisted
make demo-replay                    completed; 13 PASS assertions
make demo-cached                    completed; 13 PASS assertions
make openapi                        25 office + 4 gateway operations exported
docker compose build                passed
docker compose up -d                offices healthy; gateway started
container isolation probes          passed for Dhaka, Frankfurt and gateway
docker compose config --quiet       passed
```

The evaluation corpus is synthetic and team-authored; these metrics are not a claim of
production extraction accuracy. The Docker isolation probes verified that each office
cannot see the other office's runtime/private-key paths or raw source corpus, and that
the gateway cannot see office runtime paths, private keys or `/app/fixtures`.

Remaining acceptance gaps: no genuine hosted-model call was made because credentials
remain absent, and no backup-laptop clean reset/replay rehearsal was performed.

## Implementation review round 2

Implemented the seven follow-up findings in `IMPLEMENTATION_REVIEW_ROUND2.md`:

- **F1:** comparison output is blocked and audited if any applicable local source is
  non-exportable; the decision covers the full applicable snapshot, not just visible
  citations. The regular signed-claims endpoint independently withholds such rules.
- **F2:** validation parses amount limits from the source evidence independently of the
  proposed scope and sends omitted lower or upper limits to review.
- **F3:** remote snapshot selection is scoped by canonical target fingerprint, valid time,
  and source-office knowledge time. A later-received historical or different-target
  empty export cannot retire current facts.
- **F4:** comparison quotes are redacted before creating a quote-free projection; that
  exact projection is hashed and signed. The gateway checks the hash, pinned signature,
  tenant/region, projection-to-local-answer relation and quote absence before use.
- **F5:** explicit recipient `known_at` is never advanced. If an export arrives later,
  it is not passed as eligible; a missing required snapshot produces a visible
  `needs_review` incomplete result. A default current request uses the receipt moment.
- **F6:** pending replacement markers are filtered by creation/receipt time, effective
  date, affected applicable revisions and source sensitivity. Resolution time is stored
  so historical queries retain the pending state they knew at the time.
- **F7:** lineage authorizes each graph node against its source provenance before adding
  it or traversing its edges. Derived finding/answer nodes inherit access checks from all
  cited revisions.

Round-two regression coverage includes the reported source-scope omissions, historical
and alternate-target exports, a delayed explicit-cutoff import with a later local policy,
tampered signed comparison projections, non-exportable comparisons, temporal pending
resolution/access, and restricted-derived lineage.

Verification after round two:

```text
make test                            82 passed
make evaluate                        166/166 checks passed; 41/41 labels persisted
make demo-replay                     completed
make demo-cached                     completed
```

No live model call, Docker rebuild/container isolation rehearsal, or backup-laptop
rehearsal is claimed for this round.
