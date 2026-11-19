# Northwind policy-conflict test pack

Two realistic two-page corporate PDFs for exercising general-policy extraction and
model-assisted conflict detection. Each document mixes real policy clauses with
ordinary corporate material (org chart, service standards, office directory, people
metrics, spend dashboard, risk register, committee minutes, glossary and document
history). The extra material is there to check that extraction and comparison do not
turn non-policy text into conflict findings.

These are **known test fixtures, not a benchmark or a legal opinion**. Conflict
findings are model-assisted candidates with `review` severity; a human must inspect
the quotations and decide. A clean run does not prove that every statement was
assessed.

| File | Purpose |
|---|---|
| `northwind_employee_handbook_2026.pdf` | Policy document: travel, leave and workplace conduct |
| `northwind_security_procurement_procedure_2026.pdf` | Procedure document: security, purchasing, travel security and physical access |
| `manifests/*.json` | Trusted upload metadata for the API or automated checker |
| `expected_findings.json` | Machine-readable expected conflicts, decoys and the missing-exception case |

## Upload settings

Use **Sources -> Upload PDF**. Do **not** choose *Replace*: these are independent
documents, not versions of the same policy.

| Field | Employee handbook | Security and procurement procedure |
|---|---|---|
| Policy name | `northwind_employee_handbook_2026` | `northwind_security_procurement_procedure_2026` |
| Version | `v1` | `v1` |
| Policy category | `people_travel` | `corporate_security_procurement` |
| Source authority | **Policy** | **Operating procedure** |
| Publication date | `2025-12-15` | `2025-12-18` |
| Effective from | `2026-01-01` | `2026-01-01` |
| Applies to | `All Northwind Trading Bangladesh employees` | `All Northwind Trading Bangladesh employees` |
| Scope labels | none | none |
| Hosted model consent | allow | allow |

Upload the handbook first, then the procedure. The handbook creates the internal
conflicts; the procedure creates its own conflicts and the one cross-document
conflict against the handbook's airfare rule.

Both documents must use the **same applicability and effective date**. Different
scope labels or non-overlapping dates make a pair legitimately `not_comparable`, so
the cross-document check would not run.

## Full coverage vs. the default limits

The normal defaults are 6 candidates per statement and 24 comparison pairs per
ingestion. These documents deliberately contain more statements than that, because
real policies do. Under the defaults the office will report
`policy_comparison_limit` or `policy_retrieval_limited` and will not compare every
pair. The first conflicts are ordered early and are usually covered, but the full
matrix, including all decoys, needs larger limits.

For the complete test, stop the offices, set these in the private root `.env`, and
restart them:

```bash
POLICY_COMPARISON_TOP_K=8
POLICY_COMPARISON_MAX_PAIRS=120
LLM_JOB_MODEL_BUDGET_SECONDS=900
```

Use the `DHAKA_`-prefixed forms if the shared values are intentionally different.
This increases model calls and cost. Do not leave the larger limits on for normal
demo use.

## Expected conflicts

All five should appear as `review` severity. Internal policy/policy and
procedure/procedure pairs become `contradiction`; the policy/procedure pair becomes
`compliance_gap`.

| ID | Pair | Conflict type | Expected finding |
|---|---|---|---|
| `travel_claim_deadline` | Handbook 3.1 vs 3.2 | Deadline versus permission | `contradiction` |
| `annual_leave_entitlement` | Handbook 4.1 vs 4.2 | Numeric entitlement | `contradiction` |
| `personal_email_customer_data` | Procedure 3.1 vs 3.2 | Prohibition versus permission | `contradiction` |
| `purchase_approval_threshold` | Procedure 4.1 vs 4.2 | Approval threshold | `contradiction` |
| `cross_document_airfare_class` | Handbook 3.4 vs Procedure 2.1 | Policy versus procedure | `compliance_gap` |

The concrete conflicts:

- A claim submitted on day 45 is allowed by the 60-day permission and forbidden by
  the 30-day requirement.
- A full-time employee cannot be entitled to 25 leave days and capped at 20.
- The procedure both prohibits customer data in personal email and permits it while
  working remotely.
- A EUR 1,500 purchase is above the EUR 500 approval threshold but inside the
  EUR 2,000 no-approval allowance.
