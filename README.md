# Meridian — verifiable institutional memory

Meridian has a backend for two bank offices (Dhaka and Frankfurt) plus a
metadata-only gateway. It ingests PDFs and saved Slack events, extracts typed policy
claims with evidence, keeps effective-time and knowledge-time history, detects
stale/contradictory/incomplete guidance, answers scoped questions deterministically,
and produces signed evidence bundles that an independent verifier can check.

The repository also contains the synthetic demo corpus, replay proposals, evaluation
labels, command-line demos and an offline test suite. The frontend includes a
Claude-inspired findings workspace with persisted reviews and a Sources workspace
for PDF uploads, processing status and original-document inspection, plus a Verification
workspace for source-copy checks, signed answer bundles and evidence lineage. Questions
supports natural-language questions across accessible PDF and saved Slack sources, with citations and optional source/date filters. Cross-office shows both offices’ cited answers together and offers signed numeric-rule checks through the gateway.

For your own policy subjects, use `subject: "general_policy"`. This path retrieves
relevant statements, checks source quotations, and publishes model-assisted conflict
candidates for human review. See the [general policy demo guide](docs/general_policy_demo.md)
for manifests, PDF/Slack API examples, comparison retries, limits and model evaluation.
The existing numeric checks remain available. General source Q&A is office-local;
automated cross-office text conflict judgments are not implemented. The browser can
present independently authorized office answers side by side. A read-only live Slack
connector supports selected public channels through Socket Mode;
[setup and supported behavior](docs/slack_integration.md) are documented separately.

## Browser workspace

Requires Node **22.13+** (or a newer supported Node release), in addition to the
backend prerequisites below. Run from the repository root:

```bash
make setup                    # only needed on a new checkout
make local-up                 # starts existing office databases without resetting them
make frontend-install         # npm ci with the committed lockfile
make frontend                 # http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173/findings**. If there are no findings yet, use
`make demo-replay` to prepare the synthetic demo (this resets demo databases). Do
not run that command during an investigation you want to preserve.

The workspace includes office selection, search and filters, exact evidence quotes,
inline PDF/Slack source inspection, source downloads, effective/knowledge chronology, and acknowledge/resolve/dismiss
decisions with required reasons and durable history. Finding selection and filters
are stored in the URL. `DESIGN.md` is the installed Claude design reference;
[FRONTEND_GUIDELINES.md](FRONTEND_GUIDELINES.md) records the Meridian adaptations
and a review checklist for this first slice.

Search by text, full finding ID, or the displayed tag (for example `#2B6375FB`).
The queue's Sort control supports severity, newest, oldest, review status and ID;
sorting preserves the finding already being viewed. Clicking a tag copies it to the
clipboard and confirms success; it does not change search. The address bar includes
the selected tag and full finding ID, filters, sort, tab, mobile pane, auto-refresh,
and any open source's location and zoom. Share that URL to restore the same view
against the same office data, subject to the recipient's access. Tag-only links
also work, for example `/findings?office=dhaka&tag=2B6375FB`.

The **Auto-refresh** toggle reloads data every 10 seconds, preserves selection, and
pauses in hidden tabs, while editing, and while a dialog/source is open.
**View original** opens a local PDF renderer at the cited page with matching lines
highlighted, or the saved Slack source at its quoted message. PDF pages, zoom, and
the source view are also restored from shared URLs. Downloads remain available.

On desktop, click **Shortcuts**, or press `?` / `F1`,
for the keyboard guide and the option to disable single-key shortcuts. `/` focuses
search, `J` / `K` move through findings, and `A` / `R` / `D` open review forms.
`U` opens PDF upload when permitted.
`Ctrl+Enter` / `⌘+Enter` submits the open review or upload form after validation.
`Shift+R` toggles auto-refresh; `Shift+T` opens theme options. Auto-refresh has an
explicit on/off switch indicator on desktop and mobile. Key hints and the shortcuts
button are hidden in the mobile layout.

