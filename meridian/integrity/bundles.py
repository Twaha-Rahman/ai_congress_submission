"""Canonical payload builders and independent bundle verification."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from ..contracts.claims import ClaimRevision
from ..contracts.common import (
    MERKLE_CONVENTION,
    CheckStatus,
    OfficeRegion,
    Sensitivity,
    SourceType,
    StrictModel,
    ensure_utc,
    utc_now,
)
from ..contracts.manifest import SourceManifest
from ..contracts.verification import (
    BundleClause,
    CheckResult,
    ClaimBundleEntry,
    ClauseProof,
    EvidenceBundle,
    ManifestBundleEntry,
    VerificationReport,
)
from .canonical import canonical_hash_hex, canonical_json_bytes, sha256_hex
from .merkle import leaf_hash as _leaf_hash, verify_inclusion
from .signing import PinnedKeyRegistry, verify_with_registry


class SignedManifestPayload(StrictModel):
    """Canonical manifest committed and signed at ingestion time."""

    schema_version: str = "1"
    tenant_id: str
    region: OfficeRegion
    source_id: str
    source_identity: str
    version_label: str
    source_type: SourceType
    source_sha256: str
    merkle_root: str
    tree_size: int
    merkle_convention: str = MERKLE_CONVENTION
    parser_version: str
    contract_schema_version: str
    sensitivity: Sensitivity
    office_export: bool
    hosted_model: bool
    trusted_metadata: SourceManifest
    ingested_at: datetime
    signer_key_id: str

    @field_validator("ingested_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


def clause_leaf_payload(
    *,
    tenant_id: str,
    region: str,
    source_id: str,
    source_identity: str,
    version_label: str,
    clause_id: str,
    page: int,
    section: str | None,
    start_char: int,
    end_char: int,
    text: str,
    source_sha256: str,
    parser_version: str,
) -> bytes:
    """Canonical commitment payload for one clause leaf."""

    return canonical_json_bytes(
        {
            "schema_version": "1",
            "tenant_id": tenant_id,
            "region": region,
            "source_id": source_id,
            "source_identity": source_identity,
            "version_label": version_label,
            "clause_id": clause_id,
            "page": page,
            "section": section,
            "start_char": start_char,
            "end_char": end_char,
            "text": text,
            "source_sha256": source_sha256,
            "parser_version": parser_version,
        }
    )


def build_clause_proof(
    *,
    clause_id: str,
    leaf_hash_hex: str,
    index: int,
    tree_size: int,
    siblings_hex: list[str],
    merkle_root: str,
) -> ClauseProof:
    return ClauseProof(
        clause_id=clause_id,
        leaf_index=index,
        tree_size=tree_size,
        leaf_hash=leaf_hash_hex,
        siblings=siblings_hex,
        merkle_root=merkle_root,
    )


def verify_clause_proof(proof: ClauseProof, *, leaf_hash_hex: str) -> tuple[bool, str | None]:
    if proof.leaf_hash != leaf_hash_hex:
        return False, "proof leaf hash does not match the recomputed clause hash"
    siblings = []
    for item in proof.siblings:
        try:
            raw = bytes.fromhex(item)
        except ValueError:
            return False, "malformed sibling hash encoding"
        if len(raw) != 32:
            return False, "malformed sibling hash length"
        siblings.append(raw)
    try:
        root = bytes.fromhex(proof.merkle_root)
        leaf = bytes.fromhex(leaf_hash_hex)
    except ValueError:
        return False, "malformed root or leaf hash encoding"
    ok = verify_inclusion(
        leaf_hash_value=leaf,
        index=proof.leaf_index,
        tree_size=proof.tree_size,
        siblings=siblings,
        root=root,
    )
    if not ok:
        return False, "inclusion proof does not verify against the committed root"
    return True, None


def _check(name: str, status: CheckStatus, reason: str | None = None, **detail: str) -> CheckResult:
    return CheckResult(check=name, status=status, reason=reason, detail=detail)


def verify_bundle(
    bundle: EvidenceBundle,
    *,
    registry: PinnedKeyRegistry,
    tenant_id: str,
    now: datetime | None = None,
) -> VerificationReport:
    """Verify every supplied bundle component independently."""

    checks: list[CheckResult] = []
    moment = now or utc_now()

    # ------------------------------------------------------------ bundle envelope
    binding_errors: list[str] = []
    if bundle.tenant_id != tenant_id:
        binding_errors.append("bundle tenant does not match the verifying tenant")
    if bundle.answer.tenant_id != bundle.tenant_id:
        binding_errors.append("answer tenant does not match the bundle tenant")
    if bundle.region.value != bundle.answer.region.value:
        binding_errors.append("bundle region does not match the answer region")
    checks.append(
        _check(
            "bundle_binding",
            CheckStatus.FAILED if binding_errors else CheckStatus.PASSED,
            "; ".join(binding_errors) if binding_errors else None,
        )
    )

    # ---------------------------------------------------------------- answer text
    text_hash = sha256_hex(bundle.answer.answer_text.encode("utf-8"))
    if text_hash != bundle.answer.answer_text_hash:
        checks.append(
            _check(
                "answer_text_hash",
                CheckStatus.FAILED,
                "answer text does not match the hash bound into the answer payload",
            )
        )
    else:
        checks.append(_check("answer_text_hash", CheckStatus.PASSED))

    # ------------------------------------------------------------ answer signature
    answer_bytes = canonical_json_bytes(bundle.answer)
    recomputed = sha256_hex(answer_bytes)
    if recomputed != bundle.answer_hash:
        checks.append(
            _check(
                "answer_signature",
                CheckStatus.FAILED,
                "answer payload hash does not match the recorded hash",
            )
        )
    else:
        ok, reason = verify_with_registry(
            answer_bytes, bundle.answer_signature, bundle.answer_key_id, registry
        )
        checks.append(
            _check(
                "answer_signature",
                CheckStatus.PASSED if ok else CheckStatus.FAILED,
                reason,
            )
        )

    # ----------------------------------------------------------- claim signatures
    claim_checks = 0
    claim_failures = 0
    for entry in bundle.claims:
        claim_bytes = canonical_json_bytes(entry.claim)
        if sha256_hex(claim_bytes) != entry.claim_hash:
            claim_failures += 1
            claim_checks += 1
            continue
        ok, _ = verify_with_registry(claim_bytes, entry.signature, entry.key_id, registry)
        claim_checks += 1
        if not ok:
            claim_failures += 1
    if claim_checks == 0:
        checks.append(
            _check("claim_signature", CheckStatus.NOT_CHECKED, "no claim payloads supplied")
        )
    elif claim_failures:
        checks.append(
            _check(
                "claim_signature",
                CheckStatus.FAILED,
                f"{claim_failures} of {claim_checks} supplied claims failed verification",
            )
        )
    else:
        checks.append(
            _check("claim_signature", CheckStatus.PASSED, None, checked=str(claim_checks))
        )

    # -------------------------------------------------------- manifest signatures
    manifest_checks = 0
    manifest_failures = 0
    binding_failures = 0
    binding_failure_reasons: list[str] = []
    authenticated: dict[str, SignedManifestPayload] = {}
    for entry in bundle.manifests:
        payload_bytes = canonical_json_bytes(entry.manifest_payload)
        signature_ok = False
        if sha256_hex(payload_bytes) != entry.manifest_hash:
            manifest_failures += 1
        else:
            ok, _ = verify_with_registry(payload_bytes, entry.signature, entry.key_id, registry)
            if not ok:
                manifest_failures += 1
            else:
                signature_ok = True
        manifest_checks += 1
        try:
            signed = SignedManifestPayload.model_validate(entry.manifest_payload)
        except Exception:
            binding_failures += 1
            binding_failure_reasons.append(
                f"{entry.source_id}: signed manifest payload is not a valid SignedManifestPayload"
            )
            continue
        mismatches: list[str] = []
        if signed.tenant_id != tenant_id:
            mismatches.append("tenant")
        if signed.region != entry.region:
            mismatches.append("region")
        if signed.region.value != bundle.region.value:
            mismatches.append("bundle.region")
        if signed.source_id != entry.source_id:
            mismatches.append("source_id")
        if signed.source_identity != entry.source_identity:
            mismatches.append("source_identity")
        if signed.version_label != entry.version_label:
            mismatches.append("version_label")
        if signed.source_sha256 != entry.source_sha256:
            mismatches.append("source_sha256")
        if signed.merkle_root != entry.merkle_root:
            mismatches.append("merkle_root")
        if signed.tree_size != entry.tree_size:
            mismatches.append("tree_size")
        if signed.sensitivity.value != entry.sensitivity:
            mismatches.append("sensitivity")
        if signed.office_export != entry.office_export:
            mismatches.append("office_export")
        if signed.signer_key_id != entry.key_id:
            mismatches.append("signer_key_id")
        trusted = signed.trusted_metadata
        if trusted.tenant_id != signed.tenant_id:
            mismatches.append("trusted_metadata.tenant_id")
        if trusted.region != signed.region:
            mismatches.append("trusted_metadata.region")
        if trusted.source_identity != signed.source_identity:
            mismatches.append("trusted_metadata.source_identity")
        if trusted.version_label != signed.version_label:
            mismatches.append("trusted_metadata.version_label")
        if trusted.source_type != signed.source_type:
            mismatches.append("trusted_metadata.source_type")
        if trusted.sensitivity != signed.sensitivity:
            mismatches.append("trusted_metadata.sensitivity")
        if trusted.permissions.office_export != signed.office_export:
            mismatches.append("trusted_metadata.permissions.office_export")
        if trusted.permissions.hosted_model != signed.hosted_model:
            mismatches.append("trusted_metadata.permissions.hosted_model")
        try:
            trusted_parser = signed.trusted_metadata.model_dump(mode="json").get("parser_version")
        except Exception:  # pragma: no cover - SourceManifest has no parser field
            trusted_parser = None
        if trusted_parser is not None and trusted_parser != signed.parser_version:
            mismatches.append("trusted_metadata.parser_version")
        if mismatches:
            binding_failures += 1
            binding_failure_reasons.append(
                f"{entry.source_id}: wrapper fields disagree with the signed payload "
                f"({', '.join(mismatches)})"
            )
        elif signature_ok:
            authenticated[entry.source_id] = signed
        else:
            binding_failure_reasons.append(
                f"{entry.source_id}: manifest signature did not verify"
            )
    if manifest_checks == 0:
        checks.append(
            _check("manifest_signature", CheckStatus.NOT_CHECKED, "no manifest payloads supplied")
        )
    elif manifest_failures:
        checks.append(
            _check(
                "manifest_signature",
                CheckStatus.FAILED,
                f"{manifest_failures} of {manifest_checks} supplied manifests failed verification",
            )
        )
    else:
        checks.append(
            _check(
                "manifest_signature", CheckStatus.PASSED, None, checked=str(manifest_checks)
            )
        )
    if not bundle.manifests:
        checks.append(
            _check("manifest_binding", CheckStatus.NOT_CHECKED, "no manifest payloads supplied")
        )
    elif binding_failures:
        checks.append(
            _check(
                "manifest_binding",
                CheckStatus.FAILED,
                f"{binding_failures} of {len(bundle.manifests)} supplied manifests are not "
                "bound to their signed payloads: " + "; ".join(binding_failure_reasons),
            )
        )
    else:
        checks.append(
            _check(
                "manifest_binding",
                CheckStatus.PASSED,
                None,
                checked=str(len(authenticated)),
            )
        )

    # ------------------------------------------------------------ clause inclusion
    clause_checks = 0
    clause_failures = 0
    clause_skipped = 0
    clause_failure_reasons: list[str] = []
    disclosed_by_source: dict[str, dict[str, BundleClause]] = {}
    for entry in bundle.manifests:
        disclosed = {clause.clause_id: clause for clause in entry.clauses}
        disclosed_by_source[entry.source_id] = disclosed
        signed = authenticated.get(entry.source_id)
        for proof in entry.clause_proofs:
            if signed is None:
                clause_failures += 1
                clause_failure_reasons.append(
                    f"{entry.source_id}: proof supplied for an unauthenticated manifest"
                )
                continue
            if proof.merkle_root != signed.merkle_root:
                clause_failures += 1
                clause_failure_reasons.append(
                    f"{proof.clause_id}: proof root is not the signed manifest root"
                )
                continue
            if proof.tree_size != signed.tree_size:
                clause_failures += 1
                clause_failure_reasons.append(
                    f"{proof.clause_id}: proof tree size is not the signed tree size"
                )
                continue
            proof_ok, proof_reason = verify_clause_proof(
                proof, leaf_hash_hex=proof.leaf_hash
            )
            if not proof_ok:
                clause_failures += 1
                clause_failure_reasons.append(
                    f"{proof.clause_id}: {proof_reason}"
                )
                continue
            bundle_clause = disclosed.get(proof.clause_id)
            if bundle_clause is None:
                # Withheld text is legitimate, but the proof still has to be bound to
                # the authenticated root above.
                clause_skipped += 1
                continue
            if not (
                0
                <= bundle_clause.start_char
                <= bundle_clause.end_char
                <= len(bundle_clause.text)
            ):
                clause_failures += 1
                clause_failure_reasons.append(
                    f"{proof.clause_id}: disclosed offsets are outside the disclosed text"
                )
                continue
            leaf_payload = clause_leaf_payload(
                tenant_id=signed.tenant_id,
                region=signed.region.value,
                source_id=signed.source_id,
                source_identity=signed.source_identity,
                version_label=signed.version_label,
                clause_id=bundle_clause.clause_id,
                page=bundle_clause.page,
                section=bundle_clause.section,
                start_char=bundle_clause.start_char,
                end_char=bundle_clause.end_char,
                text=bundle_clause.text,
                source_sha256=signed.source_sha256,
                parser_version=signed.parser_version,
            )
            computed = _leaf_hash(leaf_payload).hex()
            ok, reason = verify_clause_proof(proof, leaf_hash_hex=computed)
            clause_checks += 1
            if not ok:
                clause_failures += 1
                clause_failure_reasons.append(f"{proof.clause_id}: {reason}")
    if clause_failures:
        checks.append(
            _check(
                "clause_inclusion",
                CheckStatus.FAILED,
                f"{clause_failures} clause proof problem(s): "
                + "; ".join(clause_failure_reasons[:10]),
            )
        )
    elif clause_checks == 0:
        checks.append(
            _check(
                "clause_inclusion",
                CheckStatus.NOT_CHECKED,
                "no disclosed clause text was supplied with the bundle"
                if clause_skipped == 0
                else "all supplied clause texts were withheld",
                skipped_not_disclosed=str(clause_skipped),
            )
        )
    else:
        checks.append(
            _check(
                "clause_inclusion",
                CheckStatus.PASSED,
                None,
                checked=str(clause_checks),
                skipped_not_disclosed=str(clause_skipped),
            )
        )

    # ------------------------------------------------------- claim evidence binding
    bound_claims: dict[str, ClaimBundleEntry] = {}
    claim_binding_failures: list[str] = []
    for entry in bundle.claims:
        claim = entry.claim
        signed = authenticated.get(claim.source_id)
        if signed is None:
            claim_binding_failures.append(
                f"{claim.revision_id}: claim source manifest was not supplied/authenticated"
            )
            continue
        if claim.evidence.manifest_root != signed.merkle_root:
            claim_binding_failures.append(
                f"{claim.revision_id}: evidence root is not the signed manifest root"
            )
            continue
        proof = entry.clause_proof
        if proof is None:
            claim_binding_failures.append(
                f"{claim.revision_id}: no clause proof was supplied for a local claim"
            )
            continue
        if proof.clause_id != claim.evidence.clause_id:
            claim_binding_failures.append(
                f"{claim.revision_id}: proof clause id does not match the evidence locator"
            )
            continue
        if proof.leaf_hash != claim.evidence.leaf_hash:
            claim_binding_failures.append(
                f"{claim.revision_id}: proof leaf hash does not match the evidence leaf hash"
            )
            continue
        if proof.merkle_root != signed.merkle_root or proof.tree_size != signed.tree_size:
            claim_binding_failures.append(
                f"{claim.revision_id}: proof is not bound to the signed tree root/size"
            )
            continue
        if entry.clause_disclosed:
            clause = disclosed_by_source.get(claim.source_id, {}).get(claim.evidence.clause_id)
            if clause is None:
                claim_binding_failures.append(
                    f"{claim.revision_id}: clause marked disclosed but no matching text was supplied"
                )
                continue
            locator_mismatch = (
                clause.page != claim.evidence.page
                or clause.section != claim.evidence.section
            )
            if locator_mismatch:
                claim_binding_failures.append(
                    f"{claim.revision_id}: evidence locator does not match the disclosed clause"
                )
                continue
            if not (
                0
                <= claim.evidence.start_char
                <= claim.evidence.end_char
                <= len(clause.text)
            ) or clause.text[
                claim.evidence.start_char : claim.evidence.end_char
            ] != claim.evidence.quote:
                claim_binding_failures.append(
                    f"{claim.revision_id}: evidence quote is not the disclosed clause substring"
                )
                continue
            recomputed_leaf = _leaf_hash(
                clause_leaf_payload(
                    tenant_id=signed.tenant_id,
                    region=signed.region.value,
                    source_id=signed.source_id,
                    source_identity=signed.source_identity,
                    version_label=signed.version_label,
                    clause_id=clause.clause_id,
                    page=clause.page,
                    section=clause.section,
                    start_char=clause.start_char,
                    end_char=clause.end_char,
                    text=clause.text,
                    source_sha256=signed.source_sha256,
                    parser_version=signed.parser_version,
                )
            ).hex()
            if recomputed_leaf != proof.leaf_hash:
                claim_binding_failures.append(
                    f"{claim.revision_id}: disclosed clause does not reproduce the proof leaf"
                )
                continue
            proof_ok, proof_reason = verify_clause_proof(
                proof, leaf_hash_hex=recomputed_leaf
            )
            if not proof_ok:
                claim_binding_failures.append(
                    f"{claim.revision_id}: {proof_reason}"
                )
                continue
        else:
            proof_ok, proof_reason = verify_clause_proof(
                proof, leaf_hash_hex=claim.evidence.leaf_hash
            )
            if not proof_ok:
                claim_binding_failures.append(
                    f"{claim.revision_id}: {proof_reason}"
                )
                continue
        bound_claims[claim.revision_id] = entry
    if not bundle.claims:
        checks.append(
            _check("claim_binding", CheckStatus.NOT_CHECKED, "no claim payloads supplied")
        )
    elif claim_binding_failures:
        checks.append(
            _check(
                "claim_binding",
                CheckStatus.FAILED,
                f"{len(claim_binding_failures)} of {len(bundle.claims)} claims are not bound "
                "to authenticated evidence: " + "; ".join(claim_binding_failures[:10]),
            )
        )
    else:
        checks.append(
            _check("claim_binding", CheckStatus.PASSED, None, checked=str(len(bound_claims)))
        )

    # ------------------------------------------------- answer -> evidence binding
    cited_claims = bound_claims
    mismatch_reasons: list[str] = []
    missing_local: list[str] = []
    remote_reference_ids = set(bundle.remote_references)
    remote_matched = 0
    local_matched = 0
    passage_withheld = 0
    for citation in bundle.answer.citations:
        if citation.claim_revision_id is None:
            signed = authenticated.get(citation.source_id)
            wrapper = next((entry for entry in bundle.manifests if entry.source_id == citation.source_id), None)
            clause = disclosed_by_source.get(citation.source_id, {}).get(citation.clause_id)
            proof = next((p for p in wrapper.clause_proofs if p.clause_id == citation.clause_id), None) if wrapper else None
            if (signed is None or proof is None or citation.remote or citation.claim_id is not None or citation.claim_payload_hash is not None
                    or citation.source_identity != signed.source_identity or citation.source_version_label != signed.version_label
                    or citation.manifest_root != signed.merkle_root or citation.authority != signed.trusted_metadata.authority.value
                    or citation.restricted != (signed.sensitivity is Sensitivity.RESTRICTED)
                    or proof.merkle_root != signed.merkle_root or proof.tree_size != signed.tree_size
                    or not verify_clause_proof(proof, leaf_hash_hex=proof.leaf_hash)[0]):
                mismatch_reasons.append(f"{citation.statement_id}: passage is not bound to an authenticated source/proof")
                continue
            if clause is None:
                passage_withheld += 1
                continue
            leaf = _leaf_hash(clause_leaf_payload(tenant_id=signed.tenant_id, region=signed.region.value,
                source_id=signed.source_id, source_identity=signed.source_identity, version_label=signed.version_label,
                clause_id=clause.clause_id, page=clause.page, section=clause.section,
                start_char=clause.start_char, end_char=clause.end_char, text=clause.text,
                source_sha256=signed.source_sha256, parser_version=signed.parser_version)).hex()
            if (leaf != proof.leaf_hash or citation.page != clause.page or citation.section != clause.section
                    or not (0 <= citation.start_char < citation.end_char <= len(clause.text))
                    or clause.text[citation.start_char:citation.end_char] != citation.quote):
                mismatch_reasons.append(f"{citation.statement_id}: passage quote or locator does not match committed text")
                continue
            local_matched += 1
            continue
        entry = cited_claims.get(citation.claim_revision_id)
        if entry is None:
            if citation.remote and citation.claim_revision_id in remote_reference_ids:
                remote_matched += 1
                continue
            missing_local.append(citation.claim_revision_id)
            continue
        claim = entry.claim
        signed = authenticated.get(claim.source_id)
        if signed is None:
            mismatch_reasons.append(
                f"{citation.statement_id}: claim source {claim.source_id} is not authenticated"
            )
            continue
        expected = {
            "claim_id": claim.claim_id,
            "source_id": claim.source_id,
            "source_identity": signed.source_identity,
            "source_version_label": signed.version_label,
            "clause_id": claim.evidence.clause_id,
            "manifest_root": claim.evidence.manifest_root,
            "claim_payload_hash": entry.claim_hash,
            "authority": claim.authority.value,
            "page": claim.evidence.page,
            "section": claim.evidence.section,
            "quote": claim.evidence.quote,
            "start_char": claim.evidence.start_char,
            "end_char": claim.evidence.end_char,
            "restricted": signed.sensitivity is Sensitivity.RESTRICTED,
        }
        actual = {
            "claim_id": citation.claim_id,
            "source_id": citation.source_id,
            "source_identity": citation.source_identity,
            "source_version_label": citation.source_version_label,
            "clause_id": citation.clause_id,
            "manifest_root": citation.manifest_root,
            "claim_payload_hash": citation.claim_payload_hash,
            "authority": citation.authority,
            "page": citation.page,
            "section": citation.section,
            "quote": citation.quote,
            "start_char": citation.start_char,
            "end_char": citation.end_char,
            "restricted": citation.restricted,
        }
        differing = sorted(key for key, value in expected.items() if actual.get(key) != value)
        if citation.remote:
            differing.append("remote")
        if differing:
            mismatch_reasons.append(
                f"{citation.statement_id}: citation disagrees with the signed claim "
                f"({', '.join(differing)})"
            )
            continue
        local_matched += 1

    expected_hashes = sorted({citation.claim_payload_hash for citation in bundle.answer.citations if citation.claim_payload_hash})
    if expected_hashes != sorted(set(bundle.answer.cited_claim_payload_hashes)):
        mismatch_reasons.append("answer cited_claim_payload_hashes do not match its citations")
    expected_roots = sorted({citation.manifest_root for citation in bundle.answer.citations})
    if expected_roots != sorted(set(bundle.answer.cited_manifest_roots)):
        mismatch_reasons.append("answer cited_manifest_roots do not match its citations")

    if mismatch_reasons or missing_local:
        reasons = mismatch_reasons + [
            f"local citation {revision_id} has no supplied claim entry"
            for revision_id in missing_local
        ]
        checks.append(
            _check(
                "answer_binding",
                CheckStatus.FAILED,
                "citations are not bound to the supplied evidence: " + "; ".join(reasons[:10]),
            )
        )
    elif not bundle.answer.citations:
        checks.append(_check("answer_binding", CheckStatus.PASSED, None, matched="0"))
    elif passage_withheld:
        checks.append(_check("answer_binding", CheckStatus.NOT_CHECKED,
            "one or more directly cited passage texts were withheld", matched=str(local_matched), not_supplied=str(passage_withheld + remote_matched)))
    elif local_matched == 0 and remote_matched:
        checks.append(
            _check(
                "answer_binding",
                CheckStatus.NOT_CHECKED,
                "all cited claims were legitimately undisclosed remote references",
                not_supplied=str(remote_matched),
            )
        )
    else:
        checks.append(
            _check(
                "answer_binding",
                CheckStatus.PASSED,
                None,
                matched=str(local_matched),
                not_supplied=str(remote_matched),
            )
        )

    return VerificationReport(
        tenant_id=tenant_id,
        region=bundle.region.value if hasattr(bundle.region, "value") else str(bundle.region),
        target_type="bundle",
        target_id=bundle.bundle_id,
        checks=checks,
        generated_at=moment,
    )


def claim_hash(claim: ClaimRevision) -> str:
    return canonical_hash_hex(claim)


__all__ = [
    "SignedManifestPayload",
    "BundleClause",
    "clause_leaf_payload",
    "build_clause_proof",
    "verify_clause_proof",
    "verify_bundle",
    "claim_hash",
]
