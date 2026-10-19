# Backend Implementation Brief

## 1. Read this first

Implement the backend described in [the revised proposal](ai_congress_hackathon_project_plan_revised.md). This brief provides the execution order, concrete development choices, and checks for the coding model. The revised proposal remains the source of product requirements; this brief does not remove its acceptance checks.

The intended implementation model is **DeepSeek V4.1 Flash 1017**. No feature is weakened based on its benchmark score. The work is divided into verifiable stages so implementation errors can be detected before they spread. The same workflow is suitable for other coding models.

**Distinguish two models:** the coding model writes this repository; the application's runtime model extracts rules through OpenRouter. They need not be the same model. Do not automatically configure the application to use DeepSeek, or assume a display name is a valid OpenRouter model ID. Runtime model/provider selection is configuration and requires a fixture-based check.

Before coding, read this brief and these proposal sections: 2–7 for behavior, 8–10 for trust boundaries and model modes, 11 for APIs/commands, and 12 for acceptance. Read sections 13–15 for demo constraints and delivery context. Do not implement business interviews, a frontend, or a local LLM installer.

Implement stages in order. Complete the applicable checks before moving on; continue without asking for approval between normal development stages. Keep a concise progress record in `IMPLEMENTATION_STATUS.md`: current stage, implemented behavior, commands actually run and their results, unresolved failures, and external prerequisites. Re-read it when resuming. Do not replace implementation with a plan or stop after scaffolding.

## 2. Goal and fixed choices

Build three services runnable on one 16 GB laptop:

- A Dhaka office backend with its own SQLite database, immutable source directory, signing key, model configuration, and durable ingestion jobs.
- A Frankfurt backend running the same office code with separate storage, credentials, and key.
- A gateway that routes structured questions and approved claims. It cannot read either source directory.

Use Python 3.11, FastAPI, Pydantic, SQLite with SQL migrations and FTS5, PyMuPDF, httpx, hashlib, cryptography Ed25519, pytest, and Docker Compose. Use the built-in `sqlite3` interface unless a concrete blocker requires an additional database library. Pin compatible dependencies in a reproducible lockfile. Start one office worker per service process; do not configure multiple API worker processes against that worker loop.

Do not add Neo4j, Redis, a vector database, an agent framework, Kubernetes, React, OCR, live Slack authorization, currency conversion, confidential computing, or ZK circuits. Unknown wording and unsupported formats must produce explicit review/failure states.

Use explicit target facts for the demo queries. General natural-language question interpretation and generated answer phrasing are optional; supported numeric answers must be computed by the engine and may use deterministic templates. Actual model-based extraction through the configurable adapter is required for the live path.

Suggested boundaries, which can be ordinary Python modules rather than frameworks:

| Module | Responsibility |
|---|---|
| `contracts` | Strict typed inputs, claims, findings, query responses, signed payloads, exports |
| `storage` | Migrations, transactional persistence, source paths, job state, revisions |
| `ingestion` | PDF clauses, Slack normalization, deduplication, job processing |
| `extraction` | Provider interface, live/cache/replay adapters, schema/evidence validation |
| `rules` | Scope/value intersections, compatibility, finding classification |
| `temporal` | Snapshot selection, explicit supersession, closure events |
| `integrity` | Canonical serialization, hashes, Merkle proofs, signatures, bundle verification |
| `queries` | Authorized retrieval, deterministic answers, citations, lineage |
| `security` | Server-side demo principals, scope checks, source and derivative permissions |
| `federation` | Typed exchange, signature verification, egress instrumentation |
| `office_api`, `gateway_api` | HTTP handlers calling the modules above |
| `scripts`, `tests`, `fixtures` | Commands, independent checks, synthetic inputs and labels |

## 3. Contracts to freeze before application features

Create Pydantic models with unknown fields forbidden. Generate JSON schemas and API examples from those models rather than maintaining conflicting handwritten schema copies. Distinguish extraction proposals from accepted backend records.