On Questions, `B` opens **Recent answers** and `Shift+N` reuses the selected question
in the composer without submitting. Refresh failures keep the loaded answer list in
place. Date fields open the shared calendar/time picker from the whole field;
keyboard editing and `Alt+Down` remain available. Choose a date/time, then **Apply**;
**Cancel** leaves the field unchanged. Datetime fields include UTC time choices and
an exact-time input. Share dialogs place an icon-only copy action beside
the link, with stable confirmation inside the button.

Use the sidebar's **Theme** control for **Light**, **Dark**, or **System** appearance.
Office, theme and role sit below navigation; on mobile they share a compact header.
System is the default and follows device changes; your choice is saved locally.
Copy confirmation animates inside the finding tag without moving the page. Dialogs
close with an outside click, the close button, or Escape, and preserve the page's
width while background scrolling is locked.

The frontend server reads the root `.env` and keeps bearer tokens on the server.
It runs as the configured demo reviewer by default. To inspect read-only access:

```bash
UI_ROLE=reader make frontend
```

The principal is fixed on the server; there is no browser role selector. This is a
loopback-only demo operator workspace, not a multi-user login system. Real user
authentication is required before exposing it on an office network. The server
forwards only the endpoints needed by findings, sources, local questions, verification and gateway comparison queries/receipts. Direct federation, raw gateway source access, model APIs and service credentials are not exposed to browser code.

### Cross-office comparisons

Open **Cross-office** in the sidebar (`/comparisons`). **Source answers** sends the
same natural-language question and UTC cutoffs independently to Dhaka and Frankfurt,
with an optional source selection per office. Answers appear independently with
status, limitations, exact citations, original-source inspection and verification.
This requires access to both offices and uses their configured models; it does not
send source passages through the federation gateway or infer a combined verdict.

**Signed-rule check** uses the existing strict gateway protocol for numeric loan
approval or record retention rules. Record retention specifies originating and
processing offices, loan records, `MTF_CROSS_OFFICE` and loan closure. Both workflows
show incomplete/unavailable evidence explicitly. Export counts and byte totals
belong to the structured exchange, not hosted-model traffic. Passage inclusion is
not checked when originals are withheld from the gateway.

The server-side reviewer workspace needs `DEMO_TOKEN_GATEWAY_SERVICE` for signed-rule
checks; `UI_ROLE=reader` cannot borrow that service identity. The browser supplies
neither credentials nor snapshot/import controls. Gateway comparisons import approved
signed claims only when explicitly submitted. Successful gateway receipts persist
under `GATEWAY_RUNTIME_DIR/comparison_receipts/<tenant>/`; shared links read those
receipts without submitting another comparison. Clearing gateway runtime removes
those links. General links reference the separately saved office answers; recipients
still need access to each answer’s complete source scope.

`N` opens the comparison form, `Ctrl/⌘+Enter` submits it, and `Shift+E` / `Shift+S`
open exports / sharing. Stopping a request stops browser waiting; server work may
finish. Check each office’s recent answers before submitting again after an uncertain
failure. No polling or automatic POST retries are used.

For a built version, run `make frontend-build`, then `npm start --prefix frontend`.
The built server also listens on loopback port 5173; stop the dev server first.
`UI_PORT` changes the built server port, and `DHAKA_BASE_URL` / `FRANKFURT_BASE_URL`
change office connections. `GATEWAY_BASE_URL` changes the gateway connection. Restart the frontend server after changing these values.
Fonts and PDF.js resources are bundled locally, so the built UI makes no CDN/model
requests. `predev`/`prebuild` copy PDF resources from the locked package into the
ignored `frontend/public/pdfjs/` directory; no additional download is needed onsite.

```bash
npm test --prefix frontend     # bridge security, presentation, URL state, source location
make test                     # backend suite, including durable review history
```

### Ask questions

Open **http://127.0.0.1:5173/questions** and ask a plain-language question about
any topic covered by the office's sources: for example, “Who reviews open orders,
and how often?” or “How do employees request leave?” **Sources** searches all
accessible originals by default, or a single selected version. There are no loan or
retention fields to fill in. Source passages are retrieved before the configured
OpenRouter/OpenAI-compatible model writes a cited answer. The same path can use an
operator-approved local model in production.

