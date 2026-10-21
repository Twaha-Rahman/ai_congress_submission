"""Deterministic query answering over an authorised knowledge snapshot.

The engine computes supported numeric answers itself (allowed-set intersection over
applicable claims), binds citations to the exact evidence, and abstains or asks for
review instead of inventing an answer.  Optional model phrasing never changes the
computed result: a phrasing that loses the numbers or the authority is discarded and
flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..contracts.common import (
    ANSWER_TEMPLATE_VERSION,
    AnswerStatus,
    Authority,
    ClaimOrigin,
    ErrorCode,
    FindingType,
    LoanType,
    Mode,
    QueryWarningCode,
    RuleKind,
    Severity,
    Subject,
    TimeInterval,
    canonical_datetime,
    utc_now,
)
from ..contracts.findings import ComparisonResult
from ..contracts.qa import (
    AnswerPayload,
    AnswerRecord,
    AnswerWarning,
    Citation,
    GoverningFact,
    QueryRequest,
    TargetFacts,
)
from ..integrity.bundles import claim_hash
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..integrity.signing import Signer
from ..rules.compare import ClaimView, aggregate_requirements
from ..rules.intervals import (
    format_amount_minor,
    format_time_interval,
    scope_matches_target,
)
from ..rules.publish import compare_pair, finding_id_for, finding_key
from ..rules.values import (
    REQUIREMENT_KINDS,
    constraint_for,
    contains,
    describe,
    describe_violation,
    domain_for,
    intersect,
    witness_value,
)
from ..storage.store import OfficeStore, new_id
from ..temporal.snapshots import select_snapshot

AUTHORITATIVE = {Authority.POLICY, Authority.PROCEDURE}


def _approval_phrase(value: int) -> str:
    noun = "approval" if value == 1 else "approvals"
    return f"{value} {noun} are" if value != 1 else f"{value} {noun} is"


@dataclass
class AnswerDraft:
    status: AnswerStatus
    statements: list[tuple[str, str, list[str]]] = field(default_factory=list)
    governing_facts: list[GoverningFact] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    warnings: list[AnswerWarning] = field(default_factory=list)
    partial_reasons: list[str] = field(default_factory=list)
    modes: dict[str, Mode] = field(default_factory=dict)
    model_metadata: dict[str, str] = field(default_factory=dict)

    def text(self) -> str:
        return " ".join(text for _sid, text, _cites in self.statements).strip()


class QueryEngine:
    """Authorised retrieval plus deterministic computation for one office."""

    def __init__(self, *, store: OfficeStore, signer: Signer, extra_modes: dict[str, str] | None = None) -> None:
        self.store = store
        self.signer = signer
        self.extra_modes = extra_modes or {}

    # ------------------------------------------------------------------- helpers
    def _citation(self, view: ClaimView, *, statement_id: str, quote: bool = True) -> Citation:
        revision = view.revision
        record = self.store.get_claim(revision.revision_id)
        remote = revision.origin is ClaimOrigin.REMOTE
        payload_hash = (
            record.payload_hash
            if record
            else (view.payload_hash or claim_hash(revision))
        )
        source = self.store.get_source(revision.source_id)
        restricted = bool(source and source.restricted)
        return Citation(
            statement_id=statement_id,
            claim_revision_id=revision.revision_id,
            claim_id=revision.claim_id,
            source_id=revision.source_id,
            source_identity=revision.source_identity,
            source_version_label=revision.source_version_label,
            clause_id=revision.evidence.clause_id,
            manifest_root=revision.evidence.manifest_root,
            claim_payload_hash=payload_hash,
            authority=revision.authority.value,
            page=revision.evidence.page,
            section=revision.evidence.section,
            quote=revision.evidence.quote if (quote and not remote) else None,
            start_char=revision.evidence.start_char,
            end_char=revision.evidence.end_char,
            restricted=restricted,
            remote=remote,
        )

    def _is_restricted(self, view: ClaimView) -> bool:
        source = self.store.get_source(view.revision.source_id)
        return bool(source and source.restricted)

    def _governing_fact(self, view: ClaimView) -> GoverningFact:
        revision = view.revision
        return GoverningFact(
            claim_revision_id=revision.revision_id,
            claim_id=revision.claim_id,
            authority=revision.authority.value,
            policy_family=revision.policy_family,
            rule_summary=describe(constraint_for(revision.rule), revision.rule.unit),
            scope_summary=revision.scope.model_dump_json(),
            valid_interval=TimeInterval(start=revision.valid_from, end=revision.valid_to),
        )

    # -------------------------------------------------------------------- public
    def answer(
        self,
        request: QueryRequest,
        *,
        known_at: datetime | None = None,
        region: str | None = None,
        allowed_restricted: bool = True,
    ) -> AnswerRecord:
        if request.target.subject is Subject.GENERAL_POLICY:
            raise ValueError("general source questions require GeneralQuestionEngine")
        moment = known_at or request.known_at or utc_now()
        views = self.store.claim_views(subject=request.target.subject.value)
        remote_snapshot_available = False
        if request.target.subject is Subject.RECORD_RETENTION:
            # Imported remote claims (signed exports stored in a separate provenance
            # namespace) participate in local comparison without fabricating clause text.
            # Only the exact latest snapshot for the requested knowledge moment is
            # eligible; stale history never leaks into a current comparison.
            from ..federation.exchange import (
                remote_claim_views,
                select_remote_snapshots,
                target_fingerprint_for_facts,
            )

            local_ids = {view.revision.revision_id for view in views}
            remote_context = {
                "subject": request.target.subject.value,
                "known_at": moment,
                "snapshot_ids": request.remote_snapshot_ids or None,
                "target_fingerprint_value": target_fingerprint_for_facts(request.target),
                "valid_at": request.valid_at,
                "source_known_at": request.remote_source_known_at,
            }
            selected_snapshots = select_remote_snapshots(
                store=self.store,
                **remote_context,
            )
            remote_snapshot_available = bool(selected_snapshots)
            views = list(views) + [
                view
                for view in remote_claim_views(
                    store=self.store,
                    **remote_context,
                )
                if view.revision.revision_id not in local_ids
            ]
        if not allowed_restricted:
            # Restricted evidence is excluded before comparison, so neither its values
            # nor its existence affects the answer or citation list.
            views = [view for view in views if not self._is_restricted(view)]
        snapshot = select_snapshot(
            views, valid_at=request.valid_at, known_at=moment, subject=request.target.subject
        )
        applicable = [
            view for view in snapshot if scope_matches_target(view.revision.scope, request.target)
        ]
        draft = AnswerDraft(
            status=AnswerStatus.ABSTAINED,
            modes={
                "retrieval": Mode.REPLAY,
                "phrasing": Mode.REPLAY,
                **self.extra_modes,  # type: ignore[arg-type]
            },
        )
        if request.target.subject is Subject.LOAN_APPROVAL:
            self._answer_loan_approval(request, draft, applicable, views, moment)
        else:
            self._answer_record_retention(request, draft, applicable, views, moment)

        if request.remote_snapshot_required and not remote_snapshot_available:
            draft.statements.insert(
                0,
                (
                    "S0",
                    "A matching remote export snapshot was not available to the requesting "
                    "office by the requested knowledge time; this result is incomplete and "
                    "must not be treated as a complete cross-office comparison.",
                    [],
                ),
            )
            draft.warnings.append(
                AnswerWarning(
                    code=QueryWarningCode.REVIEW_REQUIRED,
                    message=(
                        "no complete remote snapshot matching this target and source-time "
                        "context had been received by the requested known_at"
                    ),
                )
            )
            draft.status = AnswerStatus.NEEDS_REVIEW

        # A declared replacement whose extracted rules did not validate leaves the
        # old policy current for safety, but it must never be presented as definitely
        # current.  The pending marker is visible as a specific review result.
        applicable_ids = {view.revision.revision_id for view in applicable}
        pending = []
        for item in self.store.pending_replacements(
            subject=request.target.subject.value, known_at=moment
        ):
            detail = item.get("detail") or {}
            effective_from = detail.get("effective_from")
            if effective_from:
                try:
                    effective_moment = datetime.fromisoformat(
                        str(effective_from).replace("Z", "+00:00")
                    )
                except ValueError:
                    # Malformed pending metadata is not actionable query state.
                    continue
                if request.valid_at < effective_moment:
                    continue
            source = self.store.get_source(str(item.get("source_id", "")))
            if source is None or (source.restricted and not allowed_restricted):
                continue
            if applicable_ids.intersection(
                str(rev) for rev in detail.get("affected_revision_ids", [])
            ):
                pending.append(item)
        if pending:
            affected = sorted(
                {
                    str(rev)
                    for item in pending
                    for rev in (item.get("detail") or {}).get("affected_revision_ids", [])
                }
            )
            draft.statements.insert(
                0,
                (
                    "S0",
                    "A replacement policy change affecting this target is pending validation; "
                    "the rule stated below is the most recent validated rule and must not be "
                    "treated as definitely current until the replacement is reviewed.",
                    [],
                ),
            )
            draft.warnings.append(
                AnswerWarning(
                    code=QueryWarningCode.PENDING_REPLACEMENT,
                    message=(
                        "a declared replacement produced no validated rules (or incomplete "
                        "coverage); the prior validated policy remains current pending review"
                    ),
                    claim_revision_ids=affected,
                )
            )
            if draft.status is not AnswerStatus.NEEDS_REVIEW:
                draft.status = AnswerStatus.NEEDS_REVIEW

        return self.save_answer(request, draft, moment=moment, region=region)

    def save_answer(self, request: QueryRequest, draft: AnswerDraft, *, moment: datetime, region: str | None = None) -> AnswerRecord:
        """Sign and persist answers from numeric computation or grounded source Q&A."""
        answer_id = new_id("ans")
        text = draft.text()
        region_value = region or self.store.region
        payload = AnswerPayload(
            tenant_id=self.store.tenant_id,
            region=region_value,  # type: ignore[arg-type]
            answer_id=answer_id,
            status=draft.status,
            question=request.question,
            query_hash=sha256_hex(canonical_json_bytes(request)),
            answer_text=text,
            answer_text_hash=sha256_hex(text.encode("utf-8")),
            target=request.target,
            valid_at=request.valid_at,
            known_at=moment,
            governing_facts=draft.governing_facts,
            citations=draft.citations,
            warnings=draft.warnings,
            modes=draft.modes,
            template_version=ANSWER_TEMPLATE_VERSION,
            signer_key_id=self.signer.key_id,
            model_metadata=draft.model_metadata,
            cited_claim_payload_hashes=sorted({c.claim_payload_hash for c in draft.citations if c.claim_payload_hash}),
            cited_manifest_roots=sorted({c.manifest_root for c in draft.citations}),
            partial_reasons=draft.partial_reasons,
            created_at=utc_now(),
        )
        payload_bytes = canonical_json_bytes(payload)
        record = AnswerRecord(
            payload=payload,
            payload_hash=sha256_hex(payload_bytes),
            signature=self.signer.sign(payload_bytes),
            key_id=self.signer.key_id,
            answer_text_hash=payload.answer_text_hash,
        )
        with self.store.db.transaction() as connection:
            self.store.insert_answer(connection, record)
            self.store.upsert_node(
                connection,
                node_id=f"answer:{answer_id}",
                node_type="answer",
                label=f"{draft.status.value} answer",
                attributes={
                    "payload_hash": record.payload_hash,
                    "valid_at": canonical_datetime(request.valid_at),
                    "known_at": canonical_datetime(moment),
                },
            )
            for citation in draft.citations:
                self.store.upsert_edge(
                    connection,
                    edge_type="CITES",
                    from_node_id=f"answer:{answer_id}",
                    to_node_id=(f"revision:{citation.claim_revision_id}" if citation.claim_revision_id else f"clause:{citation.clause_id}"),
                    attributes={"statement_id": citation.statement_id},
                )
        return record

    # ------------------------------------------------------------------ subjects
    def _answer_loan_approval(
        self,
        request: QueryRequest,
        draft: AnswerDraft,
        applicable: list[ClaimView],
        views: list[ClaimView],
        known_at: datetime,
    ) -> None:
        target = request.target
        requirements = [
            view
            for view in applicable
            if view.revision.rule.kind in REQUIREMENT_KINDS
            and view.revision.authority in AUTHORITATIVE
        ]
        advice = [
            view
            for view in applicable
            if view.revision.rule.kind is RuleKind.ADVISED_SUFFICIENT
        ]
        if not requirements:
            draft.status = AnswerStatus.ABSTAINED
            draft.warnings.append(
                AnswerWarning(
                    code=QueryWarningCode.REVIEW_REQUIRED,
                    message=(
                        "no authoritative approval requirement applies to these target facts at "
                        "the requested valid_at/known_at"
                    ),
                )
            )
            if advice:
                draft.warnings.append(
                    AnswerWarning(
                        code=QueryWarningCode.ONLY_INFORMAL_GUIDANCE,
                        message="only informal guidance applies; it cannot be treated as authority",
                        claim_revision_ids=[view.revision.revision_id for view in advice],
                    )
                )
            return

        unit = requirements[0].revision.rule.unit
        domain = domain_for(unit)
        merged, _ = aggregate_requirements(requirements)
        if merged is None:
            draft.status = AnswerStatus.NEEDS_REVIEW
            draft.statements.append(
                (
                    "S1",
                    "The applicable authoritative requirements are mutually unsatisfiable for "
                    "these target facts; a reviewer must resolve the conflict.",
                    [view.revision.revision_id for view in requirements],
                )
            )
            draft.governing_facts = [self._governing_fact(view) for view in requirements]
            draft.citations = [
                self._citation(view, statement_id="S1") for view in requirements
            ]
            return
        witness = witness_value(merged, domain)
        assert witness is not None

        primary = requirements[0]
        for view in requirements:
            if describe(constraint_for(view.revision.rule), view.revision.rule.unit) == describe(
                merged, view.revision.rule.unit
            ):
                primary = view
                break
        amount_text = format_amount_minor(target.amount_minor or 0)
        loan_type = target.loan_type.value if target.loan_type else "business"
        if merged.lo is not None and merged.hi is None:
            lead = f"At least {_approval_phrase(int(merged.lo))}"
        elif merged.hi is not None and merged.lo is None:
            lead = f"At most {_approval_phrase(int(merged.hi))}"
        elif (
            merged.lo is not None
            and merged.hi is not None
            and merged.lo == merged.hi
            and merged.lo_inclusive
            and merged.hi_inclusive
        ):
            lead = f"Exactly {_approval_phrase(int(merged.lo))}"
        else:
            lead = f"The allowed set is {describe(merged, unit)}; the required number of approvals is"
        statement = (
            f"{lead} required for a {loan_type} loan of "
            f"{amount_text} as of {canonical_datetime(request.valid_at)}: "
            f"{describe(merged, unit)} "
            f"under {primary.revision.policy_family} "
            f"({primary.revision.source_version_label}, {primary.revision.authority.value}, "
            f"clause {primary.revision.evidence.clause_id})."
        )
        cited = sorted({view.revision.revision_id for view in requirements})
        draft.statements.append(("S1", statement, cited))
        draft.governing_facts = [self._governing_fact(view) for view in requirements]
        draft.citations = [self._citation(view, statement_id="S1") for view in requirements]
        draft.status = AnswerStatus.ANSWERED
        if len(requirements) > 1:
            draft.warnings.append(
                AnswerWarning(
                    code=QueryWarningCode.REVIEW_REQUIRED,
                    message=(
                        "more than one authoritative requirement applies; the reported value is "
                        "the intersection of their allowed sets"
                    ),
                    claim_revision_ids=cited,
                )
            )

        # ------------------------------------------------- guidance vs requirement
        guidance_findings: list[ComparisonResult] = []
        for advice_view in advice:
            for requirement in requirements:
                result = compare_pair(requirement, advice_view, views)
                if result.finding_type in {
                    FindingType.STALE_GUIDANCE,
                    FindingType.INCORRECT_GUIDANCE,
                }:
                    guidance_findings.append(result)
        if guidance_findings:
            codes = []
            for result in guidance_findings:
                advice_view = next(
                    view
                    for view in views
                    if view.revision.revision_id
                    in {result.left_revision_id, result.right_revision_id}
                    and view.revision.rule.kind is RuleKind.ADVISED_SUFFICIENT
                )
                advised = advice_view.revision.rule.value
                published = (
                    canonical_datetime(advice_view.revision.valid_from)
                    if advice_view.revision.valid_from
                    else "an earlier date"
                )
                sentence = (
                    f"The guidance published {published} says {advised} approval is sufficient; "
                    "following it would violate the current requirement."
                )
                statement_id = f"S{len(draft.statements) + 1}"
                draft.statements.append((statement_id, sentence, [advice_view.revision.revision_id]))
                draft.citations.append(self._citation(advice_view, statement_id=statement_id))
                key = finding_key(
                    result.finding_type, result.left_revision_id, result.right_revision_id
                )
                draft.warnings.append(
                    AnswerWarning(
                        code=QueryWarningCode.STALE_GUIDANCE,
                        message=(
                            f"{result.finding_type.value}: "
                            f"{result.detail.get('required', 'requirement')} overrides the advised "
                            f"value {advised}"
                        ),
                        claim_revision_ids=list(result.claim_revision_ids()),
                        finding_ids=[finding_id_for(key)],
                    )
                )
                codes.append(result.finding_type.value)
            draft.modes["guidance_check"] = Mode.REPLAY
        return

    def _answer_record_retention(
        self,
        request: QueryRequest,
        draft: AnswerDraft,
        applicable: list[ClaimView],
        views: list[ClaimView],
        known_at: datetime,
    ) -> None:
        requirements = [
            view
            for view in applicable
            if view.revision.rule.kind in REQUIREMENT_KINDS
            and view.revision.authority in AUTHORITATIVE
        ]
        procedures = [
            view
            for view in applicable
            if view.revision.rule.kind is RuleKind.OPERATING_EXACT
        ]
        if not requirements:
            draft.status = AnswerStatus.ABSTAINED
            draft.warnings.append(
                AnswerWarning(
                    code=QueryWarningCode.REVIEW_REQUIRED,
                    message="no authoritative retention requirement applies to these target facts",
                )
            )
            return

        unit = requirements[0].revision.rule.unit
        domain = domain_for(unit)
        merged, _ = aggregate_requirements(requirements)
        requirement_ids = [item.revision.revision_id for item in requirements]
        procedure_ids = [item.revision.revision_id for item in procedures]
        if merged is None:
            conflict_ids = requirement_ids + procedure_ids
            draft.status = AnswerStatus.NEEDS_REVIEW
            draft.statements.append(
                (
                    "S1",
                    "The applicable authoritative retention requirements are mutually "
                    "unsatisfiable for these target facts; a reviewer must resolve the conflict.",
                    conflict_ids,
                )
            )
            all_applicable = requirements + procedures
            draft.governing_facts = [self._governing_fact(item) for item in all_applicable]
            draft.citations = [
                self._citation(item, statement_id="S1") for item in all_applicable
            ]
            return

        starting = (
            request.target.starting_event.value
            if request.target.starting_event
            else "the starting event"
        )
        families = sorted({item.revision.policy_family for item in requirements})
        drafts = [
            f"{item.revision.source_version_label} "
            f"({item.revision.authority.value}, clause {item.revision.evidence.clause_id})"
            for item in requirements
        ]
        draft.statements.append(
            (
                "S1",
                f"The applicable retention requirement is {describe(merged, unit)} from "
                f"{starting} under {', '.join(families)} ({'; '.join(drafts)}).",
                requirement_ids,
            )
        )
        draft.governing_facts = [self._governing_fact(item) for item in requirements]
        draft.citations = [self._citation(item, statement_id="S1") for item in requirements]

        if not procedures:
            draft.status = AnswerStatus.ANSWERED
            return

        violating: list[ClaimView] = []
        violation_lines: list[str] = []
        finding_ids: list[str] = []
        for procedure in procedures:
            planned = procedure.revision.rule.decimal_value()
            draft.governing_facts.append(self._governing_fact(procedure))
            draft.citations.append(self._citation(procedure, statement_id="S1"))
            if contains(merged, planned, domain):
                continue
            violating.append(procedure)
            inequality = describe_violation(planned, merged, unit)
            violation_lines.append(
                f"The planned operating procedure retains records for exactly "
                f"{procedure.revision.rule.value} years from {starting}, which does not meet "
                f"the requirement of {describe(merged, unit)} ({inequality})."
            )
            # Keep pairwise finding identifiers available to reviewers without letting
            # the pair choice drive the answer text or constraint.
            for requirement in requirements:
                pair = compare_pair(requirement, procedure, views)
                if pair.finding_type is FindingType.COMPLIANCE_GAP:
                    key = finding_key(
                        pair.finding_type, pair.left_revision_id, pair.right_revision_id
                    )
                    finding_ids.append(finding_id_for(key))

        if violating:
            draft.status = AnswerStatus.ANSWERED
            for index, line in enumerate(violation_lines, start=2):
                draft.statements.append(
                    (f"S{index}", line + " This is a procedure-level gap; actual deletion was not observed.",
                     requirement_ids + procedure_ids)
                )
            draft.warnings.append(
                AnswerWarning(
                    code=QueryWarningCode.REVIEW_REQUIRED,
                    message=(
                        f"{len(violating)} of {len(procedures)} applicable operating "
                        "procedure(s) fall outside the authoritative retention requirement"
                    ),
                    claim_revision_ids=requirement_ids + procedure_ids,
                    finding_ids=sorted(set(finding_ids)),
                )
            )
            return

        draft.status = AnswerStatus.ANSWERED
        draft.statements.append(
            (
                f"S{len(draft.statements) + 1}",
                f"All {len(procedures)} applicable operating procedure(s) are compatible with "
                f"the applicable requirement of {describe(merged, unit)}.",
                requirement_ids + procedure_ids,
            )
        )
