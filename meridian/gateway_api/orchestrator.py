"""Gateway orchestration: metadata-only federation across offices.

The gateway holds no office database and no raw source volume.  It fetches *signed
structured exports* from each office, verifies them against pinned public keys, merges
the allowlisted claim facts in memory, and records relay-level audit entries (sizes and
hashes only).  Clause text never reaches the gateway, so clause inclusion is always
reported as ``not_checked`` for federated answers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..contracts.common import (
    ClaimOrigin,
    ErrorCode,
    OfficeRegion,
    RuleKind,
    Subject,
    canonical_datetime,
    utc_now,
)
from ..contracts.federation import (
    ExportClaim,
    FederationExport,
    FederationSubquery,
)
from ..contracts.qa import AnswerPayload, QueryRequest
from ..federation.exchange import (
    target_fingerprint,
    target_fingerprint_for_facts,
    verify_export,
)
from ..integrity.canonical import canonical_json_bytes, sha256_hex
from ..integrity.signing import PinnedKeyRegistry, verify_with_registry
from ..rules.compare import ClaimView, aggregate_requirements
from ..rules.intervals import format_amount_minor, scope_matches_target
from ..rules.values import (
    REQUIREMENT_KINDS,
    constraint_for,
    contains,
    describe,
    describe_violation,
    domain_for,
    witness_value,
)


class OfficeUnavailable(RuntimeError):
    def __init__(self, region: str, detail: str) -> None:
        super().__init__(f"office {region} is unavailable: {detail}")
        self.region = region
        self.detail = detail


class FederationImportRejected(RuntimeError):
    """The requesting office refused the verified export; no comparison may run."""

    def __init__(self, region: str, detail: str, *, response: dict | None = None) -> None:
        super().__init__(f"office {region} rejected the import: {detail}")
        self.region = region
        self.detail = detail
        self.response = response or {}


@dataclass
class OfficeResult:
    region: str
    status: str  # delivered | blocked | unavailable | invalid
    export: FederationExport | None = None
    #: True only after envelope hash, pinned signature, signer office and request
    #: binding all verified.  Downstream computation must require this flag.
    verified: bool = False
    claims: int = 0
    withheld: int = 0
    not_checked: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    detail: str | None = None
    payload_bytes: int = 0
    payload_sha256: str | None = None


@dataclass
class RelayLog:
    path: Path

    def record(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for line in self.path.read_text("utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


class GatewayOrchestrator:
    """Fetches, verifies and merges signed exports from the two offices."""

    def __init__(
        self,
        *,
        tenant_id: str,
        office_urls: dict[str, str],
        office_tokens: dict[str, str | None],
        registry: PinnedKeyRegistry,
        relay_log: RelayLog,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.tenant_id = tenant_id
        self.office_urls = {key.upper(): value for key, value in office_urls.items()}
        self.office_tokens = {key.upper(): value for key, value in office_tokens.items()}
        self.registry = registry
        self.relay_log = relay_log
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    # ------------------------------------------------------------------ subset
    def known_offices(self) -> list[str]:
        return sorted(self.office_urls)

    # -------------------------------------------------------------- fetch stage
    def _post_json(self, region: str, path: str, payload: dict) -> dict:
        region = region.upper()
        url = self.office_urls.get(region)
        token = self.office_tokens.get(region)
        if not url:
            raise OfficeUnavailable(region, "no configured base URL")
        headers = {"authorization": f"Bearer {token}"} if token else {}
        try:
            with httpx.Client(
                transport=self._transport, timeout=self.timeout_seconds
            ) as client:
                response = client.post(f"{url.rstrip('/')}{path}", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise OfficeUnavailable(region, str(exc)) from exc
        if response.status_code >= 400:
            raise OfficeUnavailable(region, _error_detail(response))
        try:
            return response.json()
        except ValueError as exc:
            raise OfficeUnavailable(region, f"office returned non-JSON: {exc}") from exc

    def import_export(
        self, region: str, export: FederationExport, *, expect: dict[str, str] | None = None
    ) -> dict:
        """Deliver a verified export to the requesting office's remote namespace."""

        body: dict[str, Any] = {"export": export.model_dump(mode="json")}
        if expect:
            body["expect"] = expect
        response = self._post_json(region, "/v1/federation/imports", body)
        self._relay(
            region,
            export.payload.request_id,
            "imported" if response.get("accepted") else "import_rejected",
            export.payload_hash,
            None if response.get("accepted") else "; ".join(response.get("errors") or []),
            None,
        )
        return response

    def import_then_compare(
        self, requester: str, export: FederationExport, query: QueryRequest
    ) -> tuple[dict, dict, QueryRequest]:
        """Import one verified export, then run the comparator on that snapshot.

        The comparison is bound to the export's exact query context. An explicit
        recipient ``known_at`` is immutable: if the export arrived later, it is not
        supplied as an eligible snapshot and the comparator returns an incomplete
        review result unless an earlier matching snapshot exists. For a current query
        with no explicit cutoff, the recipient cutoff is captured at receipt time.
        """

        expect = {
            "origin_region": export.payload.origin_region.value,
            "request_id": export.payload.request_id,
            "target_fingerprint": target_fingerprint(
                self._subquery(export.payload.request_id, query).target
            ),
            "valid_at": query.valid_at.isoformat(),
        }
        if query.known_at is not None:
            expect["known_at"] = query.known_at.isoformat()
        imported = self.import_export(
            requester, export, expect=expect
        )
        if not imported.get("accepted"):
            raise FederationImportRejected(
                requester,
                "; ".join(imported.get("errors") or ["import was not accepted"]),
                response=imported,
            )
        snapshot_ids = list(imported.get("snapshot_ids") or [])
        if not snapshot_ids and imported.get("snapshot_id"):
            snapshot_ids = [str(imported["snapshot_id"])]
        if not snapshot_ids:
            raise FederationImportRejected(
                requester, "import accepted without a snapshot identifier", response=imported
            )
        receipt = imported.get("received_at")
        comparison_updates: dict[str, Any] = {
            "remote_source_known_at": export.payload.known_at,
            "remote_snapshot_required": True,
            "remote_snapshot_ids": [],
        }
        if receipt:
            received_at = datetime.fromisoformat(str(receipt).replace("Z", "+00:00"))
            if query.known_at is None:
                comparison_updates["known_at"] = received_at
            if query.known_at is None or received_at <= query.known_at:
                comparison_updates["remote_snapshot_ids"] = snapshot_ids
        comparison_request = query.model_copy(update=comparison_updates)
        comparison = self.comparison_at_office(requester, comparison_request)
        return imported, comparison, comparison_request

    def comparison_at_office(self, region: str, query: QueryRequest) -> dict:
        """Ask the requesting office's local comparator to produce the final answer.

        This is the Demo 3 path: the office already holds its own policy and the
        imported remote claim, so the comparison happens next to the governing policy.
        Passages are stripped from the response; only typed facts and opaque remote
        references cross back to the gateway.
        """

        body = self._post_json(
            region,
            "/v1/comparisons",
            query.model_dump(mode="json"),
        )
        try:
            answer = AnswerPayload.model_validate(body["answer"])
        except Exception as exc:  # noqa: BLE001 - untrusted inter-office response
            raise OfficeUnavailable(region.upper(), f"invalid comparison answer: {exc}") from exc
        answer_bytes = canonical_json_bytes(answer)
        if sha256_hex(answer_bytes) != body.get("answer_hash"):
            raise OfficeUnavailable(region.upper(), "comparison projection hash mismatch")
        key_id = str(body.get("answer_key_id", ""))
        ok, reason = verify_with_registry(
            answer_bytes, str(body.get("answer_signature", "")), key_id, self.registry
        )
        pinned = self.registry.get(key_id)
        if not ok or pinned is None or pinned.region.upper() != region.upper():
            raise OfficeUnavailable(
                region.upper(),
                reason or "comparison signer is not pinned to the requesting office",
            )
        if answer.tenant_id != self.tenant_id or answer.region.value.upper() != region.upper():
            raise OfficeUnavailable(region.upper(), "comparison projection tenant/region mismatch")
        if body.get("local_answer_id") != answer.answer_id:
            raise OfficeUnavailable(region.upper(), "comparison projection source answer mismatch")
        if body.get("local_answer_hash") != answer.model_metadata.get("local_answer_hash"):
            raise OfficeUnavailable(region.upper(), "comparison projection source hash mismatch")
        if answer.model_metadata.get("export_projection") != "comparison-v1":
            raise OfficeUnavailable(region.upper(), "unsupported comparison projection")
        if any(citation.quote is not None for citation in answer.citations):
            raise OfficeUnavailable(region.upper(), "comparison projection disclosed a passage quote")
        # Preserve the authenticated projection envelope for the API caller.
        return body

    def fetch_export(
        self,
        region: str,
        *,
        request_id: str,
        query: QueryRequest,
        subquery: FederationSubquery | None = None,
    ) -> OfficeResult:
        region = region.upper()
        url = self.office_urls.get(region)
        token = self.office_tokens.get(region)
        if not url:
            raise OfficeUnavailable(region, "no configured base URL")

        moment = utc_now()
        requested = subquery or self._subquery(request_id, query)
        payload = requested.model_dump(mode="json")
        headers = {"authorization": f"Bearer {token}"} if token else {}
        try:
            with httpx.Client(
                transport=self._transport, timeout=self.timeout_seconds
            ) as client:
                response = client.post(
                    f"{url.rstrip('/')}/v1/federation/claims", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            self._relay(region, request_id, "unavailable", None, None, str(exc))
            raise OfficeUnavailable(region, str(exc)) from exc

        if response.status_code >= 500:
            self._relay(region, request_id, "failed", None, None, f"http {response.status_code}")
            raise OfficeUnavailable(region, f"HTTP {response.status_code}")
        if response.status_code != 200:
            detail = _error_detail(response)
            self._relay(region, request_id, "denied", None, detail, None)
            return OfficeResult(
                region=region,
                status="blocked" if response.status_code == 403 else "invalid",
                detail=detail,
            )

        body = response.json()
        try:
            export = FederationExport.model_validate(body["export"])
        except Exception as exc:  # noqa: BLE001 - a malformed export is a structured failure
            self._relay(region, request_id, "invalid", None, str(exc), None)
            return OfficeResult(
                region=region, status="invalid", detail=f"malformed export: {exc}"
            )

        verified, errors = verify_export(
            export,
            registry=self.registry,
            tenant_id=self.tenant_id,
            expected_origin=region,
            expected_request_id=requested.request_id,
            expected_target_fingerprint=target_fingerprint(requested.target),
            expected_valid_at=requested.valid_at,
            expected_known_at=requested.known_at,
        )
        if verified is None:
            self._relay(
                region, request_id, "signature_failed", export.payload_hash, "; ".join(errors), None
            )
            # The untrusted payload is deliberately discarded: a rejected export must
            # never be available to any downstream answer or comparison path.
            return OfficeResult(
                region=region,
                status="invalid",
                detail="export signature/binding verification failed: " + "; ".join(errors),
                export=None,
                verified=False,
            )

        status = "delivered" if export.payload.claims else (
            "blocked" if export.payload.withheld_restricted else "delivered"
        )
        self._relay(
            region,
            request_id,
            status,
            export.payload_hash,
            None,
            None,
            payload_bytes=body.get("summary", {}).get("payload_bytes"),
        )
        return OfficeResult(
            region=region,
            status=status,
            export=export,
            verified=True,
            claims=len(export.payload.claims),
            withheld=export.payload.withheld_restricted,
            not_checked=list(export.payload.not_checked),
            reason_codes=list(export.payload.reason_codes),
            payload_bytes=int(body.get("summary", {}).get("payload_bytes") or 0),
            payload_sha256=export.payload_hash,
        )

    def _subquery(self, request_id: str, query: QueryRequest) -> FederationSubquery:
        target = query.target
        if target.subject is Subject.LOAN_APPROVAL:
            from ..contracts.federation import LoanTarget

            typed = LoanTarget(
                loan_type=target.loan_type,
                currency=target.currency,
                origin_office=target.origin_office,
                amount_minor=target.amount_minor,
            )
        else:
            from ..contracts.federation import RecordTarget

            typed = RecordTarget(
                record_class=target.record_class,
                origin_office=target.origin_office or OfficeRegion.DHAKA,
                processing_office=target.processing_office or OfficeRegion.DHAKA,
                product=target.product,
                starting_event=target.starting_event,
            )
        return FederationSubquery(
            request_id=request_id,
            subject=target.subject,
            target=typed,
            valid_at=query.valid_at,
            known_at=query.known_at or utc_now(),
            target_fingerprint=target_fingerprint(typed),
        )

    def _relay(
        self,
        region: str,
        request_id: str,
        outcome: str,
        payload_hash: str | None,
        error: str | None,
        detail: str | None,
        payload_bytes: int | None = None,
    ) -> None:
        self.relay_log.record(
            {
                "gateway_request_id": request_id,
                "office": region,
                "outcome": outcome,
                "payload_sha256": payload_hash,
                "error": error,
                "detailed_error": detail,
                "payload_bytes": payload_bytes or 0,
                "created_at": canonical_datetime(utc_now()),
            }
        )

    # ------------------------------------------------------------- merge stage
    def federated_answer(
        self,
        request_id: str,
        query: QueryRequest,
        results: list[OfficeResult],
    ) -> dict:
        views: list[tuple[str, ClaimView, ExportClaim]] = []
        for result in results:
            # Only fully verified exports participate; a rejected signature never
            # influences a federated answer even if the payload is attached.
            if not result.verified or result.export is None:
                continue
            for claim in result.export.payload.claims:
                if claim.subject is not query.target.subject:
                    continue
                view = _view_from_export_claim(result.export, claim)
                if scope_matches_target(view.revision.scope, query.target):
                    views.append((result.region, view, claim))

        contributions = [
            {
                "origin_region": region,
                "revision_id": view.revision.revision_id,
                "claim_id": view.revision.claim_id,
                "authority": view.revision.authority.value,
                "policy_family": view.revision.policy_family,
                "rule_summary": describe(
                    constraint_for(view.revision.rule), view.revision.rule.unit
                ),
                "claim_payload_hash": claim.claim_payload_hash,
                "manifest_root": view.revision.evidence.manifest_root,
                "source_ref": view.revision.source_id,
                "source_kind": claim.source_kind,
                "valid_from": canonical_datetime(view.revision.valid_from)
                if view.revision.valid_from
                else None,
                "valid_to": canonical_datetime(view.revision.valid_to)
                if view.revision.valid_to
                else None,
            }
            for region, view, claim in views
        ]

        statements: list[dict] = []
        warnings: list[dict] = []
        status = "abstained"

        requirements = [
            view
            for _region, view, _claim in views
            if view.revision.rule.kind in REQUIREMENT_KINDS
            and view.revision.authority.value in {"policy", "procedure"}
        ]
        procedures = [
            view
            for _region, view, _claim in views
            if view.revision.rule.kind is RuleKind.OPERATING_EXACT
        ]

        if query.target.subject is Subject.LOAN_APPROVAL and requirements:
            unit = requirements[0].revision.rule.unit
            domain = domain_for(unit)
            merged, _ = aggregate_requirements(requirements)
            if merged is None:
                status = "needs_review"
                statements.append(
                    {
                        "statement_id": "S1",
                        "text": (
                            "The federated authoritative requirements are mutually "
                            "unsatisfiable for these target facts; a reviewer must resolve "
                            "the conflict."
                        ),
                        "claim_revision_ids": [v.revision.revision_id for v in requirements],
                    }
                )
            else:
                witness = witness_value(merged, domain)
                assert witness is not None
                status = "answered"
                if merged.lo is not None and merged.hi is None:
                    lead = "At least"
                elif merged.hi is not None and merged.lo is None:
                    lead = "At most"
                elif (
                    merged.lo is not None
                    and merged.hi is not None
                    and merged.lo == merged.hi
                    and merged.lo_inclusive
                    and merged.hi_inclusive
                ):
                    lead = "Exactly"
                else:
                    lead = f"The allowed set is {describe(merged, unit)}"
                noun = "approval" if int(witness) == 1 else "approvals"
                verb = "is" if int(witness) == 1 else "are"
                if lead.endswith(("At least", "At most", "Exactly")):
                    lead = f"{lead} {int(witness)} {noun} {verb}"
                statements.append(
                    {
                        "statement_id": "S1",
                        "text": (
                            f"{lead} required for a "
                            f"{query.target.loan_type.value} loan of "
                            f"{format_amount_minor(query.target.amount_minor or 0)} as of "
                            f"{canonical_datetime(query.valid_at)}; federated offices "
                            f"converge on {describe(merged, unit)}."
                        ),
                        "claim_revision_ids": [v.revision.revision_id for v in requirements],
                    }
                )
        elif query.target.subject is Subject.RECORD_RETENTION:
            if not requirements:
                status = "abstained"
                warnings.append(
                    {
                        "code": "review_required",
                        "message": (
                            "no federated authoritative retention requirement applies to the "
                            "target facts at the requested valid_at/known_at"
                        ),
                    }
                )
            else:
                unit = requirements[0].revision.rule.unit
                domain = domain_for(unit)
                merged, _ = aggregate_requirements(requirements)
                requirement_ids = [v.revision.revision_id for v in requirements]
                procedure_ids = [v.revision.revision_id for v in procedures]
                if merged is None:
                    status = "needs_review"
                    statements.append(
                        {
                            "statement_id": "S1",
                            "text": (
                                "The federated authoritative retention requirements are mutually "
                                "unsatisfiable for these target facts; a reviewer must resolve "
                                "the conflict."
                            ),
                            "claim_revision_ids": requirement_ids + procedure_ids,
                        }
                    )
                else:
                    starting = (
                        query.target.starting_event.value
                        if query.target.starting_event
                        else "the starting event"
                    )
                    statements.append(
                        {
                            "statement_id": "S1",
                            "text": (
                                f"The applicable federated retention requirement is "
                                f"{describe(merged, unit)} from {starting} under "
                                f"{', '.join(sorted({v.revision.policy_family for v in requirements}))}."
                            ),
                            "claim_revision_ids": requirement_ids,
                        }
                    )
                    violations = []
                    for procedure in procedures:
                        planned = procedure.revision.rule.decimal_value()
                        if contains(merged, planned, domain):
                            continue
                        violations.append(
                            {
                                "statement_id": f"S{len(statements) + 1}",
                                "text": (
                                    f"Federated procedure retains records for exactly "
                                    f"{procedure.revision.rule.value} years, which does not meet "
                                    f"the requirement of {describe(merged, unit)} "
                                    f"({describe_violation(planned, merged, unit)})."
                                ),
                                "claim_revision_ids": requirement_ids + procedure_ids,
                            }
                        )
                        statements.append(violations[-1])
                    if violations:
                        status = "answered"
                        warnings.append(
                            {
                                "code": "review_required",
                                "message": (
                                    f"{len(violations)} of {len(procedures)} federated "
                                    "operating procedure(s) fall outside the authoritative "
                                    "retention requirement"
                                ),
                                "claim_revision_ids": requirement_ids + procedure_ids,
                            }
                        )
                    else:
                        status = "answered"
                        if procedures:
                            statements.append(
                                {
                                    "statement_id": f"S{len(statements) + 1}",
                                    "text": (
                                        f"All {len(procedures)} applicable federated operating "
                                        f"procedure(s) are compatible with {describe(merged, unit)}."
                                    ),
                                    "claim_revision_ids": requirement_ids + procedure_ids,
                                }
                            )
        else:
            status = "abstained"
            warnings.append(
                {
                    "code": "review_required",
                    "message": "no federated claims matched the typed target facts",
                }
            )

        withheld_total = sum(result.withheld for result in results)
        not_checked = sorted(
            {item for result in results for item in result.not_checked} or {"clause_inclusion"}
        )
        offices = [
            {
                "region": result.region,
                "status": result.status,
                "claims": result.claims,
                "withheld_restricted": result.withheld,
                "reason_codes": result.reason_codes,
                "payload_bytes": result.payload_bytes,
                "payload_sha256": result.payload_sha256,
                "detail": result.detail,
            }
            for result in results
        ]
        return {
            "request_id": request_id,
            "status": status,
            "statements": statements,
            "warnings": warnings,
            "contributions": contributions,
            "offices": offices,
            "withheld_restricted_total": withheld_total,
            "not_checked": not_checked,
            "no_raw_source_text_transferred": True,
            "generated_at": canonical_datetime(utc_now()),
        }


def _view_from_export_claim(export: FederationExport, claim: ExportClaim) -> ClaimView:
    """Reconstruct a comparable view from an allowlisted export claim.

    No clause text is available: the reconstructed evidence carries an opaque
    placeholder and verification stays ``not_checked`` for clause inclusion.
    """

    from ..contracts.claims import ClaimRevision
    from ..contracts.extraction import ExtractionProvenance, VerifiedEvidence

    revision = ClaimRevision(
        tenant_id=export.payload.tenant_id,
        region=export.payload.origin_region,
        claim_id=claim.claim_id,
        revision_id=claim.claim_revision_id,
        subject=claim.subject,
        scope=claim.scope,
        rule=claim.rule,
        authority=claim.authority,
        policy_family=claim.policy_family,
        source_id=f"remote_{export.payload.origin_region.value.lower()}_{claim.source_ref}",
        source_identity=f"remote:{export.payload.origin_region.value.lower()}",
        source_version_label=export.payload.request_id,
        source_clause_id="remote:not_disclosed",
        valid_from=claim.valid_from,
        valid_to=claim.valid_to,
        system_from=claim.system_from,
        evidence=VerifiedEvidence(
            clause_id="remote:not_disclosed",
            page=0,
            section=None,
            quote="",
            start_char=0,
            end_char=0,
            leaf_hash="not_disclosed",
            manifest_root=claim.manifest_root,
        ),
        extraction=ExtractionProvenance(
            mode="remote_export",
            provider=f"remote-office:{export.payload.origin_region.value.lower()}",
            model=None,
            validator_version="remote-export-v1",
            notes=["clause text not disclosed; clause inclusion is not_checked at the gateway"],
        ),
        origin=ClaimOrigin.REMOTE,
    )
    return ClaimView(
        revision=revision,
        system_to=claim.system_to,
        closure_kind=None,
        superseding_source_id=None,
        supersession_effective_from=None,
        payload_hash=claim.claim_payload_hash,
    )


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return f"{response.status_code}: {error.get('code')}: {error.get('message')}"
    return f"HTTP {response.status_code}"


__all__ = [
    "GatewayOrchestrator",
    "OfficeResult",
    "OfficeUnavailable",
    "RelayLog",
]