**Policy date** and **Knowledge cutoff** are always visible and open the UTC date
and time picker in one click. They default to **Now** and **Latest**; apply a custom
date or use its reset icon to return to the default. Reuse a saved question with **Use this question**;
its exact original timestamp precision is retained until the displayed time changes.

Answers contain clickable statement references, exact source quotations and page/
section locators. **Inspect source** opens the original at its passage. Unsupported
questions abstain, conflicting evidence can require review, and retrieval/processing
limits remain explicit. Retrieval is bounded to 64 passages and 48,000 source
characters per question; larger contexts disclose incomplete coverage. This is
model-assisted interpretation, not a correctness
certificate. Citation matching tolerates only PDF whitespace wrapping; saved quotes
and offsets always refer to the exact preserved original. The server discards a
proposed answer if its quotations or passage IDs cannot be grounded.

**Recent answers** searches the latest 50 authorized answers by question, date,
status or ID, with list-only highlighting. Opening an answer does not rerun it.
**Verify answer** opens signed-bundle checks: general answers bind directly to
signed source commitments and passage proofs, without inventing extracted claims.
Verification proves integrity and bindings, not whether a model's interpretation
is correct. Old typed numeric answers remain readable and verifiable.

Share view preserves the saved answer, office, list search, active panel, mobile
pane and source location. Draft questions and source filters stay out of shared
URLs. Export downloads the saved response; signed bundles are in Verification.
On mobile, Back restores list scroll and focus. `N` focuses the composer, `/` searches
recent answers, `J`/`K` move through matches, `V` opens verification, and
`Ctrl+Enter`/`⌘+Enter` submits. `Shift+E`/`Shift+S` export/share; shortcut preferences
and typing guards apply.

General questions require `LLM_MODEL`/`LLM_API_KEY` on the office backend and can incur
model charges. Sources that forbid hosted processing are excluded before retrieval
unless the endpoint is explicitly approved and local; normal reader authorization
also applies before ranking or sending text. Saved answers remain limited to readers
who can access their full source context, including context that was not cited.
Calls, failures and usage are audited.
No model secrets enter browser code. General Q&A has no cached/replay fallback;
explicit cached/replay requests are rejected. Typed numeric API questions retain
their deterministic behavior. Restart office services and the frontend after upgrading.

### Verify evidence and inspect lineage

Open **http://127.0.0.1:5173/verification**, use **Trace evidence** (`V`) from a
finding, or **Verify source** from source inspection. Use **Check integrity** to run
checks and **Trace evidence** to follow evidence connections. Switching tabs retains
your selected file and results for the same evidence. Choose an evidence type:

- **Source copy:** select an authorized source, choose its PDF or saved Slack JSON
  copy, then run verification. The original and your copy appear together; opening
  Verification never chooses a source for you. File bytes, normalized text, passage
  text and the commitment tree are checked independently. A metadata-only PDF edit can fail
  file identity while its text checks pass. The immutable original is never changed.
- **Finding:** follow the finding's statements, passages and source versions;
  inspect exact passages and open the source at its location. Source-copy and
  answer-bundle checks do not verify finding snapshot signatures.
- **Saved answer:** search recent authorized answers by question or creation date.
  Manual ID entry is available under Open by answer ID. Inspect its answer and
  authorized lineage, export its signed bundle, and check that bundle.
  Create a new local answer in Questions, then open it here for verification.
- **Uploaded bundle:** choose an exported JSON bundle (a bare bundle or a
  `{ "bundle": ... }` response). Inspect supplied connections and check its
  signatures, evidence bindings and disclosed passage proofs against pinned keys.
  Changed answer text fails its text hash and signature. Undisclosed passages remain
  **Not checked**; they are never presented as verified because another check passed.