| Contract | Required contents |
|---|---|
| Source manifest | Tenant/office, source/version identity, authority, policy family, effective interval, applicability, explicit replaced clauses/scope, sensitivity, office/model export permissions |
| Extraction proposal | Subject, supported scope/rule, exact evidence span, unsupported/ambiguous cases; no trusted authority, permissions, IDs, or receipt timestamps |
| Claim revision | Backend identity, trusted metadata, normalized rule/scope, effective interval, actual system receipt time, evidence, extraction provenance, immutable signed content |
| Revision closure | Signed append-only event referencing a revision and its system end time |
| Finding | Claim revisions, classification, exact affected scope/time, explanation code, severity, evidence, separate review-event history |
| Query | Question, typed target, `valid_at`, optional `known_at`, mode; authenticated office/tenant supplied by server context |
| Answer | Status, exact answer text, factual-statement citations, governing facts, warnings, times, modes, signed lineage |
| Verification | Separate file, clause, manifest, claim, and answer checks; each `passed`, `failed`, or `not_checked` with a reason |
| Federation export | Approved enum/numeric scope and rules, effective dates, opaque references, commitments, origin and signature; no free-text evidence |
| Egress event | Request/channel/destination, serialized payload bytes/hash, result, real timestamp; no credentials or raw prompts |

Document any implementation-level choice left open by the proposal. Routine choices should be made and recorded without expanding product scope. If a real contradiction between documents is discovered, record the specific conflict rather than silently dropping a requirement.

### Numerical and temporal rules

- USD amounts use integer cents: USD 25,000 is `2500000`. Reject zero/negative loan amounts and unsupported currencies.
- Amount intervals preserve endpoint inclusion. Use integer successor/predecessor arithmetic or an equivalent correct discrete-range implementation. Test included singleton intersections and empty intervals.
- Approval values are positive integers. Retention uses normalized decimal strings and matching year units/start events. Do not convert years to days.
- Supported rule kinds: `required_minimum`, `maximum_allowed`, `exactly_required`, `advised_sufficient`, `operating_exact`.
- Compare requirements as allowed value sets. Compare advice/planned operating values against applicable requirements. A different minimum alone is not a contradiction.
- Effective and system intervals are half-open. Null end means infinity. Capture `known_at` once per query; reject invalid date intervals and unsupported future knowledge cutoffs.
- `system_to` is derived from signed closure events and excluded from the original signed claim content. New effective-history revisions receive new IDs/signatures. Never mutate signed claim content to retire a rule.
- Source publication time, policy effective time, and actual ingestion time are different fields. Only tests use controlled clocks; live audit times are real.

## 4. Fixture story and expected outcomes

Create actual text-based PDFs with reproducibly identifiable sections and a saved Slack event. Keep source wording and the trusted manifests aligned. Full wording and scope are in proposal section 3.

| Source | Asserted behavior |
|---|---|
| Dhaka lending v2, effective Jan 1, 2026 | USD business loans through 50,000 require at least one approval; above that require at least two |
| Dhaka lending v3, effective Feb 1, 2026 | Through 25,000 require at least one; above that require at least two; manifest explicitly replaces the v2 approval scope |
| Slack, published March 3, 2026 | For the same loans through 50k, one approval is sufficient and no second sign-off is needed |
| Dhaka retention procedure | Delete the shared cross-office loan records after exactly five years from loan closure |
| Frankfurt retention policy | Retain those same records for at least seven years from loan closure |

Use `valid_at=2026-03-03T12:00:00Z` in the scripted current-policy story. For historical checks use a January valid date or actual ingestion checkpoints for `known_at`. Do not copy example ingestion dates from the proposal into runtime records.

| Check | Expected result |
|---|---|
| USD 25,000 under v3 | One approval; Slack advice is adequate at this amount |
| USD 25,000.01 under v3 | Two approvals; Slack advice is insufficient |
| USD 50,000 under v3 | Two approvals; Slack advice is insufficient |
| USD 50,000.01 under v3 | Two approvals; Slack advice does not cover this amount |
| v3 versus v2 | Explicit supersession, no active contradiction alert |
| Active v3 versus Slack | One `stale_guidance` finding with affected band `(25000, 50000]` USD |
| Minimum one versus minimum two | Compatible requirements |
| Minimum five years versus minimum seven | Compatible requirements |
| Operating exactly five versus required minimum seven | Procedure-level `compliance_gap` |
| Minimum seven versus maximum five, same applicability | `contradiction` |
| Different record scope or retention starting event | Not comparable or review, never an automatic contradiction |
| USD 30,000 question | Two approvals, with policy citation and warning about stale Slack guidance |
| Unsupported currency, missing condition, ambiguous authority | Reject/review/abstain as appropriate; no fabricated answer |

