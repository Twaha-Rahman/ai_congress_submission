# General policy PDF + Slack demo

The office backend now supports domain-independent policy statements alongside
the existing numeric loan-approval and retention checks. Use
`subject: "general_policy"` for travel, leave, procurement, security or other topics.
General findings are **model-assisted candidates requiring human review**, with
source quotations and signed snapshots. They are not proof of a contradiction or
exhaustive coverage of every policy.

## What is implemented

1. The normal PDF and saved-Slack ingestion APIs accept a general-policy manifest.
2. The model extracts verbatim statements, actors, actions, constraints, textual
   applicability, conditions and exceptions. Trusted authority, permissions and
   replacement links continue to come only from the uploader's manifest.
3. The backend checks quotations and extracted excerpts against preserved parser
   text. Invented text and scope changes are rejected or held for review.
4. For each accepted new statement, local lexical retrieval ranks relevant current
   general statements. Policy-family equality is not required: team chat can be
   checked against several policy families. Statements within the same PDF can
   also be compared.
5. A separate model call compares the two primary statements with their full source
   context, including other clauses that may contain exceptions. The backend checks
   both returned quotations, currentness, explicit categorical scope boundaries,
   effective intervals and trusted policy replacements before publishing.
6. Conflicts use review severity, include `assessment: "model_assisted"`, and do not
   become deterministic high-severity alerts. The Findings workspace displays their
   general scope and statement text, marks them as provisional, and counts review
   severity items as needing attention.

Different minimums are not automatically contradictory. For example, passwords of
at least 12 and at least 16 characters can both be required. Guidance explicitly
allowing a prohibited action or a missed deadline can conflict with policy.

## Configure the model

Set `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` in your private `.env`, or the
corresponding `DHAKA_`/`FRANKFURT_` overrides. Use the exact model ID offered by your
provider. Restart the office services after changes. No credentials belong in a
manifest, browser bundle or shared URL.

The demo configuration restricts providers to DeepSeek and Cloudflare with
`only=deepseek,cloudflare,order=deepseek,cloudflare,require_parameters=true`, and sets
`LLM_REASONING_EFFORT=none`. Both extraction and comparison receive the explicit
reasoning setting. Use `low` if your rehearsal needs some reasoning; leave empty to
use the provider/model default. Changing reasoning also changes cache identity.
These performance settings need evaluation with your actual documents; a faster
extraction does not establish conflict-detection accuracy.

Select `mode=live` on ingestion to process your own new documents. `cached` and
`replay` stay explicit and never fall back to paid model calls. General extraction
uses prompt version `general-extract-v1`; semantic comparison uses
`general-compare-v1`. General comparison cache/replay records are separate from
extraction records, under the office's `comparisons/` subdirectory.

Every source included in a hosted comparison must allow hosted processing. A
shareable Slack message cannot grant permission to send a restricted PDF. Full
source context is included, so permission applies to that context too. An explicitly
approved local endpoint can process sources that prohibit hosted egress. General
policy text stays local to its office: it cannot enter the existing numeric-only
cross-office federation or numeric Q&A APIs.

## Upload a policy

Use a text-based PDF. Scanned/image-only PDFs still need OCR support. Complicated
layouts should be rehearsed with the actual document and model.

### Browser workflow

Start the office services and frontend as described in the [README](../README.md).
Configure the selected office's uploader credential on the frontend server in your
private `.env`; reader mode cannot upload. Open **Sources → Upload PDF** and select
a text-based PDF up to 20 MiB. Enter its name, version, category, authority,
publication date and applicability, plus an effective date when known. Dates use UTC.
For a hosted model, explicitly allow sending the source text to it. These browser
uploads use `subject: "general_policy"`, `mode: "live"` and `office_export: false`.

Submit with the button or `Ctrl+Enter` / `⌘+Enter`. Recent uploads displays the real
job and incomplete-coverage reasons, with auto-refresh enabled after submission.
You can inspect the original, open its findings and retry comparisons when accepted
statements exist. A request error preserves the draft and selected file; the browser
never automatically resends a POST. Check recent uploads before retrying an uncertain
submission. Failed extraction requires an upload again.

Choose **Version relationship → Replaces …** only for a whole-version replacement.
The UI retrieves the trusted scope and existing clause IDs and requires a new
version label and a later effective start. For a partial replacement or numeric
subject, use the API workflow below.

### API workflow

Create `travel-policy.manifest.json`:

```json
{
  "schema_version": "1",
  "tenant_id": "meridian_demo",
  "region": "DHAKA",
  "source_identity": "travel_policy",
  "version_label": "v1",
  "source_type": "pdf",
  "subject": "general_policy",
  "authority": "policy",
  "policy_family": "travel",
  "scope": {
    "kind": "policy",
    "description": "All employees covered by the travel policy",
    "attributes": {}
  },
  "effective_from": "2026-10-01T00:00:00Z",
  "effective_to": null,
  "publication_time": "2026-09-20T00:00:00Z",
  "sensitivity": "demo_shareable",
  "permissions": {"office_export": false, "hosted_model": true}
}
```

Use `attributes` for explicit, categorical boundaries such as `{"country":"BD"}`.
Use consistent keys and values; these are exact categories, not natural-language
equivalence. Keep textual conditions/exceptions in the source. Unknown applicability
should be left unspecified for the semantic stage to assess. Missing policy
effective dates prevent a confident conflict classification.