Readers can run verification using their existing read access. Verification does not
require uploader privileges or make model calls. The UI sends copies only to the
selected local office backend. Files are limited to 20 MiB. Neither uploaded copies,
imported bundles nor verification reports are published as sources or stored in URL
state; use the header **Export** menu to keep a report, trace, or saved answer bundle.
**Share view** explains what the link includes before copying it.

The trace starts with the selected record’s supporting evidence; **Show related
evidence** expands the wider authorized graph. Browse conclusions, statements,
passages and sources one group at a time, with more records loaded on request.
Statements use literal excerpts and citations as labels, and source versions are grouped
under their document. Sources counts documents separately from their versions. Search
highlights literal matches in the evidence list; inspector text stays unchanged.
Selecting a record shows its connections and exact passage beside
the list on desktop. On mobile it opens a detail view; **Back to evidence** restores
your scroll and focus. Connections represent stored
provenance, not an integrity result. Uploaded-bundle connections are explicitly
labelled as supplied data. Server-authorized traces omit inaccessible nodes and
dangling edges; a bounded trace warns when it reaches the node limit.

`/` focuses lineage search; `Escape` leaves it without clearing the query. `J`/`K`
move through matching records, `I` opens Check integrity, `L` opens Trace evidence,
and `V` opens Check integrity and runs a ready verification form. `Ctrl+Enter` / `⌘+Enter` also submits that form.
`Shift+E` opens Export and `Shift+S` opens Share view. Share view preserves office,
task, trace scope/group, mobile pane, evidence type/ID, selected node, search, result
filter and source page/zoom/passage.
Saved-answer search is retained in the link. Local files and check results must be
supplied or rerun after reload. Browser history restores the evidence view, with explicit unavailable states for missing IDs. Evidence,
lineage, and bundle requests fail independently: a trace failure does not prevent a
source-copy check, and a bundle failure does not hide a saved answer’s trace.

### View activity and compare source versions

Open **Activity** to search office transfer records, processing snapshots, source
publication/withdrawal and review decisions. Filter by type, outcome or UTC date,
inspect a record, or export/share the current view. Audit access is required.
Completed uploads update to Acknowledged or Reviewed as their findings are reviewed;
processing warnings remain visible separately.

In **Sources**, choose **Compare versions** on a source row or in its inspector.
Compare preserved text and metadata, swap the base/compared versions, search changes,
and inspect either original. Both versions must be accessible and belong to the
same source. See [the workflow and API guide](docs/activity_versions.md).

### Connect live Slack channels

Open **Sources → Live Slack** in an authorized workspace to monitor public channels,
set their applicability and processing permissions, pause/resume model work and
inspect recent processing. Slack app credentials are configured per office on the
server. Edits and deletions withdraw prior evidence from current answers while
preserving audit history. See [the setup guide](docs/slack_integration.md) for app
installation, restart instructions, permissions and coverage limits.

### Import saved Slack messages

Open **Sources → Import Slack JSON** and choose a saved message event or batch.
The dialog previews the channel, message count and dates. Enter the source name,
version, policy category and applicability, choose its readers, and allow hosted
processing when using a hosted model. Imports use informal authority and derive
publication time from the saved messages. Live Slack credentials are not required.

Files can contain up to **200 messages**, **100,000 text characters** and **5 MiB**
from one channel. Thread replies must include their parent in the batch. Use
**Download example** in the dialog for the supported JSON structure; full workspace
ZIP exports and edit/delete notifications are not supported. Processing appears in
**Recent activity**, and importing another source preserves the job already selected.

### Upload your own PDF

Open **Sources → Upload PDF**. Choose a text-based PDF up to **20 MiB**, then enter
its policy name, version, category, publication date and applicability. Add the
effective date when known. Additional settings cover restricted access, an end date
and categorical scope labels. These uploads use the general-policy path in **live**
mode; the configured model must be available. Scans need OCR before upload.

For the hosted demo, explicitly allow model processing in the form. Consent starts
unchecked. Originals remain in the selected office; uploads disable cross-office
export. For a local model, use an approved private/loopback endpoint with
`LLM_LOCAL_ENDPOINT_APPROVED=1` (or the office-prefixed setting) on both the office
and frontend server, then restart both.

