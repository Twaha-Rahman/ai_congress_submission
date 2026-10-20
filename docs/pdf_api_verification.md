# Paid PDF API verification — 20 October 2026

The final fresh-database run found all **five expected conflict candidates**, assessed
all **four compatible cases without false conflicts**, and held the missing
Appendix C exception for review. It accepted **47 statements** and held **one**.
There were no provider, schema, internal, or evidence-location errors in this run.

## What was exercised

Both PDFs in `fixtures/conflict_testing` were uploaded, in the fixture's specified
order, with their manifests and `mode=live`. Requests used real HTTP against an
isolated FastAPI office, real bearer authentication, the durable worker, the PDF
parser, paid OpenRouter calls, validation, signed publication, and the normal
jobs/sources/claims/findings endpoints. Production office databases were not used.

Configuration matched the demo: `deepseek/deepseek-v4.1-flash-1017`, default reasoning
(no reasoning override), 600-second extraction and comparison timeouts/budgets,
top-six retrieval, and at most 24 comparison calls per source. The only allowed
providers were DeepSeek and Cloudflare, with DeepSeek preferred.

The demo now explicitly uses `LLM_RESPONSE_FORMAT=json_object`. The same output
schema is supplied in the system prompt and enforced by the backend. Invalid JSON,
invalid fields, invented quotations, incorrect locations, and scope changes still
fail validation. There is no automatic output-mode fallback.

OpenRouter's endpoint metadata at test time advertised `structured_outputs` for
Cloudflare, but not DeepSeek. Consequently, requiring strict structured outputs
prevented the preferred DeepSeek route from being used. The strict Cloudflare run
reached its 600-second budget without a completed extraction. An explicit DeepSeek
JSON-mode diagnostic returned in 71.7 seconds. All 50 calls in the final full API
run were served by DeepSeek. This comparison changes both provider and output mode;
it is not an isolated provider-speed benchmark.

References: [model endpoint metadata](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints),
[structured-output routing](https://openrouter.ai/docs/guides/features/structured-outputs).

## Final measured results

| PDF | Paid extraction | Complete upload job | Comparison calls |
|---|---:|---:|---:|
| Employee handbook | 77.8 seconds | 166.2 seconds | 24 |
| Security/procurement procedure | 47.8 seconds | 144.2 seconds | 24 |

The 48 comparisons had a median duration of 3.315 seconds (range 1.895–8.839).
Both jobs completed on their first attempt with no error code. Reported cost for
the final 50-call run was **USD 0.050654652**. Default reasoning remained enabled;
the extraction responses reported 17,151 and 9,985 reasoning tokens respectively.
Prompt caching and generation variability affect these timings and costs.

| Fixture case | Observed result |
|---|---|
| 30-day requirement vs 60-day permission | Contradiction, review severity |
| 25-day leave entitlement vs 20-day cap | Contradiction, review severity |
| Personal-email prohibition vs remote-work permission | Contradiction, review severity |
| Approval above EUR 500 vs no approval up to EUR 2,000 | Contradiction, review severity |
| Economy-only handbook vs premium-economy procedure | Compliance gap, review severity |
| Two mandatory travel deadlines | Consistent |
| 12-character and 16-character password minimums | Consistent |
| Personal email vs approved-vendor secure portal | Unrelated; both relevant pairs assessed |
| Warehouse safety clothing vs office dress | Unrelated |
| Missing Appendix C criteria | Statement held for extraction review; no conflict published |

Compatible cases were checked against completed comparison responses, not merely
the absence of findings. There were no unexpected conflict findings.

**Fixture expectation distinction:** `expected_findings.json` asks for a pairwise
`needs_review` finding for Appendix C. The application instead holds that statement
before comparison, as a signed `needs_review` claim plus an `unsupported_condition`
review item. Thus the literal pairwise-finding check does **not** pass. The intended
safety behavior is preserved: the missing exception is visible for review and is
never accepted or classified as a contradiction. The fixture was not altered to
hide this distinction.

Both original PDFs were downloaded through the API and matched the uploaded bytes
exactly. All five finding signatures and snapshot hashes verified. The 47 accepted
claim signatures, quote offsets, and source-root bindings also verified.

## Problems fixed during verification

- Clear conflicting statements were previously all marked ambiguous, preventing
  comparison. Extraction now leaves consistency assessment to the comparison stage.
- Redundant actor/action/constraint fields were paraphrased despite correct quotes.
  Hosted extraction now supplies complete verbatim passages; comparison interprets
  their meaning with full source context.
- Introductory statements exhausted the comparison budget in extraction order.
  Retrieved pairs are now ranked together before the global call limit is applied.
- Comparison instructions now distinguish exception applicability from resolution
  of the conflict itself, and distinguish compatible mandatory bounds from an
  explicit permission to violate a stricter requirement.
- Exact full section headings are accepted as location hints when backed by the
  source heading. Invented titles and incorrect locations remain review items.
- Explicit JSON mode lets DeepSeek serve this demo while retaining backend schema
  and evidence validation. Output modes have separate cache identities.

The final prompt versions are `general-extract-v3` and `general-compare-v3`.
The offline suite passes **160 tests**. A separate paid HTTP comparison-retry run
also found all five conflicts and assessed all four compatible cases successfully.
Both running offices and the gateway were restarted with the final changes; all
three `/ready` endpoints returned HTTP 200.

## Limits and local evidence

Both final jobs correctly finish `needs_review`: top-six retrieval and the 24-pair
limit leave incomplete coverage, and Appendix C is genuinely missing. These are
visible review reasons, not processing errors. This small fixture run establishes
the outcomes above, not exhaustive detection for arbitrary office policies.

Older stored source versions are not automatically re-extracted. Upload a new
version to use the corrected extractor. **Retry comparison** reuses accepted
statements and cannot recover statements held by an older extractor.

The final report, request/response traces, case audit and HTTP integrity checks
are in ignored `runtime/live-api-verification/round5/`. The comparison-retry report
is in `round4/recheck-report.json`. Across the investigation, completed responses
reported **USD 0.199159592** in total. This is not a complete billing total: timed-out
or interrupted requests that returned no usage information may incur other charges.
Obsolete runs were stopped to prevent further calls on old code.

See [the general-policy demo guide](general_policy_demo.md) for normal API use and
configuration. The older [latency-only experiment](pdf_extraction_latency_check.md)
used disabled reasoning and did not establish successful ingestion; this report
records the subsequent full API verification with default reasoning.
