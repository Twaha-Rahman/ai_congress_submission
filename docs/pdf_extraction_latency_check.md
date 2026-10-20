# PDF extraction latency check — 20 October 2026

Follow-up: [full paid HTTP API verification with default reasoning](pdf_api_verification.md)
now covers successful ingestion, comparisons, findings, and evidence validation.

One explicitly authorized paid extraction request used
`fixtures/conflict_testing/northwind_security_procurement_procedure_2026.pdf`.
The PDF text was parsed with the real ingestion parser and submitted with the real
general-policy extraction prompt. This was an isolated extraction test; it did not
publish sources/findings or run pair comparisons. Client retries were disabled for
the measurement. No second paid generation was made.

## Configuration and measured results

| Item | Result |
|---|---|
| Model | `deepseek/deepseek-v4.1-flash-1017` |
| Allowed providers | DeepSeek and Cloudflare only; DeepSeek preferred |
| Actual response provider | Cloudflare |
| Reasoning request | `effort: none` |
| Reported reasoning tokens | 0 |
| PDF size | 2 pages; 30 parsed clauses; 4,911 characters |
| Local PDF parsing | 3.961 milliseconds |
| HTTP headers received | 3.978 seconds |
| Complete model response | 37.966 seconds |
| HTTP status / finish reason | 200 / `stop` |
| Input tokens | 2,313 |
| Output tokens | 6,249 |
| Reported request cost | USD 0.0039807 |
| Request / response bytes | 17,429 / 26,316 |

The earlier request exceeded 300 seconds without a completed extraction. This new
configuration returned a complete HTTP response in about 38 seconds. Both routing
and reasoning changed, so this single observation cannot isolate either one's
contribution, compare the providers, or establish a general latency guarantee.
DeepSeek itself was not benchmarked independently.

## Output validation and follow-up

The response was JSON but failed the application's semantic schema validators:
27 proposed rules used incompatible subject/rule/scope types. It was **not a
successful ingestion or conflict-detection run**, and no findings were published.

The general extraction request previously exposed the combined numeric/general
response schema. The request schema now constrains subject to `general_policy`,
scope to `PolicyScope`, and rule to `PolicyRule`. Numeric ingestion keeps its own
existing behavior. A regression test checks that numeric scope alternatives cannot
appear in the general structured-output contract.

This narrower contract was added after the paid call and verified offline. It has
not been validated with a second paid generation, so successful live extraction
and conflict quality remain unconfirmed. The complete local measurement, including
the OpenRouter generation ID, is in ignored `runtime/paid_pdf_benchmark.json`.