The frontend needs `DEMO_TOKEN_DHAKA_UPLOADER` and/or
`DEMO_TOKEN_FRANKFURT_UPLOADER` in the private root `.env`, in addition to its reviewer
token. These credentials stay on the Node server. Reader mode cannot upload even
when an uploader credential is configured. Restart the office services and frontend
when updating from an older checkout, so source details and job summaries match.

After submission, recent uploads shows the actual queued, processing, processed,
needs-review or failed state. Auto-refresh turns on with confirmation and checks
every three seconds while work is active. Inspect the reasons for incomplete or
failed processing; an empty Findings queue does not establish consistency. You can
inspect accepted sources, open their findings, or explicitly retry a comparison.
Failed extraction requires another upload. Failed requests keep the form and file;
uncertain submissions are never automatically resent.

Selecting an upload opens a status drawer without moving the activity list. It
shows the current processing stage, per-stage durations, comparison-pair counts,
queue time and total elapsed time. Updates continue while the drawer is open.
Uploading another PDF keeps the currently selected upload open. New jobs record
stage timings; older jobs clearly indicate when those measurements are unavailable.
Retries retain earlier attempt history and report timings for the latest attempt.

For a complete policy replacement, choose the earlier version in **Version
relationship**. The form keeps its name, category and scope and sends an explicit
replacement declaration using its clause IDs. Supply a different version label and
an effective date later than the earlier version's start. Partial replacements use
the ingestion API. Merely uploading a higher version does not replace an old one.

Sources search, type, sort, selected job and an open document's page/zoom are stored
in the URL, so authorized teammates can restore the same view against the same
backend. Unsent files, form text and consent stay out of shared URLs.

The review-history addition preserves the existing finding response and adds a
top-level `reviews` array. Review submissions can supply `expected_snapshot_id`;
the API returns a conflict if the finding changed before the decision was recorded.

## What is implemented

- **Trusted ingestion:** uploader-supplied manifests carry authority, permissions,
  sensitivity and supersession. Model output can never set those fields.
- **Evidence-grounded extraction:** strict JSON schema; exact quotes are resolved in
  preserved parser text; hallucinated quotes, unsupported conditions, unsupported
  negation, scope escapes and number mismatches are rejected or sent to review.
  Hosted extraction requests ask for exact quotations and page/section hints only.
  Character offsets are computed from preserved source text; legacy model-provided
  offsets are ignored without relaxing quote or location validation.
- **Durable office state:** SQLite with append-only migrations, transactional
  publication, immutable originals, durable jobs and restart recovery.
- **Temporal history:** separate effective (`valid_from`/`valid_to`) and system
  (`system_from`/closure) axes; explicit manifest supersession closes old knowledge
  with signed append-only events and carries corrected history as new revisions.
- **Deterministic comparison:** requirement allowed-set intersections, amount-band
  boundaries, advice-vs-requirement classification, procedure-level compliance gaps.
- **Signed evidence:** canonical JSON, RFC 9162 Merkle commitments, Ed25519
  signatures, pinned public-key verification, per-component bundle verification.
- **Explicit model modes:** `live`, `cached`, `replay` per stage. Missing credentials,
  cache misses and missing replay data fail visibly; there is no silent fallback.
- **Federation:** signed structured-claim exports, source-office egress policy,
  recipient verification, isolated remote-claim storage, opaque remote citations and
  `not_checked` clause inclusion.
- **Authorization:** bearer identities scoped by tenant/office; restricted evidence is
  excluded before query computation, lineage and federation.
- **Audit:** egress events record structured bytes, hashes, outcomes and model
  metadata separately for office-to-office and hosted-model channels.

## Repository layout

```
meridian/              application packages (contracts, rules, storage, ingestion,
                       extraction, temporal, queries, federation, office/gateway APIs)
frontend/              React/TypeScript findings workspace and local API bridge
scripts/               setup, stack supervisor, seed/reset, demos, evaluation
fixtures/              demo + evaluation sources, manifests, replay and cache material
config/principals.json static identity/permission map (tokens come from env)
docs/openapi/          generated office and gateway OpenAPI documents
tests/                 offline pytest suite
evidence/              generated demo/evaluation JSON (git-ignored)
runtime/               SQLite databases, source bytes, keys, logs (git-ignored)
```

