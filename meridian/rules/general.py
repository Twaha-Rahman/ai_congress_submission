"""Retrieved, evidence-grounded semantic comparisons for office-local policies.

No model calls happen in a database write transaction. The backend rechecks scope,
currentness and explicit replacement after publication, and never treats a model's
semantic judgment as a verified, deterministic contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import math
import re
import time
from typing import Sequence

from ..contracts.claims import ClaimRevision
from ..contracts.common import (
    Authority, ExplanationCode, FindingType, Mode, Severity, SourceType, Subject,
)
from ..contracts.extraction import PolicyComparisonProposal
from ..contracts.findings import ComparisonResult, FindingRecord
from ..contracts.manifest import SourceManifest
from ..extraction.policy import POLICY_COMPARISON_VERSION
from ..extraction.provider import ClauseInput, ExtractionRequest, ProviderResult
from ..extraction.service import ModelStageService
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..rules.compare import ClaimView, compare_claims
from ..storage.store import ClauseRow, OfficeStore

_STOP = set("a an the is are be been was were to of for in on at by and or with must may shall should can not no only all".split())


def _tokens(text: str) -> set[str]:
    # Unicode words plus light inflection folding; no outside embedding service.
    words = re.findall(r"[^\W_]+", text.casefold())
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w
            for w in words if len(w) > 1 and w not in _STOP}


def rank_candidates(left: ClaimView, candidates: Sequence[ClaimView]) -> list[ClaimView]:
    """Lexical relevance with family boost; never require family equality.

    A few zero-overlap candidates remain eligible so small demo corpora can still
    compare paraphrases. Larger corpora need retrieval-recall evaluation.
    """
    query = _tokens(left.revision.evidence.quote)
    documents = [_tokens(v.revision.evidence.quote) for v in candidates]
    frequencies = {t: sum(t in d for d in documents) for t in query}
    scored = []
    for view, document in zip(candidates, documents):
        score = sum(math.log(1 + (len(documents) + 1) / (1 + frequencies[t]))
                    for t in query & document) / math.sqrt(max(1, len(document)))
        score += 0.25 * (view.revision.policy_family == left.revision.policy_family)
        scored.append((score, view))
    return [v for _, v in sorted(scored, key=lambda item: (-item[0], item[1].revision_id))]


def rank_pairs(
    pairs: dict[tuple[str, str], tuple[ClaimView, ClaimView]],
    views: Sequence[ClaimView],
) -> list[tuple[tuple[str, str], tuple[ClaimView, ClaimView]]]:
    """Spend the source-wide call budget on relevant pairs, independent of order.

    Per-statement retrieval alone is insufficient: taking its union in insertion
    order lets introductory material exhaust the budget. Use symmetric TF-IDF
    cosine relevance over the full corpus before applying the global pair cap.
    This is retrieval priority only, never a consistency or conflict judgment.
    """
    documents = {v.revision_id: _tokens(v.revision.evidence.quote) for v in views}
    frequencies: dict[str, int] = {}
    for document in documents.values():
        for token in document:
            frequencies[token] = frequencies.get(token, 0) + 1
    weights = {t: (1 + math.log((1 + len(documents)) / (1 + count))) ** 2
               for t, count in frequencies.items()}
    norms = {key: math.sqrt(sum(weights[t] for t in tokens))
             for key, tokens in documents.items()}

    def score(item):
        key, (left, right) = item
        a, b = documents[left.revision_id], documents[right.revision_id]
        overlap = sum(weights[t] for t in a & b)
        relevance = overlap / max(1, norms[left.revision_id] * norms[right.revision_id])
        return (-relevance, key)

    return sorted(pairs.items(), key=score)


def _gate(left: ClaimView, right: ClaimView) -> ComparisonResult:
    from .publish import _explicit_supersession

    result = compare_claims(left, right, explicit_supersession=_explicit_supersession(left, right))
    if result.finding_type in {FindingType.NOT_COMPARABLE, FindingType.SUPERSESSION}:
        return result
    if not left.is_current or not right.is_current:
        return result.model_copy(update={
            "finding_type": FindingType.NOT_COMPARABLE,
            "severity": Severity.INFO,
            "explanation_code": ExplanationCode.REVISION_NOT_CURRENT,
        })
    return result


def _metadata(view: ClaimView) -> dict:
    r = view.revision
    return {
        "revision_id": r.revision_id,
        "source_identity": r.source_identity, "version": r.source_version_label,
        "authority": r.authority.value, "policy_family": r.policy_family,
        "scope": r.scope.model_dump(mode="json"),
        "valid_from": r.valid_from, "valid_to": r.valid_to,
        "rule": r.rule.model_dump(mode="json"),
    }


def comparison_request(
    left: ClaimView, right: ClaimView, *, store: OfficeStore,
    manifest: SourceManifest, new_clauses: Sequence[ClauseRow], mode: Mode,
    request_id: str,
) -> ExtractionRequest | None:
    """Bind both primary quotes and full source context to permission/cache identity.

    Source-level context preserves exceptions in other clauses. Oversized documents
    are sent to review rather than silently chopping off a possible exception.
    Slack messages carry no implied thread reconstruction.
    """
    metadata = {"left": _metadata(left), "right": _metadata(right)}
    clauses = [
        ClauseInput("left_primary", left.revision.evidence.page, None, left.revision.evidence.quote),
        ClauseInput("right_primary", right.revision.evidence.page, None, right.revision.evidence.quote),
    ]
    hosted_allowed = True
    seen_sources: set[str] = set()
    for side, view in (("left", left), ("right", right)):
        r = view.revision
        source = store.get_source(r.source_id)
        if source is None:
            # Only the currently staged source may be absent from the store.
            if r.source_identity != manifest.source_identity or r.source_version_label != manifest.version_label:
                return None
            context = list(new_clauses)
            permission = manifest.permissions.hosted_model
            source_type = manifest.source_type.value
            declared_conditions = manifest.declared_conditions
        else:
            context = store.clauses_for_source(r.source_id)
            permission = source.hosted_model
            source_type = source.source_type
            declared_conditions = source.manifest.declared_conditions
        hosted_allowed = hosted_allowed and permission
        metadata[side]["source_type"] = source_type
        metadata[side]["hosted_model_allowed"] = permission
        metadata[side]["declared_conditions"] = declared_conditions
        if r.source_id in seen_sources:
            continue
        seen_sources.add(r.source_id)
        if not any(c.clause_id == r.source_clause_id and
                   c.text[r.evidence.start_char:r.evidence.end_char] == r.evidence.quote
                   for c in context):
            return None
        clauses.extend(ClauseInput(f"{side}_context:{c.clause_id}", c.page, c.section, c.text)
                       for c in context)
    if sum(len(c.text) for c in clauses) > 60000:
        return None
    identity = sha256_hex(canonical_json_bytes({
        "metadata": metadata, "context": [c.__dict__ for c in clauses],
        "prompt": POLICY_COMPARISON_VERSION,
    }))
    return ExtractionRequest(
        tenant_id=store.tenant_id, region=store.region,
        source_identity=f"pair_{identity}", version_label="v1", source_type=SourceType.PDF,
        subject=Subject.GENERAL_POLICY, authority=f"{left.revision.authority.value}/{right.revision.authority.value}",
        content_sha256=identity, manifest_scope_summary=canonical_json_bytes(metadata).decode(),
        clauses=clauses, mode=mode, prompt_version=POLICY_COMPARISON_VERSION,
        schema_version="general-comparison-v1", request_id=request_id,
        hosted_model_allowed=hosted_allowed,
    )


def classify_policy(left: ClaimView, right: ClaimView, result: ProviderResult) -> ComparisonResult:
    """Check model evidence, then assign conservative backend-owned classification."""
    base = _gate(left, right)
    if base.finding_type in {FindingType.NOT_COMPARABLE, FindingType.SUPERSESSION}:
        return base
    detail = {
        "assessment": "model_assisted", "requires_human_review": "true",
        "model": result.model or "", "mode": result.mode.value,
        "comparison_prompt_version": POLICY_COMPARISON_VERSION,
        "comparison_output_sha256": result.raw_output_sha256 or "",
    }
    proposal = result.proposal
    if not result.ok or not isinstance(proposal, PolicyComparisonProposal):
        detail.update(reason="policy_comparison_failed", explanation=(
            "The statements could not be assessed. Inspect their evidence; no consistency conclusion was reached."
        ), error_code=result.error_code.value if result.error_code else "schema_violation")
    elif (proposal.left_quote != left.revision.evidence.quote
          or proposal.right_quote != right.revision.evidence.quote):
        detail.update(reason="comparison_evidence_mismatch", explanation=(
            "The model did not return the exact primary evidence; its assessment was withheld."
        ))
    else:
        detail.update(explanation=proposal.explanation, relationship=proposal.relationship)
        complete = (proposal.same_action and proposal.scope_overlap is True
                    and proposal.time_overlap is True and proposal.exceptions_resolved
                    and proposal.evidence_sufficient
                    and left.revision.valid_from is not None and right.revision.valid_from is not None)
        separate = (not proposal.same_action or proposal.scope_overlap is False
                    or proposal.time_overlap is False)
        if ((proposal.relationship == "consistent" and complete)
                or (proposal.relationship in {"consistent", "unrelated"}
                    and separate and proposal.evidence_sufficient)):
            return base.model_copy(update={
                "finding_type": FindingType.NOT_COMPARABLE, "severity": Severity.INFO,
                "detail": detail,
            })
        if proposal.relationship == "conflict" and complete:
            authorities = {left.revision.authority, right.revision.authority}
            if Authority.POLICY in authorities and Authority.INFORMAL in authorities:
                finding_type = FindingType.INCORRECT_GUIDANCE
            elif Authority.POLICY in authorities and Authority.PROCEDURE in authorities:
                finding_type = FindingType.COMPLIANCE_GAP
            else:
                finding_type = FindingType.CONTRADICTION
            # A model judgment is a likely conflict, never a deterministic alert.
            return base.model_copy(update={
                "finding_type": finding_type, "severity": Severity.REVIEW,
                "explanation_code": ExplanationCode.SEMANTIC_CONFLICT,
                "authority_basis": f"{left.revision.authority.value}/{right.revision.authority.value}",
                "detail": detail, "alert": False,
            })
        detail["reason"] = "insufficient_context"
    return base.model_copy(update={"detail": detail, "alert": False})


@dataclass
class PolicyBatch:
    comparisons: dict[tuple[str, str], ComparisonResult] = field(default_factory=dict)
    calls: list[tuple[ExtractionRequest, ProviderResult]] = field(default_factory=list)
    reviews: list[tuple[str, str]] = field(default_factory=list)


def prepare_policy_comparisons(
    store: OfficeStore, *, new_revisions: Sequence[ClaimRevision],
    new_clauses: Sequence[ClauseRow], manifest: SourceManifest,
    service: ModelStageService, mode: Mode, request_id: str, recheck: bool = False,
) -> PolicyBatch:
    batch = PolicyBatch()
    new_views = [ClaimView(r) for r in new_revisions if r.subject is Subject.GENERAL_POLICY]
    if not new_views:
        return batch
    existing = store.claim_views(subject=Subject.GENERAL_POLICY.value, include_remote=False, limit=None)
    views = [v for v in existing if v.is_current and not v.carried_forward] + new_views
    views = list({v.revision_id: v for v in views}.values())
    if manifest.source_type is SourceType.SLACK and not any(
        v.revision.authority is Authority.POLICY for v in views
    ):
        batch.reviews.append(("policy_reference_missing", "No accepted general policy is available to check this message against."))
    existing_pairs = {
        tuple(sorted(record.payload.claim_revision_ids))
        for record in store.list_findings(limit=100000)
        if record.payload.subject is Subject.GENERAL_POLICY
    }
    pairs: dict[tuple[str, str], tuple[ClaimView, ClaimView]] = {}
    for left in new_views:
        candidates = [v for v in views if v.revision.claim_id != left.revision.claim_id
                      and _gate(left, v).finding_type is not FindingType.NOT_COMPARABLE]
        ranked = rank_candidates(left, candidates)
        if len(ranked) > service.settings.policy_comparison_top_k:
            batch.reviews.append(("policy_retrieval_limited", "Only the most relevant candidate statements were compared; coverage is incomplete."))
        for right in ranked[:service.settings.policy_comparison_top_k]:
            a, b = sorted([left, right], key=lambda v: v.revision_id)
            key = (a.revision_id, b.revision_id)
            if recheck or key not in existing_pairs:
                pairs[key] = (a, b)
    if len(pairs) > service.settings.policy_comparison_max_pairs:
        batch.reviews.append(("policy_comparison_limit", "The source exceeded the comparison-pair limit; coverage is incomplete."))
    selected = rank_pairs(pairs, views)[:service.settings.policy_comparison_max_pairs]
    service.report_progress("comparison", completed=0, total=len(selected))
    deadline = time.monotonic() + service.settings.llm_job_model_budget_seconds
    for key, (left, right) in selected:
        request = comparison_request(left, right, store=store, manifest=manifest,
                                     new_clauses=new_clauses, mode=mode, request_id=request_id)
        if request is None:
            batch.reviews.append(("policy_context_unavailable", "Evidence or complete source context was unavailable or exceeded the context limit."))
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            batch.reviews.append(("policy_comparison_budget", "The comparison time budget was exhausted; coverage is incomplete."))
            break
        result = service.compare_policy(replace(request, model_budget_seconds=remaining))
        batch.calls.append((request, result))
        service.report_progress("comparison", completed=len(batch.calls), total=len(selected))
        comparison = classify_policy(left, right, result)
        batch.comparisons[key] = comparison
        if comparison.finding_type is FindingType.NEEDS_REVIEW:
            batch.reviews.append((comparison.detail.get("reason", "insufficient_context"), comparison.detail.get("explanation", "Policy comparison needs review.")))
    # Dedupe job-level coverage reasons without hiding individual comparison calls.
    batch.reviews = list(dict.fromkeys(batch.reviews))
    return batch


def publish_policy_batch(connection, store, batch, *, signer, now, recheck=False) -> list[str]:
    from .publish import publish_comparison, finding_key

    views = {v.revision_id: v for v in store.claim_views(
        subject=Subject.GENERAL_POLICY.value, limit=None, connection=connection,
    )}
    keys = store.finding_keys(connection=connection)
    published = []
    for (a, b), comparison in batch.comparisons.items():
        if a not in views or b not in views:
            continue
        gate = _gate(views[a], views[b])
        if gate.finding_type in {FindingType.NOT_COMPARABLE, FindingType.SUPERSESSION}:
            comparison = gate
        if recheck:
            current_key = finding_key(comparison.finding_type, a, b)
            for old in store.list_findings(connection=connection, limit=100000):
                if (set(old.payload.claim_revision_ids) == {a, b}
                        and old.payload.finding_key != current_key
                        and old.payload.detail.get("assessment") != "historical"):
                    retire_policy_assessment(connection, store, old, signer=signer, now=now,
                        explanation="A newer comparison supersedes this assessment. Inspect the latest findings and job result.")
        snapshot = publish_comparison(connection, store, comparison, signer=signer,
                                      now=now, existing_keys=keys, force_snapshot=recheck)
        if snapshot:
            published.append(comparison.finding_type.value)
    return published


def retire_policy_assessment(connection, store, record: FindingRecord, *, signer, now, explanation=None):
    """Invalidate an old assessment without deleting its evidence or reviewer audit."""
    from .publish import publish_comparison

    p = record.payload
    result = ComparisonResult(
        finding_type=p.finding_type, severity=Severity.INFO,
        explanation_code=ExplanationCode.REVISION_NOT_CURRENT,
        left_revision_id=p.claim_revision_ids[0], right_revision_id=p.claim_revision_ids[1],
        subject=p.subject, affected_scope=p.affected_scope,
        affected_valid_interval=p.affected_valid_interval, authority_basis=p.authority_basis,
        detail={**p.detail, "assessment": "historical", "explanation": explanation or (
            "A cited policy revision has been replaced. This assessment is historical; inspect the replacement policy."
        )}, alert=False,
    )
    publish_comparison(connection, store, result, signer=signer, now=now,
                       existing_keys=store.finding_keys(connection=connection), force_snapshot=True)


def recompare_policy_source(store, source_id, *, service, signer, mode, request_id):
    """Explicit recovery after provider failure, without re-uploading immutable data."""
    from ..ingestion.pipeline import IngestionOutcome
    from ..contracts.common import ErrorCode, utc_now
    from ..storage.store import new_id

    source = store.get_source(source_id)
    if source is None or source.subject != Subject.GENERAL_POLICY.value:
        return IngestionOutcome(error_code=ErrorCode.INVALID_INPUT.value,
                                error_detail="comparison retry requires an existing general-policy source")
    current = [v.revision for v in store.claim_views(subject=Subject.GENERAL_POLICY.value, limit=None)
               if v.revision.source_id == source_id and v.is_current and not v.carried_forward]
    batch = prepare_policy_comparisons(store, new_revisions=current,
        new_clauses=store.clauses_for_source(source_id), manifest=source.manifest,
        service=service, mode=mode, request_id=request_id, recheck=True)
    if not current:
        batch.reviews.append(("policy_no_current_claims", "This source has no current accepted statements to compare."))
    service.report_progress("publication")
    now = utc_now()
    with store.db.transaction() as connection:
        findings = publish_policy_batch(connection, store, batch, signer=signer, now=now, recheck=True)
        for code, detail in batch.reviews:
            store.insert_claim_review(connection=connection, source_id=source_id,
                reason_code=code, detail={"detail": detail}, subject=source.subject, created_at=now)
        for request, result in batch.calls:
            store.record_model_call(connection, call_id=new_id("call"), job_id=None,
                source_id=source_id, mode=result.mode.value, provider=result.provider,
                route=result.route, model=result.model, prompt_version=request.prompt_version,
                schema_version=request.schema_version, attempts=result.attempts,
                latency_ms=result.latency_ms, usage=result.usage,
                status="succeeded" if result.ok else "failed",
                error_code=result.error_code.value if result.error_code else None,
                cache_key=result.cache_key, raw_output_sha256=result.raw_output_sha256)
    return IngestionOutcome(source_id=source_id, claim_revision_ids=[r.revision_id for r in current],
        finding_types=findings, review_reasons=[code for code, _ in batch.reviews],
        stage_modes={"policy_comparison": mode.value})