- The handbook makes premium cabins non-reimbursable; the procedure allows premium
  economy at company expense for every business flight.

## Expected review, not a confirmed conflict

| ID | Pair | Expected result |
|---|---|---|
| `appendix_c_exception` | Procedure 4.4 vs 4.5 | `needs_review`, reason `insufficient_context` |

Appendix C is referenced but not supplied. The comparison must not claim that the
exception resolves the EUR 50,000 rule. A reviewer needs the missing schedule.

## Decoys that must **not** become conflicts

These pairs are deliberately compatible or non-overlapping. A conflict finding on
any of them is a false positive worth investigating.

| ID | Pair | Why it is compatible |
|---|---|---|
| `overseas_deadline_exception` | Handbook 3.1 vs 3.3 | The 60-day overseas deadline is an explicit exception to the 30-day general rule |
| `password_minimums` | Procedure 3.3 vs 3.4 | 12 characters for all accounts and 16 for administrative accounts can both hold |
| `secure_transfer_portal` | Procedure 3.2 vs 3.5 | Approved vendors on a controlled portal are a different channel from personal email |
| `warehouse_dress` | Handbook 5.1 vs 5.2 | Warehouse safety clothing and office dress code apply to different roles and locations |

Other comparisons should resolve to `consistent`, `unrelated` or `not_comparable`;
those results are intentionally not persisted as findings.

## Non-policy corporate content in the PDFs

The handbook includes a COO message, company overview and org chart, controlled-copy
note, travel desk service standards, office directory, people metrics, glossary, FAQ
and document history. The procedure includes purpose and scope, a procurement spend
dashboard, a risk register excerpt, Security Steering Committee minutes, a glossary,
document history and contacts.

Some factual assertions may be extracted as `assertion` statements. That is allowed:
the test is that facts, questions, tables, minutes and glossary entries do not become
false conflict findings. Questions and meeting actions must not be treated as rules.

## Check in the browser

1. Upload the handbook, then the procedure, with the settings above.
2. Wait for both processing jobs to finish. Inspect any review reasons; a coverage
   limit is not a finding.
3. Open **Findings** and filter/select the `review` severity general-policy items.
4. For each expected conflict, open **View original**, confirm both cited pages and
   the exact quotations, and check that the concrete conflict exists.
5. Confirm none of the four decoys appears as a semantic conflict.
6. Confirm `appendix_c_exception` is `needs_review`, not a confirmed conflict.
7. If the office reports `policy_comparison_limit`, raise the limits and use
   **Retry comparisons** on the source rather than re-uploading it.

## Automated live check

The checker uses the real pipeline in an isolated temporary office. It never touches
the normal demo database, sources or fixture cache, but it **does make paid model
calls**.

```bash
.venv/bin/python scripts/check_conflict_test_docs.py --allow-paid-live
```

Add `--strict` to exit non-zero when a conflict is missing, a decoy is flagged, or
an unexpected conflict appears. The script prints a summary and writes
`evidence/conflict_test_report.json` with the accepted claims, all findings and the
per-expectation result.

Useful options:

```bash
--top-k 8          # candidates per statement
--max-pairs 120    # comparison pairs per ingestion
--budget 900       # model seconds per ingestion
--output PATH      # report location
```

The defaults above favour coverage over cost. Lower them only if you accept
incomplete comparison coverage.

## Regenerate the PDFs

The PDFs and expectations are generated by one script, so a text edit cannot leave a
stale PDF behind:

```bash
.venv/bin/python scripts/make_conflict_test_docs.py
```

The generator asserts that each PDF has exactly two pages and that every policy
statement survives the real PDF parser verbatim.

## Caveats

- Model-assisted comparisons are non-deterministic across models and runs. A missed
  pair is a reason to inspect retrieval, context, prompt, limits and budget, not
  proof that the policy engine is broken.
- The test expects a text-based PDF. Scans and image-only documents still need OCR.
- The documents are synthetic. Names, addresses, email domains and figures are
  fictional.
- The procedure says it supports group policies. This is realistic context, not an
  explicit replacement or precedence rule; the cross-document conflict remains a
  candidate for review.