## Prerequisites

- Python **3.11** (`python3.11`)
- `make`
- Docker with Compose v2 (only for the packaged stack; local processes work without it)
- For genuinely live extraction: an OpenRouter API key plus a model ID, set only in
  `.env` or the environment.

No local model server is required for replay/cached demos or tests.

## Quick start (local processes)

```bash
make setup          # .venv, locked deps, Ed25519 keys, trusted pins, demo tokens, .env
make test           # offline suite; no network or model calls
make demo-replay    # reset, seed, run all three stories, leave services running
make local-down     # stop the three local services
```

`make setup` is idempotent: it never overwrites existing keys, tokens or configured
model values. `.env` is git-ignored and written with permissions `0600`.

## Runtime configuration

All credentials and model routing live in `.env` / environment variables; nothing is
hardcoded. Important variables:

| Variable | Purpose |
|---|---|
| `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | shared hosted-model route |
| `DHAKA_LLM_*`, `FRANKFURT_LLM_*` | per-office overrides |
| `LLM_TEMPERATURE`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_ATTEMPTS` | live-call behavior; request timeout defaults to 600 seconds |
| `LLM_JOB_MODEL_BUDGET_SECONDS` | total model budget per extraction/comparison stage attempt, including request retries; defaults to 600 seconds |
| `LLM_REASONING_EFFORT` | optional reasoning override for extraction and comparison; empty (the default) uses model defaults |
| `LLM_RESPONSE_FORMAT` | `json_schema` (default) for provider-enforced structured output, or `json_object` with the schema supplied in the prompt and enforced by the backend; office overrides supported |
| `DHAKA_LLM_PROVIDER_PREFS`, `FRANKFURT_LLM_PROVIDER_PREFS` | provider allowlist, preference order and supported-parameter requirements |
| `DHAKA_DB_PATH`, `FRANKFURT_DB_PATH` | office SQLite paths |
| `TRUSTED_KEYS_PATH` | pinned public-key registry |
| `DEMO_TOKEN_*` | bearer tokens for the static principal map |
| `DEMO_EXTRACTION_MODE` | default `replay`, `cached` or `live` |

Provider preferences support comma-separated options and comma- or pipe-separated
lists. For example, `only=deepseek,cloudflare,order=deepseek,cloudflare,require_parameters=true`
restricts all routing to those two providers and tries DeepSeek first. `order` by
itself is a preference, not an allowlist. The demo configuration uses this allowlist
and leaves `LLM_REASONING_EFFORT` empty, omitting the reasoning parameter for both
model stages. Both extraction and comparison use a 600-second request timeout and
a separate 600-second total budget per stage attempt. Automatic job retries can
make total processing take longer. Explicit reasoning overrides produce separate
cache keys. Office-prefixed reasoning settings override the shared value.
The live demo uses `LLM_RESPONSE_FORMAT=json_object` so DeepSeek can serve requests;
its endpoint does not currently advertise strict structured-output support.
The full response schema and evidence checks are still enforced by the backend.
Output modes have separate cache identities; failures never silently switch modes.
Restart the offices after changing model settings.

See `.env.example` for the full template. Do not commit `.env`, `runtime/` or
`evidence/`.

## The three demonstrations

All commands below run offline except `demo-live`.

### 1. Catch stale guidance

```bash
make demo-replay
# or, after a reset/seed:
.venv/bin/python scripts/demo1_catch.py --mode replay
```

The baseline corpus contains lending policy v2 (one approval up to USD 50k) and v3
(two approvals above USD 25k, explicitly superseding v2). A saved Slack message says
one approval is enough “up to 50k”. Ingesting it publishes a high-severity
`stale_guidance` finding over **`(USD 25,000.00, USD 50,000.00]`**, with a signed link
to the superseded requirement. The January knowledge snapshot still answers with the
old policy; March answers with v3 and warns about the guidance. Evidence:
`evidence/demo1_finding.json`.