Do not hardcode these final outputs in seed or demo handlers. Replay fixtures supply proposed extractions only; persistence, validators, comparisons, retrieval, and signatures run normally. Unit checks must include cases outside the demo wording.

## 5. Implementation stages and gates

### Stage 1 — Contracts, fixtures, and pure rule functions

Deliver package setup, strict contracts, synthetic source-generation inputs, normalized extraction fixtures, and reusable comparison functions. Implement applicability/time overlap, discrete amount intervals, value-set compatibility, and classification. Start a small labeled development corpus and a scenario-separated held-out set before tuning extraction.

**Gate:** offline checks cover the entire table above, included endpoints, singleton/empty intervals, negation/number normalization, and incompatible scopes. Pure engine tests may use constructed claims; they do not count as end-to-end evaluation.

### Stage 2 — Durable ingestion and one-office replay

Deliver migrations, immutable original storage, PDF clause parsing, Slack normalization, durable jobs, restart recovery, and transactional claim/finding publication. Persist normalized source identity separately from content hashes. Enforce server-derived tenant/office and upload permissions now, not as an afterthought.

Use replay extraction proposals through the real validator initially. Resolve exact quotes in preserved parser text; reject fabricated spans, unsupported conditions, and model attempts to set authority. One source version can yield multiple claims. Repeated event delivery is idempotent; changed bytes under the same immutable version ID are rejected.

**Gate:** actual PDF and Slack inputs through ingestion APIs produce the expected finding; a repeated event does not duplicate it; distinct sources with identical text remain distinct; worker restart completes or safely retries unfinished jobs. Unsupported PDFs fail visibly. Unauthorized upload or object access is denied.

### Stage 3 — Temporal history, queries, and signed evidence

Deliver scoped explicit supersession, historical snapshots, signed closure events, FTS5 plus structured retrieval, deterministic answers/citations, graph-shaped lineage, review events, file hashes, clause Merkle proofs, and pinned-key signature verification.

Use the proposal's exact canonical serialization and RFC 9162 tree convention. Sign source manifests, claim revisions, finding snapshots, closure events, and answers. Bind answers to their exact text/hash, query/target, citations, and time scope. Verify all supplied bundle components against their claimed hashes/signatures; do not return a single green status after checking only the root signature.

**Gate:** January/March snapshots differ correctly; a query before the actual v3 ingestion checkpoint cannot use it; later replacement does not invalidate historical signatures. Verify original and changed copies without modifying originals. Altered bytes, leaves, claims, manifests, and answers fail their respective checks. One-leaf and odd-size trees verify. Restricted evidence stays inaccessible through lineage and findings.

### Stage 4 — Real model adapter and visible modes

Deliver live OpenRouter extraction with strict schema requests, bounded retries/timeouts, provider configuration, evidence validation, versioned cache keys, and explicit live/cached/replay modes per stage. Treat source text as untrusted data. The model has no tools and cannot grant authority or permissions.

Runtime credentials come from environment configuration. Missing credentials return a clear prerequisite/error; do not fabricate a successful live test. A paid live smoke test runs only when credentials and the explicit live-test option are supplied. Routine tests must not make paid requests.

**Gate:** a fake HTTP transport exercises success, malformed JSON, hallucinated quotes, schema violations, timeout, provider failure, cache miss, and no-silent-fallback behavior. When configured, separately run one genuinely uncached Slack extraction and record the actual model/route, latency, and usage. Cache/replay must not make hidden model calls.

### Stage 5 — Two offices and federation

Run the same office code with separate databases, source volumes, credentials, keys, and model settings. Add gateway routing and the typed federation contract. The source office authorizes exports; the gateway validates them again. Verify remote signatures against pinned office keys before comparison. Service identities are not allowed to download raw source content.

Only approved enum/numeric claims and opaque provenance references cross office boundaries. Preserve derivative permissions and separate office export permission from hosted-model permission. Log actual serialized bytes at the transport path for both office and model channels. No arbitrary model prose or source titles are allowed in strict claim exports.