With the uploader token already loaded privately into your shell environment:

```sh
curl --fail-with-body http://127.0.0.1:8081/v1/ingestions/pdf \
  -H "Authorization: Bearer $DEMO_TOKEN_DHAKA_UPLOADER" \
  -F 'file=@travel-policy.pdf' \
  -F 'manifest=<travel-policy.manifest.json' \
  -F 'mode=live'
```

The API returns HTTP 202 and a job ID. Poll `/v1/jobs/{job_id}` with an authorized
local reader token. General ingestion can finish `needs_review` even when some
claims were accepted; inspect its review reasons and `/v1/claims/reviews`. Empty
Findings alone never establishes that all content was assessed or is consistent.

## Submit a saved Slack message

`POST /v1/ingestions/slack` accepts the following JSON. A future live Slack listener
must normalize workspace events into this format and supply trusted metadata.
For the simplest demo, submit one source version per message.

```json
{
  "mode": "live",
  "manifest": {
    "tenant_id": "meridian_demo",
    "region": "DHAKA",
    "source_identity": "demo_channel_message_001",
    "version_label": "original",
    "source_type": "slack",
    "subject": "general_policy",
    "authority": "informal",
    "policy_family": "team_chat",
    "scope": {"kind":"policy", "description":"Travel guidance for employees", "attributes":{}},
    "effective_from": null,
    "effective_to": null,
    "publication_time": "2026-10-20T09:00:00Z",
    "sensitivity": "demo_shareable",
    "permissions": {"office_export":false, "hosted_model":true}
  },
  "channel": {"id":"CDEMO", "name":"demo-policy-chat"},
  "event": {
    "event_id":"demo-message-001",
    "ts":"2026-10-20T09:00:00Z",
    "user":"demo-member",
    "text":"Employees may submit travel expenses within 60 days."
  }
}
```

The manifest publication time must match the newest supplied message. When no
effective-from date is explicitly supplied, each general Slack statement uses its
own message timestamp. Source text can still make applicability uncertain. Thread
context is not fetched automatically: “the same exception as before” should require
review. The live Slack connector remains separate integration work. Saved Slack
sources appear in the Sources library after API ingestion.

## Limits, failure recovery and policy versions

Defaults are six candidates per statement and 24 distinct pairs per ingestion.
Configure `POLICY_COMPARISON_TOP_K` and `POLICY_COMPARISON_MAX_PAIRS`, optionally with
an office prefix. These bound model cost; retrieval is lexical and can miss distant
paraphrases. Pruned candidates/pairs, extraction truncation and exhausted budgets
produce review reasons rather than silent complete-coverage claims. The comparison
stage shares one `LLM_JOB_MODEL_BUDGET_SECONDS` budget, in addition to extraction's
budget. Processing is asynchronous and Findings auto-refresh introduces polling
delay.

Comparison context is capped at 60,000 characters per pair, including both complete
sources. Larger sources are held for review rather than silently losing possible
exceptions. Extraction currently considers at most the first 200 clauses and flags
incomplete general-policy coverage when that limit is reached.

Transport failures, missing cached/replay output, mismatched quotations and unknown
scope/time/exception coverage become review items. To retry comparisons after fixing
the model configuration, without changing the original source:

```sh
curl --fail-with-body -X POST \
  'http://127.0.0.1:8081/v1/sources/SOURCE_ID/comparisons?mode=live' \
  -H "Authorization: Bearer $DEMO_TOKEN_DHAKA_UPLOADER"
```

This queues a durable comparison job, reuses accepted current statements, and
preserves earlier snapshots/reviews. It does not retry failed extraction. Re-uploading
an unchanged source remains idempotent. Changed bytes or trusted metadata require a
new version label. A new comparison that changes a conclusion marks earlier pair
assessments historical. Retry with larger candidate limits when coverage was pruned.

Policy replacement still requires an explicit `supersedes` manifest declaration,
including existing clause IDs, the same trusted scope, and an effective date. A Slack
message cannot establish replacement. Replaced revisions retain evidence/history;
old semantic assessments become historical. Staleness is not inferred from age alone.

## Rehearse and evaluate

Run the controlled offline corpus without paid calls:

```sh
.venv/bin/python scripts/evaluate_general_policy.py
```

It covers 12 development cases across travel, leave, procurement and security,
including compatible minimums, exceptions, missing context, scope/time separation
and an instruction-injection message. **Offline mode uses fixture responses derived
from labels. It verifies plumbing and is not a model accuracy measurement.**

Evaluate your actual hosted model explicitly, starting with one case:

```sh
.venv/bin/python scripts/evaluate_general_policy.py \
  --mode live --allow-paid-live --only travel_deadline
```

Omit `--only` to evaluate all cases. Live mode normally makes two extraction calls
and up to one comparison call per case, plus configured retries. Reports include
errors, review reasons, usage, conflict precision and recall. This is a small
development corpus, not a held-out benchmark. Both modes create isolated temporary
databases and keys; they do not reset the normal demo. Results go to
`evidence/general_policy_evaluation.json` by default.

Before the onsite demo, test the actual policy PDF, an aligned message, a clear
conflict and an exception with the chosen model. Keep `make demo-*` and reset
commands away from your loaded demo data.