### 2. Trace, verify and tamper

```bash
.venv/bin/python scripts/demo2_trace.py
```

The script asks a question, follows answer → claims → clauses → source manifests,
fetches the signed bundle, verifies every component, then tampers with the answer
text and shows the specific checks that fail. It also compares the original source
bytes, a metadata-only change and a modified-text copy. Evidence:
`evidence/demo2_bundle.json`, `evidence/demo2_tamper_report.json`.

### 3. Cross-border comparison

```bash
.venv/bin/python scripts/demo3_border.py
```

Dhaka's procedure retains records for exactly five years; Frankfurt's policy requires
at least seven for the same cross-office record scope. The gateway retrieves signed
structured exports, the processing office imports them and runs the local comparator,
producing a procedure-level `compliance_gap` (5 < 7) with an opaque remote citation
and `clause_inclusion = not_checked`. A restricted-only export is blocked with
`egress_denied_restricted_source`, and audit counters show zero raw source text bytes
between offices. Evidence: `evidence/demo3_federation.json`.

### All three in one command

```bash
make demo-replay    # fresh demo DBs, replay proposals, all stories
make demo-cached    # same stories from the explicitly labelled synthetic cache
make demo-live      # requires credentials; new Slack extraction is uncached
```

`make demo-live` exits with status 2 and a prerequisite message when `LLM_MODEL` and
`LLM_API_KEY` are not configured. It does not fall back to replay.

## Evaluation

```bash
make evaluate
# optional subsets:
.venv/bin/python scripts/evaluate.py --only holdout_collateral
```

The corpus has 10 complete scenarios, 38 sources and 41 labeled comparisons split into
development and held-out policy families. The runner starts an isolated stack on ports
8090–8092 with fresh databases, asserts every replay quote against parsed text, measures
end-to-end precision/recall, classification and scope accuracy, persistence, review
outcomes and mode behavior, then writes `evidence/evaluation_results.json`. The latest
run is recorded in `IMPLEMENTATION_STATUS.md`.

## API overview

Every office exposes:

```
GET  /health, /ready
POST /v1/ingestions/pdf              multipart file + manifest + mode
POST /v1/ingestions/slack            saved event(s) + manifest + mode
GET  /v1/jobs, /v1/jobs/{id}
GET  /v1/sources, /v1/sources/{id}, /v1/sources/{id}/content
GET  /v1/claims, /v1/claims/reviews
GET  /v1/sources/{id}/lineage, /v1/findings/{id}/lineage
GET  /v1/findings, /v1/findings/{id}
POST /v1/findings/{id}/reviews
POST /v1/queries
GET  /v1/answers?limit=50 (1–100; filters access before limiting)
GET  /v1/answers/{id}, /v1/answers/{id}/lineage, /v1/answers/{id}/bundle
POST /v1/verifications/source, /v1/verifications/bundle
POST /v1/comparisons                 federation comparator (service auth)
POST /v1/federation/claims           signed export (service auth)
POST /v1/federation/imports          verify + import (service auth)
GET  /v1/federation/remote-claims
GET  /v1/audit/egress
```

The gateway exposes `/health`, `/ready`, `POST /v1/queries` and
`GET /v1/audit/egress`. Generated OpenAPI documents are in `docs/openapi/`; regenerate
with `make schemas`.

Example (after `make demo-replay`):

```bash
set -a; . ./.env; set +a

curl -s http://127.0.0.1:8081/health | python3 -m json.tool

curl -s -X POST http://127.0.0.1:8081/v1/queries \
  -H "Authorization: Bearer $DEMO_TOKEN_DHAKA_READER" \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "How many approvals are required for a USD 30,000 business loan originated in Dhaka?",
    "target": {
      "subject": "loan_approval",
      "amount_minor": 3000000,
      "currency": "USD",
      "loan_type": "business",
      "origin_office": "DHAKA"
    },
    "valid_at": "2026-03-03T12:00:00Z"
  }' | python3 -m json.tool
```