**Gate:** the five-year procedure versus seven-year policy produces a gap for the shared record scope. Restricted claims are blocked. Canary source text is absent from office payloads, gateway logs, and errors. Unavailable office or bad signature yields partial/abstained behavior. Remote clause inclusion is `not_checked` when the recipient has not received the clause text. Display hosted-model traffic separately from office transfer counters.

### Stage 6 — Packaging, evaluation, and live rehearsal

Deliver Compose, readiness checks, local commands, README, API examples, locked dependencies, synthetic cache, offline replay, evaluation exports, and a backup-installation procedure. Expose all routes and commands in proposal section 11; do not omit endpoints merely because a demo script can call internal functions instead.

Create about 40 labeled comparisons in complete source scenarios, with a held-out split that does not share the same policy family/scenario as tuning data. Report end-to-end TP/FP/FN, precision/recall, classification/scope errors, extraction failures, review/abstention, times by mode, model usage, and actual resource observations. A missing extraction is an end-to-end miss. Do not invent customer interviews or time saved; those require human evidence.

**Gate:** proposal section 12.3 passes offline wherever applicable; explicitly configured live checks have their actual results recorded. `make demo-replay` completes on a clean reset with outbound model calls disabled. `make demo-live` includes a new uncached extraction when credentials/network are available. Prepare and rehearse on primary and backup laptops; report any checks requiring human access that have not actually been performed.

## 6. Boundaries that must survive every stage

- Authenticate every protected API and scope object access by server-derived tenant/office/role. User-provided object IDs, office names, and model output are not authorization.
- Keep general source access separate from federation. The gateway must not proxy raw source downloads or mount office source directories.
- No unannounced fallback from live inference to fixtures. Mode, cache miss, incomplete ingestion, and regional outages are visible in output.
- Do not equate a valid signature with source truth, correct extraction, or local model residency. Office-local inference is a configurable production design, not demonstrated by hosted calls.
- A dismissed alert does not delete evidence or change an effective policy. Review actions append audit events.
- Source files are immutable. Reset is a local command limited to the configured demo tenant/directory, with explicit unattended flag. Preserve keys, fixtures, and exported evidence.
- Keep secrets and runtime data out of Git and screenshots. Test transport/error paths for content leakage rather than relying on a manually maintained zero-byte counter.
- Make unsupported behavior visible. Do not silently simplify “at least” into “exactly,” drop exceptions, infer a new policy's authority, or erase old history to make a test pass.

## 7. Definition of delivery

The final repository contains working application code, migrations, locked dependencies, `.env.example`, generated schemas/OpenAPI examples, fixtures and labels, tests, Compose, README, and the setup/seed/reset/demo/evaluation commands listed in the proposal. No required behavior is a TODO, placeholder success response, or hardcoded demo finding.

The final implementation report must list:

1. Stages completed and the three demonstrated stories.
2. Exact verification commands and actual outcomes.
3. Any skipped live calls or laptop rehearsals and the missing prerequisite.
4. Implemented, replay-backed, unvalidated, and deferred capabilities separately.
5. Remaining failures or acceptance checks not met, without calling the whole backend complete if required work remains.

Human buyer interviews, organizer logistics, venue connectivity, and confirmation of NRB participation remain team tasks. Document their status; do not synthesize evidence of participation or demand.

## 8. Prompt to start the coding model

```text
Implement the backend in this repository using backend_implementation_brief.md.
Read the linked revised proposal for the full behavior and acceptance contract.
Start by inspecting the repository and applicable local instructions.
Implement stages in order and run each stage's checks before advancing.
Continue through all stages without stopping after a plan or scaffolding.
Keep IMPLEMENTATION_STATUS.md current with actual results and prerequisites.
Preserve the fixed stack, backend-only scope, and all eight correctness fixes.
Do not fabricate successful tests, live model calls, benchmark results, or demo evidence.
Use live credentials only through configuration; routine checks must run offline.
Finish with working code, reproducible commands, and an honest acceptance report.
```

Model reference: [DeepSeek's official October 17 release announcement](https://api-docs.deepseek.com/news/news261017/). This brief does not depend on an unverified benchmark score or provider-specific context-window assumption.
