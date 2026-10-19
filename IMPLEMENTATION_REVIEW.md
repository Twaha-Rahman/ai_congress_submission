# Implementation Review

Reviewed: 2026-10-19. Scope: implementation against the revised proposal and backend implementation brief.

The project has substantial working code, useful module boundaries, durable jobs, real constraint comparisons, signed records, and a reproducible synthetic corpus. The existing offline suite passes: **65 passed in 0.61s**. It still has significant correctness and authorization gaps in the features used to justify its trust and office-isolation claims.

## Verification performed and limits

- Read the application, tests, packaging, README, and implementation status.
- Ran `.venv/bin/python -m pytest` successfully.
- Ran isolated temporary-database probes using the real ingestion, query, export, and verification code. Proposals intentionally containing errors were passed through the actual validator.
- Invoked actual office route handlers with principals authenticated through the real registry. These were handler-level checks, not complete HTTP middleware/socket tests. A threaded TestClient attempt hung in this environment and was terminated; this is not counted as an application failure.
- Used `httpx.MockTransport` to capture hosted-model requests and exercise the gateway's invalid-signature path. No paid or external model requests were made.
- Inspected Compose mounts and Dockerfile contents. Did not start Docker, reset existing demo state, or rehearse on another laptop. Existing saved evaluation/demo results were not independently rerun.
- Application code was not changed during this review. This report records findings and repair gates.

## R1 — High: enforce office and source permissions on derived-object APIs