Use the uploader token and `-F mode=replay` for a manual PDF ingestion; use the
reviewer token for review actions and restricted evidence. Tokens are read from
`.env` and are never stored in the identity map.

## Tests

```bash
make test
# 65 passed in ~0.6s (offline)
```

The suite covers strict contracts, number normalization, amount singletons and empty
intervals, allowed-set comparisons, supersession/known-at history, evidence-validator
rejections, Merkle proofs at every tree size, Ed25519 pinning, bundle tampering,
authorization/restricted exclusion, federation export/import/conflict/blocked paths,
live/cached/replay mode behavior, fake-transport provider success/timeout/500/schema
failures, and full replay ingest → finding → answer → verification.

## Docker Compose

```bash
make up             # setup + build image + start dhaka, frankfurt, gateway
make seed           # same corpus through the HTTP APIs
make local-status   # health/pid view (local pids are absent for a Compose stack)
make down
```

The gateway container has no office database, source volume, private key or fixture
mount. Each office mounts only its own runtime/key directories and its office-specific
replay/cache assets; public-key pins and configuration are read-only. Raw source
documents are uploaded by the host-side seeding tools and are not baked into the image.
Runtime databases/keys live under `./runtime` on the host. Office ports bind to
`127.0.0.1` only. This remains a same-machine simulation, not geographic isolation.

## Reset, backup and installation

```bash
make reset-demo     # refuses while healthy services hold the databases
```

Reset deletes only the configured demo tenant’s SQLite/source runtime directories and
staged files; it preserves keys, fixtures and exported evidence. To move or reinstall:

1. Install Python 3.11/make/Docker on the target.
2. Copy the repository (without `.venv`, `runtime`, `evidence`, `.env`).
3. Run `make setup`; then copy the original `runtime/keys/` and
   `runtime/trusted_keys.json` if previously exported bundles must still verify.
4. Run `make test`, `make demo-replay` or `make up`.

Changing signing keys is a new trust domain: old bundles will correctly fail
verification unless the old public keys remain pinned.

## Trust boundaries and design decisions

- Money is integer minor units (USD cents); retention years are normalized decimal
  strings; canonical signed JSON forbids floats.
- Signatures live outside signed payloads. Verification uses pinned public keys, never
  a key supplied by the response being checked.
- A valid signature proves integrity and origin, not source truth or extraction
  correctness; a reviewer still owns those judgments.
- Restricted evidence is filtered before comparison, so its values cannot influence an
  answer even indirectly.
- Federation exports carry allowlisted enums/numbers/opaque references only. Remote
  clause text is never fabricated, so local clause inclusion stays `not_checked`.
- Replay/cache data is synthetic and explicitly labelled. Hosted-model calls are never
  made from replay/cached modes.

## Known limitations / external prerequisites

- **Live PDF extraction has been exercised on synthetic fixtures**, including paid
  comparison calls; see [the measured verification report](docs/pdf_api_verification.md).
  Those results do not establish exhaustive coverage of arbitrary policies or a
  successful live Slack-connector rehearsal. A new model or route needs fresh testing.
- The identity map and bearer tokens are a demo mechanism, not production SSO/OIDC.
- Storage is single-node SQLite (WAL) per office; it is not a horizontally scaled
  deployment. The worker is one per service process by design.
- The parser supports text-based PDFs and saved Slack events; scanned PDFs/OCR and
  arbitrary chat exports are out of scope.
- Numeric answers and gateway comparisons support loan approval and record retention
  with their scoped semantics; unsupported numeric currencies/conditions are rejected
  or reviewed. Office-local general-policy findings use model-assisted comparison
  and require human interpretation. General source Q&A is model-assisted, bounded to
  retrieved authorized passages, and can abstain or be incomplete. Cross-office text
  conflict detection remains unimplemented; Cross-office presents the independent answers for human review.
- Buyer interviews, NRB participation, venue logistics and backup-laptop rehearsals are
  team tasks and are not claimed here.
