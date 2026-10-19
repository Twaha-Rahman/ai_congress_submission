# Verifiable Institutional Memory: Revised Hackathon Proposal

A backend that detects stale operational guidance after policy changes, identifies compliance gaps, and provides signed evidence linking each finding and answer to its sources.

This document is the implementation handoff. It incorporates the proposal review and the onsite demo constraints: five team members with 16 GB laptops, cheap hosted inference through OpenRouter, and office-local inference as the intended production deployment. The original proposal remains unchanged.

## 1. Judging Criteria (as provided by the hackathon)

Total: 100 points.

| # | Criterion | Weight | Score range |
|---|---|---|---|
| 1 | Innovation | 20% | 0-20 |
| 2 | Technical Execution | 20% | 0-20 |
| 3 | Business Model (+ Global Readiness) | 20% | 0-20 |
| 4 | Real-World Impact (+ Ethical AI Compliance) | 20% | 0-20 |
| 5 | Scalability (+ NRB Collaboration) | 10% | 0-10 |
| 6 | Presentation | 10% | 0-10 |

### 1.1 Innovation (20%)

**What judges look at:** Originality, creativity, and non-obvious AI application. Judges evaluate whether the idea is meaningfully differentiated, applies AI in a transformative way, and demonstrates bold or systems-level thinking rather than incremental improvements.

**Score bands**
- 0-5: Incremental improvement or common idea.
- 6-10: Moderately differentiated concept with limited novelty.
- 11-15: Strong originality and creative AI integration.
- 16-20: Breakthrough or globally competitive innovation.

### 1.2 Technical Execution (20%)

**What judges look at:** Architecture quality, AI integration depth, system robustness. Judges assess the clarity and robustness of the technical architecture, including input → processing → output workflow, model selection logic, integration of AI technologies (LLMs, ML, RAG, multimodal systems), code or workflow reliability, and explainability of the intelligence core.

**Score bands**
- 0-5: Basic prototype with limited AI implementation.
- 6-10: Functional architecture with moderate technical depth.
- 11-15: Well-structured AI-native system design.
- 16-20: Production-grade engineering maturity suitable for real-world deployment.

### 1.3 Business Model + Global Readiness (20%)

**What judges look at:** Monetization logic, adoption pathway, cross-border applicability. Judges evaluate the clarity of the value proposition, monetization or sustainability pathway, user adoption strategy, cross-border market viability, and evidence of market validation or demand.

**Score bands**
- 0-5: Concept without sustainability or business model.
- 6-10: Basic business logic with limited validation.
- 11-15: Viable market pathway with defined users.
- 16-20: Scalable, globally adaptable economic model with strong potential.

### 1.4 Real-World Impact + Ethical AI Compliance (20%)

**What judges look at:** Problem relevance, measurable benefit, responsible AI safeguards. Judges consider the significance of the problem, measurable outcomes or KPIs, societal or economic relevance, responsible data usage, bias mitigation strategies, and overall transparency in AI design.

**Score bands**
- 0-5: Weak or unclear impact case.
- 6-10: Clear localized benefit with limited scale.
- 11-15: Strong national relevance with measurable outcomes.
- 16-20: High social return with documented ethical safeguards.

### 1.5 Scalability + NRB Collaboration (10%)

**What judges look at:** Deployment feasibility, modular design, global builder integration. Judges evaluate whether the system can scale technically and operationally, including cloud readiness, modular architecture, infrastructure feasibility, inclusion of NRB or global collaboration, and alignment with international standards.

**Score bands**
- 0-3: Demo-only system without scalability considerations.
- 4-7: Early scaling strategy with limited infrastructure planning.
- 8-10: Clear deployment pathway and strong global collaboration readiness.

### 1.6 Presentation (10%)

**What judges look at:** Clarity, structure, confidence, and AI reasoning explanation. Judges assess the clarity of storytelling, effectiveness of the demonstration, ability to explain AI decisions, and overall professionalism and confidence of the team.

**Score bands**
- 0-3: Unclear or poorly structured communication.
- 4-7: Clear presentation with moderate structure.
- 8-10: Compelling, data-driven, and investor-ready presentation.


---

## 2. Product, differentiation, and boundaries

**Pitch:** “When a policy changes, we find the guidance that still tells employees to follow the old rule—and show exactly why it is unsafe to follow.”

The fictional customer is **Meridian Trade Finance**, with Dhaka and Frankfurt offices. All documents, people, policies, and obligations in the demonstration are synthetic. They do not represent actual law or regulatory advice.