Locations: [office query handler](meridian/office_api/main.py#L577), [stored answer handler](meridian/office_api/main.py#L608), [bundle handler](meridian/office_api/main.py#L634), and [restricted finding responses](meridian/office_api/main.py#L437).

The query handler checks permission and tenant but never requires the principal's office to match the office service. The global principal registry recognizes credentials for both offices in local-process deployments. A Frankfurt reader can invoke the Dhaka query handler and receive a Dhaka answer including a source quote. The direct source/listing routes do more checks, so protection varies by endpoint.

Stored answers and bundles check `READ_LOCAL` but do not re-authorize their cited sources. Reproduction: create an answer for a USD 2,000,000 loan as a Dhaka reviewer, then retrieve that answer as a Dhaka reader. The reader receives the restricted policy quote and three-approval conclusion. The bundle also contains the restricted claim's evidence quote, despite withholding its full clause entry. The response leaks information already computed for the more privileged caller.

Restricted findings intentionally expose their existence, ID, subject, and severity to readers, contrary to the proposal's no-existence-leak requirement. Jobs and claim-review lists also need source-aware filtering.

**Repair gate:** centralize tenant/office checks and authorize every referenced source before returning a saved answer, bundle, finding, job, or review. For an inaccessible signed answer, deny retrieval or generate a distinct authorized answer; do not modify signed content and retain its signature. Add route-level tests for cross-office credentials, privileged-created answers retrieved by readers, mixed-sensitivity bundles, counts, and metadata.

## R2 — High: Merkle proofs are not bound to the signed manifest root

Locations: [clause verification](meridian/integrity/bundles.py#L269), [proof-root handling](meridian/integrity/bundles.py#L130), and [answer evidence binding](meridian/integrity/bundles.py#L325).

The verifier recomputes a disclosed clause leaf and checks it against the root supplied in that clause's proof. It does not require that proof root/tree size equal the authenticated manifest root/tree size. Wrapper identity/hash fields are also not fully compared with the signed manifest payload.

Reproduction: take a valid public answer bundle, append invented text to a disclosed clause, recompute its leaf, and replace its proof with a one-leaf tree whose root is that new leaf. Leave the signed manifest, claims, and answer untouched. **Every reported check still passes**, including `clause_inclusion`, `manifest_signature`, and `answer_binding`. No signing key is needed for this modification.

**Repair gate:** parse and validate signed manifest payloads, bind every wrapper field and proof to those authenticated values, and bind claim evidence locators/leaf hashes to the disclosed passage and proof. Altered text with an attacker-chosen root must fail even when all original signatures remain valid. Missing local evidence must be incomplete/failed as appropriate, not silently treated as a fully verified bundle. Preserve explicit `not_checked` handling for legitimately undisclosed remote evidence.

## R3 — High: rejected federation signatures can still influence answers

Locations: [invalid export returned with data](meridian/gateway_api/orchestrator.py#L224), [answer consumer](meridian/gateway_api/orchestrator.py#L318), and [retention import/comparison flow](meridian/gateway_api/main.py#L160).

`fetch_export` correctly detects a bad signature but returns the untrusted export attached to an `OfficeResult(status="invalid")`. `federated_answer` accepts any non-null export without requiring successful verification. The retention path likewise checks export presence and does not stop when the import response says `accepted=false`.

Reproduction: change a valid two-approval export to one approval, recompute its payload hash, and retain its now-invalid signature. A mocked office response is marked `invalid`, but the real gateway answer function returns `answered` and states one approval is required for USD 30,000.

**Repair gate:** invalid exports never enter computation; use an explicitly verified representation or remove their payload from downstream results. Require successful import before comparison. Bind exports to the requested origin, signer office, request ID, target, and time snapshot. Add tests that use the full fetch-to-answer path, not just `verify_export` in isolation.

## R4 — High: hosted-model permission is recorded but not enforced

Locations: [pipeline extraction call](meridian/ingestion/pipeline.py#L428) and [live adapter selection](meridian/extraction/service.py#L118).

The manifest stores `permissions.hosted_model`, but neither the ingestion path nor live selection checks it before sending source text to the configured provider.

Reproduction: change a restricted synthetic source's permission to `hosted_model=false`, request live mode, and attach a mocked HTTP transport. The transport receives **one request containing the source's exact evidence text**, and ingestion succeeds. No actual external request was made in this review.

**Repair gate:** check processing/egress permission before the model transport or cache persistence, return a clear denied/review result, and audit the block. Add a regression asserting zero HTTP requests when hosted processing is forbidden. Future local-provider handling must distinguish an approved local endpoint explicitly; arbitrary URLs must not bypass the hosted prohibition.

## R5 — High: extraction validation accepts reversed meanings

Locations: [number/bound checks](meridian/extraction/validate.py#L327), [modality checks](meridian/extraction/validate.py#L361), and [generic modality patterns](meridian/extraction/validate.py#L37).

Validation checks whether numbers occur and whether a matching keyword occurs somewhere. It does not establish that the comparison direction or number-to-obligation relationship matches the text.

Two accepted reproductions:

1. Source says loans **greater than USD 25,000** need two approvals; proposal says the rule applies **at or below USD 25,000**. All numbers occur, and the proposed range fits within the broad manifest, so it is accepted.
2. Source says a loan requires **at most two approvals**; proposal says `required_minimum=2`. The word `requires` satisfies the generic minimum pattern, so the maximum is accepted as a minimum.

**Repair gate:** implement the narrowly supported grammar with operators tied to their amounts/units and require unambiguous agreement between source wording and proposed semantics. Conflicting or unsupported parses go to review. Add tests for flipped bounds, inclusivity, minimum/maximum/exactly confusion, unrelated numbers, and omitted limits. Do not weaken validation to increase a live demo's success rate.

## R6 — High: retention answers ignore additional applicable requirements

Locations: [office retention answer](meridian/queries/engine.py#L426) and [gateway equivalent](meridian/gateway_api/orchestrator.py#L419).

Retention answering uses `requirements[0]` and `procedures[0]` instead of evaluating the full applicable set. It can omit an existing contradiction or compare a procedure against a weaker rule. The numeric loan template also always begins “at least,” even for supported exact/maximum constraints, and retention gap text always prints a less-than comparison.

Reproduction using actual evaluation PDFs: ingest the minimum-seven-year policy and maximum-five-year policy for the same records. The finding engine persists a `contradiction`, while the query returns `answered`, says only “at least 7 years,” and cites just one policy.

**Repair gate:** share allowed-set aggregation between finding and query paths. An empty authoritative intersection requires review and citations to both rules; compatible requirements must all contribute correctly. Compare all applicable procedures without choosing by row order. Render the actual resulting constraint and inequality. Test reversed insertion order and exact/maximum cases in both office and gateway paths.

## R7 — High: old remote claims remain active across later exports

Locations: [import accumulation](meridian/federation/exchange.py#L209), [unscoped remote retrieval](meridian/queries/engine.py#L159), and [remote knowledge timestamp](meridian/federation/exchange.py#L347).

Imports accumulate by revision ID. Query answering then merges every stored remote claim for the subject, without restricting to the current request's verified snapshot or processing retirement/replacement information. Source-office `system_from` is reused as recipient knowledge time even though the recipient may have learned the claim much later.

Reproduction: import a valid five-year procedure export, then a valid current export containing an updated eight-year procedure. Both remote values remain eligible. The query still selects five years and reports the old gap against the seven-year policy.

**Repair gate:** for the demo, bind comparisons to the exact verified claim IDs from the current export/request. If retaining remote history, keep explicit export snapshots, recipient receipt times, and authenticated closure/replacement information. Current queries must not reuse facts absent from the current complete snapshot; historical recipient queries must not use information before receipt. Test repeated queries, updated procedures, empty exports, withdrawn permissions, and old snapshot replay.

## R8 — High: container mounts do not isolate office files or private keys

Locations: [Dhaka volume](docker-compose.yml#L54), [Frankfurt volume](docker-compose.yml#L81), [gateway fixtures mount](docker-compose.yml#L107), and [image contents](Dockerfile#L18).

Both office containers mount all of `./runtime` at `/app/runtime` under the same configured UID/GID. Each office therefore has filesystem access to the other office's database, source files, and signing private key. Separate DB path settings do not restrict that access.

The gateway does not mount live office source directories, but it mounts the entire fixture corpus, including original PDFs and Slack messages. The shared image also copies that corpus into every service. Thus it already has synthetic raw source content despite the “metadata-only” claim.

**Repair gate:** mount only each office's own runtime data and key directory, plus read-only public-key pins and necessary configuration. Keep raw corpus material in host-side seeding tools or office-specific fixture assets; omit it from gateway mounts and image layers. Verify from inside each container that other-office files/private keys and gateway raw corpus are absent or unreadable. Preserve the declared same-machine/geographic simulation limitation.

## R9 — Medium: unvalidated replacement retires validated policy

Locations: [unconditional replacement application](meridian/ingestion/pipeline.py#L588) and [closure creation](meridian/temporal/supersession.py#L104).

Supersession proceeds even when all new proposed rules fail validation. Reproduction: ingest valid v2, then v3 whose model proposals contain unsupported approval numbers. Zero v3 rules are accepted, but both old revisions are closed. A current loan query now abstains because no accepted requirement remains.

Abstaining is safer than inventing an answer. However, pending replacement knowledge is not explicitly represented to the query, and valid coverage can be retired without a validated replacement. Partial extraction can similarly create unexplained holes.

**Repair gate:** define and implement atomic replacement acceptance or a visible pending-replacement state. A pending policy change must yield a specific review/incomplete-policy result; do not describe the old rule as definitely current, silently retire unrelated scope, or lose earlier snapshots. Test zero accepted rules and incomplete amount-band coverage.

## R10 — Medium: immutable-version deduplication compares text, not original bytes

Location: [duplicate detection](meridian/ingestion/pipeline.py#L366).

The same identity/version is considered duplicate when parsed content hashes match, even if original PDF bytes or trusted metadata differ. This conflicts with the immutable version/file identity contract.

Reproduction: edit only the PDF subject metadata, preserving extracted text, and upload under the same version. The file hash changes but ingestion returns `duplicate=true` with no mismatch error. A legitimate reviewer may believe the newly submitted file was accepted even though the stored commitment still refers to the earlier bytes.

**Repair gate:** compare original-byte and canonical trusted-manifest hashes for immutable-version identity. Reject changed bytes/metadata under that identifier or require a new explicit version. Test exact replay, metadata-only PDF changes, altered effective dates, and changed permissions separately.

## Suggested repair order and release check

1. Add independent regression cases for R1–R8, then fix the trust boundaries and root/signature binding.
2. Correct extraction semantics and query aggregation; ensure failures remain visible.
3. Repair remote freshness, replacement handling, and immutable-version checks without rewriting existing signed history.
4. Rerun the existing suite and new regressions, then the clean replay demo and held-out evaluation. Keep replay evaluation labeled: its perfect score does not measure hosted model extraction quality.
5. Execute a genuine uncached extraction using the chosen OpenRouter model, and rehearse on the backup laptop. The implementation status already identifies those as outstanding; this review did not complete them.

Use the existing architecture for a focused repair pass. The current test suite is useful, but helper-level success does not establish safe behavior at the API, verifier, or gateway composition boundaries.