The product combines temporal policy records, a narrow deterministic rule engine, source lineage, integrity verification, and controlled exchange of structured claims between office nodes. Temporal graphs alone are not the innovation: systems such as [Graphiti](https://github.com/getzep/graphiti) already support temporal history and fact invalidation. Our differentiation is the application to policy applicability, actionable stale-guidance detection, and verifiable evidence across office boundaries.

### 2.1 Binding implementation scope

Build **backend only**. Deliver APIs, OpenAPI documentation, terminal demo scripts, synthetic fixtures, automated checks, and machine-readable evidence. Return graph-shaped lineage JSON for a future UI. Do not build React, a custom dashboard, or a frontend development server.

| Capability | Required MVP behavior |
|---|---|
| Ingestion | Text-based synthetic PDFs and saved Slack JSON through the same normalized pipeline |
| Extraction | Hosted OpenRouter model, strict schema, supporting evidence spans, validation, visible failure states |
| Temporal records | Effective dates, knowledge history, explicit scoped supersession |
| Rule engine | USD loan-approval thresholds and record-retention constraints only |
| Findings | Distinguish contradictions, stale guidance, compliance gaps, compatible differences, and unresolved cases |
| Query | Structured lookup, lexical retrieval, graph neighbors, citations, supported answers or abstention |
| Integrity | Original-file hashes, clause Merkle proofs, signed ingestion manifests and answer records |
| Federation | Two logically isolated office nodes; allowlisted claim exchange with measured audit events |
| Review | Reviewer-only acknowledge/resolve/dismiss actions recorded as events |
| Demo reliability | Live, cached, and offline replay modes; reset/seed; prepared backup laptop |

**Defer:** live Slack integration, OCR/scanned PDFs, arbitrary legal language, automatic currency conversion, vector search, generic entity extraction, a new graph database, production identity infrastructure, Helm/Kubernetes, confidential computing, and ZK proofs. Unsupported cases enter review or abstention; they do not produce guessed rules.

This is a demonstrable prototype, not a claim of production-grade compliance or tested geographic data residency. Preserve the core story before extending scope.

### 2.2 Fixed stack

| Layer | MVP choice |
|---|---|
| Language/API | Python 3.11, FastAPI, Pydantic |
| Storage | Separate SQLite database and source directory per office; SQL migrations |
| Graph representation | Explicit node and edge tables in SQLite; no separate graph server |
| Retrieval | Typed subject/scope lookup plus SQLite FTS5 and graph-neighbor traversal |
| Jobs | SQLite job table, one asynchronous worker per office, durable state and retries |
| PDF parsing | PyMuPDF; clause/page locators with preserved source spans |
| Model client | Small HTTP adapter using httpx; per-office configurable endpoint/model/credentials |
| Crypto | hashlib and cryptography Ed25519; no custom signature algorithms |
| Packaging | Docker Compose: Dhaka node, Frankfurt node, gateway; no UI container |
| Validation | pytest and JSON evidence exports |

Pin actual package versions in a lockfile after compatibility checks. Do not migrate databases or add infrastructure during the hackathon unless a demonstrated requirement cannot be met by this stack.

## 3. Synthetic dataset and live stories

### 3.1 Shared fixture conventions

Use one tenant, `meridian_demo`, with separate office identities `DHAKA` and `FRANKFURT`. Every source has a manifest identifying its policy family, applicable scope, dates, authority, sensitivity, and export permissions. These are supplied by an authorized uploader, not inferred from document instructions.

All dates are UTC. The scripted policy questions explicitly use `valid_at=2026-03-03T12:00:00Z` so the story remains stable regardless of the presentation date. `known_at` defaults to the actual request time. Never backdate real ingestion audit events to match the fictional story. Controlled clocks are permitted in tests and must be identified as test fixtures.

### 3.2 Demo 1: The Catch — stale guidance after an explicit replacement

**Dhaka lending policy v2**, effective January 1, 2026:

- Business loans denominated in USD, with `0 < amount <= 50000`, require at least one approval.
- The same loans with `amount > 50000` require at least two approvals.

**Dhaka lending policy v3**, effective February 1, 2026:

- The same business loans with `0 < amount <= 25000` require at least one approval.
- The same loans with `amount > 25000` require at least two approvals.
- Its trusted manifest explicitly replaces the v2 approval clauses for this entire loan scope from February 1. No other policy family or scope is replaced.

**Slack replay event**, published March 3, 2026:

> “For our USD business loans up to 50k, one approval is sufficient. You do not need a second sign-off.”

Ingest the policies before presenting. During the demonstration, ingest this new Slack event through the API with the model cache bypassed. Poll the job and show its extraction, evidence, and finding.

**Expected result:** `stale_guidance` for `25000 < amount <= 50000`. One approval is an insufficient advised action in that band. The v2/v3 change is an explicit supersession, not a separate active contradiction. Replaying the identical event produces no duplicate finding.

Do not hardcode a finding count or elapsed time into the demo. Display the measured result and execution mode.

### 3.3 Demo 2: The Trace — answer, history, and tamper detection

Ask: “As of March 3, how many approvals does a USD 30,000 business loan need?”

**Expected answer:** “At least two approvals under lending policy v3. The March 3 Slack message says one is sufficient; following it would violate the current requirement.” Cite both the authoritative clause and the stale message. Explain why v3 governs; do not treat informal guidance as equal authority.

Display answer → claim → clause/message → document version as JSON nodes and edges with page/section locators, evidence spans, and verification results.

Verify an original PDF against its ingestion manifest. Then submit a modified copy, without overwriting the stored original. The modified copy must fail the original-file hash check. Also demonstrate that editing the answer or the signed manifest invalidates its signature. A metadata-only PDF edit can fail file verification while leaving clause-text verification successful; report those results separately.

For historical behavior, ask the same loan question with `valid_at` in January: v2 requires at least one approval. Demonstrate `known_at` using actual ingestion checkpoints: an answer requested as of the checkpoint before v3 was uploaded cannot use v3, even when its effective date is earlier.

### 3.4 Demo 3: The Border — a compliance gap on shared records

Use the same record class and applicability on both sides: `loan_records`, originating in Dhaka, processed by Frankfurt for the fictional cross-office product `MTF_CROSS_OFFICE`.

- Dhaka procedure: “Delete these records after exactly five years from loan closure.” Extract as a planned operating retention duration of five years.
- Frankfurt policy: “These records must be retained for at least seven years from loan closure.” Extract as a required minimum of seven years.

The actual deletion of records has not been observed. The result is a **procedure-level compliance gap**, not a claim that actual records were deleted early. Two policies specifying minimums of five and seven years would be compatible, and must be a negative test.

A Frankfurt user asks whether the Dhaka procedure meets the Frankfurt requirement. Dhaka returns approved typed claims and signed provenance references. Frankfurt compares them locally and returns `compliance_gap`, explaining `planned_retention_years=5 < required_minimum_years=7` for the same record scope and retention starting event.

Display separate counters for office-to-office transfers and hosted-model calls. Show a restricted-source exchange being denied. Remote source text is not returned to Frankfurt; its citation is an opaque reference with a verification status, not an invitation to bypass the source office's access controls.

## 4. Rule schema and extraction contract

### 4.1 Supported semantics

Different numbers alone do not establish a conflict. Preserve the meaning of the statement.

| Rule kind | Meaning | Example |
|---|---|---|
| `required_minimum` | A compliant action must be at least this value | At least two approvals |
| `maximum_allowed` | A compliant action cannot exceed this value | Retain for no more than five years |
| `exactly_required` | A compliant action must equal this value | Exactly two approvals |
| `advised_sufficient` | Guidance says this value is enough | One approval is sufficient |
| `operating_exact` | A procedure prescribes this actual/planned operating value | Delete records after exactly five years |

The first three describe requirement sets. Two requirements contradict only if their allowed values have no intersection for the same applicability and time. `advised_sufficient` and `operating_exact` describe an advised or planned action; compare that action with the applicable requirement. They are not automatically equal-authority requirements.

Approvals are positive integers. Retention values are nonnegative numeric years from a named starting event. Support comparisons only for matching units and starting events. Currency is USD only; do not infer conversions or equate years with a fixed number of days. Missing or ambiguous units require review.

### 4.2 Example accepted claim

```json
{
  "schema_version": "1",
  "claim_id": "generated_by_backend",
  "tenant_id": "meridian_demo",
  "region": "DHAKA",
  "subject": "loan_approval",
  "scope": {
    "loan_type": "business",
    "currency": "USD",
    "origin_office": "DHAKA",
    "amount_minor": {
      "lower": 2500000,
      "lower_inclusive": false,
      "upper": null,
      "upper_inclusive": false
    }
  },
  "rule": {"kind": "required_minimum", "value": 2, "unit": "approvals"},
  "authority": "policy",
  "policy_family": "dhaka_business_loan_approvals",
  "source_version_id": "lending_v3",
  "source_clause_id": "lending_v3:4.2",
  "valid_from": "2026-02-01T00:00:00Z",
  "valid_to": null,
  "system_from": "2026-10-19T12:00:00Z",
  "system_to": null,
  "evidence": {
    "page": 1,
    "section": "4.2",
    "quote": "USD business loans above $25,000 require at least two approvals.",
    "start_char": 0,
    "end_char": 64
  },
  "validation_status": "accepted"
}
```

This is illustrative: offsets and the real ingestion timestamp must be computed by the backend, not copied from this example. Offsets are zero-based Unicode character positions with an exclusive end in the preserved parser clause text. Store money as integer cents, not floating-point dollars. Use decimal-safe handling for retention values. Use strict schemas with unknown fields forbidden at trust boundaries.

### 4.3 Trusted manifest

The authorized uploader supplies `tenant_id`, source identity, source version, policy family, authority (`policy`, `procedure`, `informal`), effective dates, applicability, superseded clause IDs/scopes, sensitivity, and egress permissions. Slack publication time is source metadata; `system_from` is the backend receipt time.

For Slack, use message publication as the asserted guidance's `valid_from` for this MVP, and disclose that modeling assumption. Missing policy effective dates require review. Unknown or contradictory applicability requires review. Authority and permissions cannot be elevated by the model.

### 4.4 Evidence-grounded validation

The model returns a list of proposed rules, source spans, and explicit unsupported/ambiguous cases. It cannot assign trusted IDs, timestamps, authority, permissions, or supersession relationships.

Validation must:

1. Check schema and locate the exact evidence quote in parser output, with page and clause context.
2. Normalize supported number forms: `50k`, `50,000`, and `50000`; `one`, `two`, and digit forms. Preserve the original evidence.
3. Check the normalized value, comparison operator, unit, negation, and modality against supported source patterns. `at least`, `no more than`, `exactly`, and `sufficient` are not interchangeable.
4. Preserve conditions and exceptions. If a claim depends on an unsupported “unless” clause or unresolved cross-reference, return `needs_review` rather than dropping the condition.
5. Reject unsupported model fields and hallucinated evidence. Retry malformed outputs within a bounded budget, then record failure or review status.

Schema-valid JSON and a matching number are necessary checks, not proof of semantic correctness. A temperature setting does not make extraction deterministic. Model self-reported confidence is not sufficient for acceptance.

## 5. Ingestion, persistence, and temporal history

### 5.1 Source pipeline

Accept text-based PDFs and Slack replay JSON. Hash original bytes before parsing. Retain immutable originals in each office's private source directory. Split PDFs by clauses with headings and adjacent conditions preserved. Report encrypted, scanned, corrupt, or unsupported PDFs explicitly; do not silently ingest empty text.

Normalized events include source ID, source version/event ID, source type, source publication time, tenant, region, and trusted manifest reference. Source edits produce a new version linked to the previous one.

Idempotency is scoped to `(tenant, region, source identity, version/event identity, content hash)`. Identical text from different sources keeps separate provenance. Identical replay deliveries produce one logical source version. Changed content with the same immutable version identifier is rejected and requires a new version identifier.

Jobs use `queued → running → succeeded | needs_review | failed`, with attempt count, error code, real timestamps, and per-stage execution mode. Persist jobs before acknowledging ingestion. On restart, safely reclaim unfinished work. Commit each source version's accepted claims, lineage, and derived findings transactionally to avoid duplicate or half-published results.

### 5.2 Two time axes

Each claim revision has:

- `valid_from`, `valid_to`: when its asserted rule applies.
- `system_from`, `system_to`: when this revision was the system's knowledge of that assertion.

Use half-open time intervals `[from, to)`; null end means unbounded. A snapshot includes revisions where `valid_from <= valid_at < valid_to` and `system_from <= known_at < system_to`, treating null ends as infinity.

On learning an explicit replacement, close the prior knowledge revision's system interval once and insert replacement revisions representing the newly known effective history. Preserve the old revision's valid interval for earlier `known_at` queries. Do not overwrite historical rule content or retroactively rewrite what the system knew. Keep original source assertions independently of derived effective intervals.

Implement closure as an append-only signed event referencing the immutable revision. Derive `system_to` from that event; it may be cached in an index but is not a mutable field inside the originally signed claim payload. New effective-interval revisions get new IDs and signatures. This prevents legitimate history updates from invalidating earlier evidence signatures. Sign and bind snapshots of derived findings to the claim revisions they actually used.

Example: v3 is effective February 1 but uploaded at checkpoint T2. A snapshot at `valid_at=February 5, known_at=T1<T2` uses the previously known v2 rule; the same valid date with `known_at>=T2` uses v3. The first answer describes system knowledge, not a claim that v2 was actually authoritative on February 5.

### 5.3 Explicit, scoped replacement

Only authorized manifest relationships establish supersession. Require matching policy family, applicable scope, explicit replaced clause IDs, and replacement date. Newer publication dates, larger version strings, embeddings, or shared subjects do not establish replacement.

Fully support the explicit whole-approval-scope replacement used by the fixtures. If a proposed partial replacement cannot be represented safely by the supported scope model, quarantine it for review rather than retiring an entire policy. Re-run affected findings when scope or effective history changes; preserve earlier finding snapshots.

Graph nodes include document, version, clause, message, claim revision, answer, and office. Edges include `IN_VERSION`, `EXTRACTED_FROM`, `SUPERSEDES`, `CITES`, and typed finding links. All tables and lookups carry tenant and region boundaries.

## 6. Deterministic findings and query behavior

### 6.1 Candidate selection

Select by canonical subject, tenant, applicable product/record/loan scope, and overlapping valid intervals at the requested knowledge snapshot. Use controlled subject aliases such as `sign-off → approval`. Match currency, record class, origin/processing offices, and retention starting event before numerical comparison.

Different jurisdictions alone neither prove conflict nor disqualify a comparison. The manifests must establish that both rules or procedures apply to the same target activity. A broad candidate set can be filtered deterministically; embeddings are not needed for the MVP.

### 6.2 Comparison and classification

Represent requirement constraints as allowed value sets. For approvals, intersect over integer counts; for retention, compare decimal year durations. Check monetary scope overlap in integer cents with explicit endpoint inclusion. Do not use a strict `<` endpoint test that misses an included singleton intersection.

| Situation | Result | Alert? |
|---|---|---|
| Minimum one approval and minimum two approvals | `compatible_difference`; two satisfies both | No |
| Required minimum two, advised sufficient one | `stale_guidance` when older replaced policy explains it; otherwise `incorrect_guidance` | Yes |
| Required minimum seven years, procedure exactly five years | `compliance_gap` | Yes |
| Required minimum seven years, maximum allowed five years, same scope and starting event | `contradiction` | Yes |
| Explicit replacement of v2 by v3 | `supersession` | No |
| Different activities, non-overlapping dates, or non-overlapping amounts | `not_comparable` | No |
| Missing condition, unknown applicability, unsupported replacement | `needs_review` | Review queue |

Staleness requires an evidence-backed link to the older guidance or replaced rule, not simply an older message date. In Demo 1, the Slack advice matches the superseded v2 threshold and fails the v3 constraint.

A finding includes claim revision IDs, classification, severity, explanation code, affected scope with exact bounds, overlapping time interval, authority basis, evidence references, and review state. Deduplicate on an ordered pair of claim revisions and finding type. Keep alert state separate from immutable evidence; review decisions are appended as events.

Use `high` severity for supported contradictions, incorrect/stale guidance, and procedure-level gaps; `review` for unresolved cases; and `info` for compatible changes. These are demo triage labels, not estimates of legal or financial risk. All alerts remain recommendations for a reviewer.

### 6.3 Queries and citations

The query request contains a question, originating office, `valid_at`, optional `known_at`, and optional typed target facts such as amount/currency/product. Natural-language interpretation may propose target facts, but ambiguous or unsupported interpretations require clarification or abstention. A fixed demo command supplies explicit target facts while still showing the human-readable question.

Apply authorization first. Retrieve current applicable claims, then related findings, superseded versions for explanation, and local evidence spans. Use FTS5 for exact terms and clause references. For supported numeric questions, compute the governing result deterministically and optionally let the model phrase it. The answer must preserve that result, authority, and warnings.

Return `answered`, `needs_review`, `abstained`, or `partial`; include citations per factual statement, time parameters, modes, model metadata where applicable, and integrity statuses. Missing applicable policy, failed extraction, absent evidence, incomplete regional response, or unsupported semantics must not produce an invented answer.

Verify that citation IDs belong to the authorized retrieved set and their evidence supports the attached statement. Numeric conclusions must match the deterministic engine. Unsupported generated prose is removed or flagged. This is a reliability check, not a mathematical proof that every interpretation is correct.

## 7. Integrity and evidence verification

### 7.1 Separate file identity from passage identity

Store `source_sha256 = SHA256(original_file_bytes)` to check byte-for-byte identity. Separately commit to parsed clauses for passage inclusion. Pin the parser version, record its configuration, and preserve parser output; do not pretend a canonical-text hash detects all PDF changes.

For the MVP, canonicalize commitment payloads with a versioned deterministic JSON encoding: UTF-8, sorted keys, compact separators, no floating-point values, no NaN, no implicit Unicode/whitespace normalization. Monetary values are integers and decimal values use a single documented normalized string representation. All writers and verifiers use the same encoding. Signatures live outside the signed payload.

Order clause leaves by `(page, start_char, clause_id)`. Each leaf payload includes tenant, office, source/version IDs, clause locator, exact text, and source-file hash. Use domain-separated hashing:

```text
leaf_hash = SHA256(0x00 || canonical_leaf_payload)
node_hash = SHA256(0x01 || left_child_hash || right_child_hash)
```

Use the recursive largest-power-of-two split described in [RFC 9162, section 2.1](https://www.rfc-editor.org/rfc/rfc9162.html#section-2.1), rather than inventing an odd-leaf convention. Inclusion proofs contain tree size, leaf index, sibling hashes, and the signed root reference. Reject malformed proofs. Cover one-leaf, odd-size, and altered-leaf cases.

### 7.2 Signed manifests and answers

At ingestion, sign a canonical manifest containing the original-file hash, Merkle root and tree size, source identity, trusted metadata and its permissions, parser/schema versions, real ingestion timestamp, and signer key ID. Persist it before exposing accepted sources. Sign validated extracted claim payloads linked to that manifest, including their evidence locators and extraction provenance. These attest to what the office recorded; they do not cryptographically prove extraction correctness.

Signed answer payloads include answer ID, exact answer-text hash, query hash and typed target facts, tenant/office, `valid_at`, `known_at`, cited claim revision hashes and manifest roots, modes, model/prompt versions where used, creation time, and key ID. Changing the answer, citations, or time scope must invalidate verification.

Each office has a separate signing key. Generate private keys locally and keep them outside the repo and gateway volumes. Pin trusted public keys in verifier configuration; do not accept a public key merely because the same untrusted response supplied it. Key rotation is a roadmap item; use stable demo keys within a run.

Export signed checkpoints and verification bundles to a separate backup location before presenting. A local hash chain alone cannot detect an administrator rewriting both data and chain. The demo protects evidence relative to pinned keys and saved commitments; it does not claim protection if the signing keys and all trusted checkpoints are compromised.

### 7.3 Verification API behavior and honest guarantees

Verification accepts a supplied file copy or a signed evidence bundle. Never mutate the immutable original for the tamper demonstration. Report `file_hash`, `clause_inclusion`, `manifest_signature`, `claim_signature`, and `answer_signature` independently as `passed`, `failed`, or `not_checked`, with reasons. A remote source whose text is not disclosed has `clause_inclusion=not_checked` at the recipient; a valid signed reference is not equivalent to independently checking the source text.

**What is demonstrated:** supplied bytes match a previously signed source commitment; a disclosed clause belongs to a committed tree; recorded answers and provenance have not changed relative to trusted signatures.

**What is not demonstrated:** source truth, publisher authenticity unless independently established, legal validity, correctness of extraction or reasoning, zero-knowledge inference, or secrecy of low-entropy facts. Merkle inclusion is selective passage verification, not automatic confidentiality. Any future ZK predicate must also address how the committed numeric claim is bound to the source; proving arithmetic over an extracted number would not prove the number was extracted correctly.

## 8. Office isolation, federation, and hosted inference

### 8.1 Two distinct data flows

```text
Dhaka source files → local parser/store → OpenRouter/provider (demo extraction)
                                         ↓
                              validated claims in Dhaka store
                                         ↓ approved typed claims only
                             gateway → Frankfurt comparator
                                         ↑
Frankfurt source files → local parser/store → OpenRouter/provider (demo extraction)

Future production: each office's model calls terminate at its approved local
inference endpoint. Office-to-office claim exchange remains separately governed.
```

Demo statement:

> “This demonstration uses synthetic documents and hosted inference through OpenRouter. Each office has a separate knowledge store. Office-to-office responses contain only approved structured claims. Production is designed for inference within each office's infrastructure; local-model performance and geographic deployment remain to be validated.”

Two containers or laptops demonstrate logical isolation, not actual Dhaka/Frankfurt geographic residency. Running a model locally is necessary for the proposed local-inference mode but does not by itself establish all production privacy or compliance requirements.

### 8.2 Strict federation protocol

The gateway has an allowlisted office/topic catalog without document text. It does not mount office source directories, store raw documents, or expose raw-source proxy endpoints.

Use a typed subquery such as:

```json
{
  "request_id": "r19",
  "subject": "record_retention",
  "target": {
    "record_class": "loan_records",
    "origin_office": "DHAKA",
    "processing_office": "FRANKFURT",
    "product": "MTF_CROSS_OFFICE",
    "starting_event": "loan_closure"
  },
  "valid_at": "2026-03-03T12:00:00Z",
  "known_at": "2026-10-19T12:05:00Z",
  "egress_policy": "structured_claims_only"
}
```

Tenant, caller, source office, and permitted destination are derived from authenticated credentials and server configuration, not trusted from arbitrary request fields. The gateway forwards a request only to the registered topic office. The recipient verifies the sending office identity and destination permission before responding.

The timestamps in this example are illustrative. At runtime, the gateway captures a real `known_at` once and propagates it to both offices. Keep office clocks synchronized; do not claim that a wall-clock cutoff is a distributed atomic snapshot. If either office has not completed the relevant ingestion, report the response as partial.

Exported claim payloads contain only the supported subject/scope enums, rule kind/value/unit, effective dates, authority enum, opaque source/claim IDs, commitments, signer key ID, and signatures. They exclude source quotes, names, free-text titles, Slack author/channel names, arbitrary explanations, model-written answers, private locators, and unknown fields. IDs are backend-generated opaque identifiers, not user-supplied strings. Validate numeric bounds and enum domains to reduce accidental free-text channels.

The source office applies its own export policy before serialization; the gateway validates the received schema again. Sign exactly the allowlisted export payload. Import remote claims into a separate provenance namespace with their origin, signature, permission, time scope, and request ID; they do not become locally authoritative source documents. Frankfurt compares its own rule with the remote approved procedure claim. A remote failure returns `partial` or `abstained`, never “compliant.”

### 8.3 Egress controls and measurement

Sensitivity is `demo_shareable` or `restricted` for the MVP. Restricted sources and all their derived claims are denied office-to-office export. Keep source permissions attached to every derived object; formatting information as JSON does not make it non-sensitive. Hosted-model permission is separate, and demo calls are limited to approved synthetic fixtures.

Each outbound office transport serializes validated payloads through one audited path. Record destination, channel (`office_to_office` or `hosted_model`), request ID, payload type, actual serialized byte count and hash, outcome, and real time. For model calls, record body size, model/provider metadata when available, latency, and returned usage without logging credentials or full prompts. Cover failure responses and exception logging; they must not leak source content.

The demo counter is **“raw source text transferred between office nodes: 0 bytes.”** Derive it from audited serialized payloads classified under the allowlist, not from a response field that asserts zero. Also show total office payload bytes, hosted-model request bytes, and blocked-export count. Test the transport with canary source text to verify it is absent from office responses, gateway logs, and errors. This is application-path evidence, not independent proof of every packet leaving the operating system.

If an originating user is authorized to view a remote source, source viewing is a separate request at that source office. It is outside this strict-demo federation flow. Do not include raw passages in the federation demo to make remote citations clickable.

## 9. Model adapter and execution modes

### 9.1 OpenRouter now, configurable office endpoint later

Start with one inexpensive paid model for extraction and answer phrasing. Select its exact model ID and provider route by testing the fixture corpus, not by assuming the cheapest model will follow the schema. Store the selection in configuration and record it in evidence. Do not hardcode a current model price or promise performance without measuring it.

Per-office configuration includes `REGION`, `DB_PATH`, `SOURCE_DIR`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, provider preferences, request timeout, concurrency limit, retry budget, prompt/schema versions, and signing-key locations. Keep secrets in environment files outside version control, with a non-secret `.env.example`.

Use a provider-neutral interface for extraction and optional answer phrasing. Contain OpenRouter-specific request options inside its adapter. Request strict JSON-schema outputs on supported model/provider combinations; require compatible parameters and a rehearsed provider allowlist/order. OpenRouter documents [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs) and [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection). Use an explicit approved fallback route only after it passes the same checks. Do not allow automatic switching to an untested model to conceal failure.

Default to one concurrent model request per office, a configurable 30-second per-attempt timeout, and at most two attempts within a 65-second overall job model budget. These are starting settings to tune during rehearsal. Retry transient errors with bounded backoff; expose schema failures and timeouts. Add an application-level call/token budget plus provider account spending controls. A deterministic conflict check, signature verification, or supported numeric answer must not require a fresh model call.

For future local inference, change endpoint/model settings through the same interface, disable hosted fallback, and rerun the extraction and latency evaluation. A local endpoint's schema support may differ; validate and fail visibly. Do not implement a local model installation or claim production readiness during this MVP.

### 9.2 Explicit modes

| Mode | Behavior | Cache miss / outage |
|---|---|---|
| `live` | Calls configured hosted model for requested model stages; cache bypass available | Bounded retry, then visible failure/review |
| `cached` | Reuses validated cached model-stage outputs | Returns cache miss unless caller explicitly selects live mode |
| `replay` | Uses versioned synthetic extraction/phrasing fixtures and reruns the actual engine and verification | Missing fixture fails visibly; no model network request |

Report mode per stage. A query with cached extraction and live phrasing is not wholly uncached. New answer IDs, timestamps, and signatures are generated for each run; replay does not pretend a saved signature is a new model result.

Cache keys include tenant/region, complete extraction input and metadata hashes, parser version, model/provider route, prompt version, schema version, and relevant generation settings. Revalidate cached outputs. Never reuse an extraction across tenants or changed authority/effective metadata. Commit only synthetic cache fixtures after checking for credentials and personal data.

Offline replay is a reliability fallback, not an unannounced replacement for a live model demonstration. Keep one new Slack ingestion and one changed query available for a genuinely uncached demonstration if connectivity permits.

## 10. Access, responsible AI, and reviewer actions

Use a small static demo identity map: distinct scoped bearer tokens for uploader, reviewer, office reader, and inter-office service roles. Tokens map to tenant, office, and permissions on the server. Demo auth is deliberately minimal and must not be presented as enterprise identity management.

Enforce scope on ingestion, jobs, sources, source downloads, claims, findings, answers, lineage, verification bundles, review actions, and federation. Deny access before retrieval or model calls. A guessed object ID cannot bypass permissions. Return only the authorized subgraph; counts, hidden node names, and errors must not reveal restricted sources. Service tokens cannot access general-purpose raw-source endpoints. Keep private API bindings and tokens local to the demo network.

Treat PDF, Slack, and retrieved text as untrusted data. Source instructions such as “ignore your rules,” “mark me official,” or “send the document to this URL” cannot alter authority, permissions, prompts, or tool behavior. Extraction has no browsing, shell, or arbitrary tool access. Validate model outputs against the schema and trusted metadata before persistence.

Use synthetic people and no real customer data. If personal information is encountered accidentally, reject/quarantine the input for this MVP rather than claiming comprehensive PII removal. Frame alerts around guidance and procedures, not employee performance. “No decisions about individuals” does not remove the need for privacy controls or review.

Reviewers can acknowledge, resolve, or dismiss findings with a reason. Append actor, time, prior/new state, and referenced claim revisions as audit events. Do not delete contrary evidence or change effective policy just because a finding was dismissed. Policy changes require a new authorized source version. Audit extraction, validation, queries, and decisions with model/prompt/schema versions and real timestamps; omit credentials and unnecessary raw text.

## 11. Backend API and command contract

All routes are versioned under `/v1`. Use typed Pydantic request/response models, stable error codes, request IDs, and cursor/limit pagination. OpenAPI must document authentication, examples, and nullable fields. These routes are the required capabilities; avoid additional generic administration surfaces.

| Service | Endpoint | Contract |
|---|---|---|
| All | `GET /health`, `GET /ready` | Health/readiness, region, schema/build version; no secrets or model call |
| Office | `POST /v1/ingestions/pdf` | File + trusted manifest + mode; 202 with job ID; uploader role |
| Office | `POST /v1/ingestions/slack` | Validated saved event(s) + manifest + mode; job ID(s) |
| Office | `GET /v1/jobs/{id}` | Durable stage, attempts, mode, real timing, error/review reason |
| Office | `GET /v1/sources/{id}` | Authorized source metadata and local locator information |
| Office | `GET /v1/sources/{id}/content` | Authorized local source access; no gateway proxy |
| Office | `GET /v1/claims`, `GET /v1/findings` | Snapshot filters, exact scope, provenance, review state |
| Office | `POST /v1/findings/{id}/reviews` | Reviewer action and reason; append event |
| Office/gateway | `POST /v1/queries` | Question + typed target + time/mode; answer/status/citations or abstention |
| Office | `GET /v1/answers/{id}/lineage` | Authorized nodes/edges, evidence and verification statuses |
| Office | `POST /v1/verifications/source` | Source ID + supplied copy; separate file and clause checks |
| Office | `POST /v1/verifications/bundle` | Signed answer/manifest/proof bundle against pinned keys |
| Office, internal | `POST /v1/federation/claims` | Typed subquery, service authentication, strict signed export |
| Gateway | `GET /v1/audit/egress` | Authorized redacted transfer events and measured counters |

Gateway queries use the authenticated originating office. Route local source questions to that office; orchestrate Demo 3 by obtaining an approved remote claim and asking Frankfurt's comparator to combine it with the local policy. Gateway responses contain the final structured result and opaque remote citations, not source passages. Local query APIs may return source passages only to locally authorized readers.

Errors distinguish invalid input, unsupported content, forbidden access, extraction failure, cache miss, missing policy, unavailable office, and failed verification. Integrity failure is a structured result, not a generic server exception. Do not implement a reset endpoint; reset is an explicitly local demo command.

Provide these commands, with exact usage in the backend README:

```text
make setup            # Install locked dependencies / initialize local configuration
make up               # Start office nodes and gateway
make seed             # Ingest synthetic baseline through the normal pipeline
make demo-live        # New uncached Slack ingestion, query, verification, federation
make demo-replay      # Same supported story offline, with modes visibly labeled
make evaluate         # Held-out end-to-end metrics + machine-readable results
make test             # Deterministic required checks, no paid API calls
make reset-demo       # Confirm configured demo data directory, then reset only demo state
```

Reset refuses non-demo tenants/paths, preserves configured keys and versioned fixtures, and requires an explicit command-line flag for unattended execution. It never deletes arbitrary paths. Export evidence outside reset-managed directories. Seed must not insert hardcoded final findings or answers; replay may supply extraction proposals, but the real validators, engine, persistence, and signers must run.

## 12. Evaluation and definition of done

### 12.1 Evaluation corpus

Create about 40 labeled comparisons grouped into small complete PDF/Slack scenarios. Include positives and negatives, boundaries, explicit supersession, late-arriving policies, harmless minimum differences, incompatible requirements, different activities, unit mismatch, negation, unsupported exceptions, restricted sources, and ambiguous evidence.

Split by source scenario or policy family, not random pairs sharing the same source, into a development set and a held-out set. Do not tune prompts or rules against held-out labels and then report them as unseen results. Preserve the label definitions, expected classifications, and expected affected scopes in versioned fixtures.

Run from original files/events through extraction, candidate selection, and finding output. A missed extraction or candidate is an end-to-end miss; do not compute headline recall only on already-correct claims. Separately report extraction validation/semantic errors, candidate recall, and classification performance to explain failures.

### 12.2 Metrics and evidence

| Measure | Required reporting |
|---|---|
| Finding quality | TP/FP/FN, precision, recall, per-class counts, correct affected scope |
| Abstention/review | Counts and reasons; do not hide misses in a review category |
| Timing | End-to-end ingestion-to-finding time; per-stage timing; live/cached/replay separately |
| Model use | Requests, retries, model/provider, returned usage, estimated cost if pricing is supplied |
| Integrity | Original pass, modified file failure, modified answer failure, proof/signature failure counts |
| Boundaries | Exact outcomes at USD 25,000; 25,000.01; 50,000; 50,000.01 |
| Federation | Measured payload bytes per channel, blocked exports, timeout/partial responses |
| Resource use | Measured peak memory on the primary laptop and setup/startup time |

Do not invent success rates, hours saved, customer validation, or regulatory compliance. If pricing is unavailable, report tokens rather than fabricated costs. Small synthetic evaluation results are prototype evidence, not estimates of production accuracy.

To estimate review effort, have a teammate review a labeled scenario manually before seeing the system output. Define the same task for the assisted run, include human verification time, record accuracy and duration, and disclose sample size and familiarity effects. If no baseline is collected, omit time-saved claims entirely.

### 12.3 Acceptance checks

The backend is complete when all of the following pass:

1. Fresh setup starts both office nodes and gateway on the designated laptop without a local LLM or frontend.
2. Ingesting v2, v3, and the new Slack event through normal APIs produces one stale-guidance finding for `25000 < USD amount <= 50000`. Explicit v2 supersession does not generate a second active contradiction.
3. USD 25,000 needs one approval; 25,000.01, 50,000, and 50,000.01 need two under v3. The stale Slack advice applies to the middle two amounts, not the first or last. Zero/negative amounts and unsupported currencies are rejected or abstained.
4. Minimum-one/minimum-two and minimum-five/minimum-seven comparisons are compatible. Minimum-seven/maximum-five requirements conflict only on a shared applicable scope and starting event. The five-year operating procedure fails the shared seven-year requirement.
5. Historical `valid_at` selects the right version; earlier `known_at` cannot use a subsequently ingested policy. A later supersession does not rewrite earlier snapshots.
6. Repeated ingestion/restart does not duplicate sources, claims, or findings; identical text from distinct source identities preserves both sources.
7. Number normalization accepts `50k` and number words; unsupported exceptions and injected instructions cannot produce silently promoted policy or permissions.
8. The USD 30,000 answer states the authoritative two-approval requirement, warns about stale guidance, cites real evidence, and has a verifiable signature bound to its exact text and time scope. Missing evidence produces abstention.
9. Original file and valid inclusion proofs pass. Altered file, altered leaf, altered manifest, altered claim, and altered answer fail the appropriate checks. Metadata-only PDF edits distinguish file mismatch from unchanged clause text.
10. Unauthorized readers cannot recover restricted content through source, finding, lineage, counts, errors, or federation APIs. A service credential cannot fetch raw source content.
11. Demo 3 returns a procedure-level compliance gap with approved claim references; canary source quotes do not appear in office-to-office payloads or gateway logs. A restricted export is denied; an office outage produces a visible partial/abstained result.
12. Offline replay performs no model calls, exposes its mode, and reruns actual validation/comparison/verification. Live failure never silently switches to fixtures.
13. Evaluation exports measured results and the exact corpus/configuration/mode. A clean reset and replay work on both primary and backup laptops.

Use focused unit checks for constraint semantics, intervals, serialization/proofs, and permission filters, plus integration checks for the full stories, job recovery, and transport boundaries. Paid live-model evaluation is a separately invoked command, not part of routine offline tests. Do not write tests that only assert a hardcoded demo response.

## 13. Onsite deployment and presentation

### 13.1 Laptop allocation

Five members have 16 GB laptops. With hosted inference and small synthetic datasets, target one laptop for the entire lean stack and measure its actual memory use. Do not require Neo4j, GPU inference, five active machines, or venue LAN connectivity for the primary demo.

| Laptop | Role |
|---|---|
| 1 | Primary: Dhaka service, Frankfurt service, gateway, terminal demonstration |
| 2 | Tested backup: same code, dependencies/images, configuration shape, fixtures, synthetic cache, trusted verification material |
| 3–5 | Development, evaluation, narration, evidence, and troubleshooting; not required runtime dependencies |

Keep databases, source directories, signing keys, and service credentials separate per office. The gateway has no source-volume access. Compose uses readiness checks and configurable node addresses. Bind public demo ports to localhost by default. If rehearsing separate laptops, use authenticated HTTPS with trusted certificates and a private hotspot/router; mTLS is a production hardening option, not a falsely claimed implemented feature. This optional topology does not establish geographic residency.

### 13.2 Live demonstration sequence

Rehearse a three-minute core path, adjusting to the organizer's actual allotted slot:

1. **Problem and Catch:** show preloaded policy versions, ingest the new Slack message live, display the job mode and exact affected range.
2. **Trace:** ask the USD 30,000 question, display citations and lineage, verify original versus changed copy, and show answer-signature failure after modification.
3. **Border:** compare the scoped five-year procedure with the seven-year requirement. Display approved payload shape, blocked restricted export, and separately labeled office/model counters.
4. **Close:** show measured quality/timing, buyer/pilot hypothesis, demo limitations, and the contribution status of any NRB collaborator.

Narration: “The model extracts proposed rules. Our supported rule engine checks applicability and compatibility. Each result links to evidence committed at ingestion. Here, inference is hosted; office-local inference is the production design.”

Use terminal output formatted for an audience, with short labels and a saved full JSON bundle. OpenAPI can help explain endpoints; no custom UI is required. Keep full evidence available for judge questions without forcing every technical field into the main presentation.

### 13.3 Reliability procedure

Before the event, install locked dependencies, build and save images locally, test primary and backup from clean demo state, verify account balance and the approved model route, prepare a hotspot, and measure a cold live run. Keep an uncached Slack event and a changed query ready. Never put secrets in displayed shell commands.

At the venue, check health/readiness, local service connectivity, live inference, and file verification before presenting. Run the primary path on one laptop. If model connectivity fails, announce offline replay and continue with real engine/integrity checks. If the primary laptop fails, use the tested backup. A recording is additional evidence, not the sole fallback for a required live demonstration.

Keep baselines, synthetic cache, and verification bundles available locally. Rehearse three times after feature freeze. Do not depend on installing packages, downloading model weights, live Slack authorization, or cross-laptop Wi-Fi during the presentation.

## 14. Buyer, pilot, impact, and global collaboration

### 14.1 Business hypothesis

**Initial customer:** a trade-finance or lending organization with a compliance team and more than one office. **Daily user:** compliance/policy operations analyst. **Potential budget owner:** head of compliance or operations. These are hypotheses, not confirmed customers.

The initial workflow is narrow: a policy owner publishes a revision; the analyst reviews affected operational guidance, confirms findings, and distributes corrections with evidence. The tool recommends and documents; it does not approve loans, make employee decisions, or certify legal compliance.

Monetization hypothesis: an annual organization subscription based on office deployments, with reviewer seats and connector support. Pilot pricing and willingness to pay remain unvalidated. For office-local deployments, “subscription” can mean licensed software/support on customer infrastructure rather than assuming all document processing runs in our SaaS.

Cost drivers include connector integration, inference, support, deployment, security review, and model evaluation. Hosted-demo API cost is not a production margin estimate. The proposed local-inference deployment shifts compute costs to the office but does not make deployment and maintenance free.

### 14.2 Validation tasks and evidence status

| Item | Task before claiming validation | Current status |
|---|---|---|
| Problem demand | Interview 3–5 relevant users about their last policy update, stale advice, and review workflow | Not yet validated |
| Buyer and procurement | Identify budget ownership, deployment restrictions, existing tools, and approval path | Hypothesis |
| Value | Measure assisted review time and accuracy against a defined manual task | Not yet measured |
| Pilot | Seek a small, authorized synthetic or appropriately approved document pilot | Proposed; no commitment claimed |
| Pricing | Ask about purchasing process and compare value with total deployment cost | Hypothesis |
| Local inference | Run supported corpus on the intended office endpoint and measure quality/latency | Roadmap validation |

Record interview role/date/consent and deidentified findings, including objections. Do not invent testimonials. A useful pilot success definition is: detect labeled stale guidance, avoid compatible-rule false alerts, provide traceable evidence, and reduce the review task's duration without reducing accuracy. Agree numerical targets with a pilot participant rather than presenting invented results.

Bangladesh relevance is the potential to reduce operational mistakes and policy-review burden in organizations coordinating local and overseas offices. Economic benefit is a hypothesis until measured. Global adaptation requires local policy authority, language/number-format evaluation, connectors, and deployment approval; changing a country tag is not sufficient.

### 14.3 NRB collaboration

Invite an NRB or international contributor for one concrete task: review a cross-office workflow, label ambiguous policy examples, or contribute a tested regional connector adapter. Record the deliverable, role, consent to attribution, and whether the involvement is proposed, agreed, or completed. Do not claim an existing partner without confirmation. Synthetic fixtures permit collaboration without sharing customer documents.

Define a normalized connector contract and one fixture-based adapter example in the backend README. Additional connectors are future contributions rather than MVP dependencies.

## 15. Team plan, build order, and submission evidence

### 15.1 Five-member ownership

| Person | Owns | Review partner |
|---|---|---|
| 1 | PDF/Slack ingestion, manifests, extraction adapter, evidence validation | Person 2 |
| 2 | Claim schema, temporal revisions, rule engine, snapshot queries | Person 1 |
| 3 | Commitments, signatures, query citations, lineage API, verification | Person 5 |
| 4 | Corpus/labels, evaluation, terminal demo, buyer interviews, narration | Person 2 |
| 5 | Federation, authorization boundaries, egress audit, Compose, backup setup | Person 3 |

Person 4's former frontend allocation becomes evaluation and presentation work. This table assigns work to the five human team members.

### 15.2 Build sequence and exit gates

1. Freeze typed claims, manifests, applicability, API response shapes, and the synthetic fixture wording. Create the held-out labels before tuning extraction.
2. Implement persistence, ingestion jobs, extraction/replay modes, and the supported constraint engine. Exit when Demo 1 and negative compatibility/boundary checks pass.
3. Implement historical snapshots, evidence commitments, answer binding, and verification. Exit when Demo 2 and temporal/tamper checks pass.
4. Add scoped query/lineage endpoints, reviewer events, and authorization checks. Exit when unauthorized access cannot bypass the same restrictions through derived objects.
5. Add two-office claim exchange and audit instrumentation. Exit when Demo 3, denied export, and unavailable-office behavior pass.
6. Run held-out live evaluation, measure resources and costs, collect any manual-review baseline and interview evidence. Report failures as well as successes.
7. Freeze features, prepare backup, reset and rehearse three times. Submit the actual measured evidence and limitations.

If time is tight, retain a correct Catch and Trace, then a minimal typed two-office Border. Do not add ZKP, a graph server, or local model setup at the expense of the live path. Any omitted required feature must be listed as incomplete rather than simulated without disclosure.

### 15.3 Judging evidence map

| Criterion | Concrete evidence to present |
|---|---|
| Innovation, 20 | Policy-specific stale guidance, applicability and exact affected ranges; clear comparison with temporal-memory approaches |
| Technical execution, 20 | Working API pipeline, structured rules, temporal snapshots, negative tests, signatures, visible errors |
| Business/global readiness, 20 | Buyer/workflow hypothesis, real interview notes if obtained, pilot design, licensed local deployment pathway |
| Impact/ethical AI, 20 | Measured end-to-end metrics, documented baseline if collected, authorization, review, abstention, synthetic-data disclosure |
| Scalability/NRB, 10 | Separate office modules, indexed incremental comparisons, measured resource use, connector contract, actual collaboration status |
| Presentation, 10 | Rehearsed onsite script, one uncached interaction, understandable explanations, tested fallback, saved evidence |

Index candidate lookups by subject/scope/time and re-check only affected claims on ingestion. This improves typical workloads but does not eliminate worst-case pairwise comparisons when many claims share the same scope. Production scaling would require a durable distributed queue, stronger storage/identity/transport controls, and measured regional inference capacity; those are a deployment pathway, not implemented claims.

### 15.4 Implementation handoff checklist

The implementation model must deliver source code, locked dependencies, migrations, `.env.example`, Compose configuration, a backend README, synthetic PDF/Slack inputs and manifests, versioned model-stage fixtures, API examples, demo/evaluation commands, and the focused checks in section 12. Keep generated private keys, real credentials, runtime databases, and non-synthetic content out of version control.

The README must distinguish implemented, fixture-backed, unvalidated, and deferred capabilities. Include the exact model/provider route selected during rehearsal, its measured behavior, the modes used for each result, how to verify an exported bundle independently, and known limitations.

External documentation used to clarify the design is linked where relevant. The hackathon judging criteria above are preserved from the supplied proposal; organizer-specific demo duration and submission mechanics must be checked against the event's actual instructions.
