"""Two-axis temporal history: effective intervals, knowledge intervals, closures."""

from __future__ import annotations

from datetime import datetime, timezone

from meridian.contracts.common import ClosureKind, FindingType
from meridian.integrity.canonical import canonical_json_bytes, sha256_hex
from meridian.integrity.signing import verify_with_registry
from meridian.temporal.snapshots import (
    in_snapshot,
    knowledge_checkpoints,
    select_snapshot,
)

from conftest import (
    DEMO_POLICY_V2,
    DEMO_POLICY_V3,
    OfficeHarness,
    T_KNOWN,
    T_POLICY_V2,
    T_POLICY_V3,
    T_VALID,
    loan_target,
)

UTC = timezone.utc
JAN_15 = datetime(2026, 1, 15, tzinfo=UTC)
JAN_20 = datetime(2026, 1, 20, tzinfo=UTC)
FEB_01 = datetime(2026, 2, 1, tzinfo=UTC)


def _loan_views(harness: OfficeHarness):
    return harness.store.claim_views(subject="loan_approval")


def test_supersession_closes_old_revisions_and_carries_effective_history(
    dhaka_seeded: OfficeHarness,
) -> None:
    views = _loan_views(dhaka_seeded)
    v2 = [view for view in views if view.revision.source_version_label == "v2"]
    originals = [view for view in v2 if not view.carried_forward]
    carried = [view for view in v2 if view.carried_forward]

    assert originals
    assert all(view.system_to == T_POLICY_V3 for view in originals)
    assert all(view.closure_kind is ClosureKind.SUPERSESSION for view in originals)
    assert all(view.superseding_source_id for view in originals)

    assert carried
    for view in carried:
        assert view.system_to is None
        assert view.revision.system_from == T_POLICY_V3
        assert view.revision.valid_to == FEB_01
        # The correction is a new signed revision, never an edit of the old one.
        assert view.revision.revision_id not in {
            original.revision.revision_id for original in originals
        }

    v3 = [view for view in views if view.revision.source_version_label == "v3"]
    assert v3
    assert all(view.is_current for view in v3)


def test_known_at_selects_the_knowledge_available_at_that_moment(
    dhaka_seeded: OfficeHarness,
) -> None:
    views = _loan_views(dhaka_seeded)

    before = select_snapshot(views, valid_at=JAN_15, known_at=JAN_20)
    before_labels = {view.revision.source_version_label for view in before}
    assert "v2" in before_labels
    assert "v3" not in before_labels
    assert all(view.revision.system_from <= JAN_20 for view in before)

    after = select_snapshot(views, valid_at=T_VALID, known_at=T_KNOWN)
    after_labels = {view.revision.source_version_label for view in after}
    assert "v3" in after_labels
    assert "v2" not in after_labels

    # Selector semantics are inclusive at the start and exclusive at the end.
    first = min(views, key=lambda view: view.revision.system_from)
    assert in_snapshot(
        first,
        valid_at=first.revision.valid_from or JAN_15,
        known_at=first.revision.system_from,
    )
    assert not in_snapshot(
        first,
        valid_at=T_VALID,
        known_at=datetime(2000, 1, 1, tzinfo=UTC),
    )


def test_query_language_changes_across_the_knowledge_axis(
    dhaka_seeded: OfficeHarness,
) -> None:
    old_answer = dhaka_seeded.query(
        loan_target(4_000_000), valid_at=JAN_15, known_at=JAN_20
    )
    assert old_answer.payload.status.value == "answered"
    assert "1 approval is required" in old_answer.payload.answer_text
    assert {citation.source_version_label for citation in old_answer.payload.citations} == {
        "v2"
    }

    new_answer = dhaka_seeded.query(loan_target(4_000_000), valid_at=T_VALID, known_at=T_KNOWN)
    assert new_answer.payload.status.value == "answered"
    assert "2 approvals are required" in new_answer.payload.answer_text
    assert {citation.source_version_label for citation in new_answer.payload.citations} == {
        "v3"
    }


def test_original_revision_bytes_and_signatures_survive_supersession(
    dhaka: OfficeHarness,
) -> None:
    dhaka.ingest(DEMO_POLICY_V2, now=T_POLICY_V2)
    v2_source = dhaka.store.find_source_version("dhaka_lending_policy", "v2")
    assert v2_source is not None
    records_before = dhaka.store.claims_for_source(v2_source.source_id)
    fingerprints = {
        record.payload.revision_id: (record.payload_hash, record.signature)
        for record in records_before
    }

    outcome = dhaka.ingest(DEMO_POLICY_V3, now=T_POLICY_V3)
    assert outcome.error_code is None

    for record in dhaka.store.claims_for_source(v2_source.source_id):
        fingerprint = fingerprints.get(record.payload.revision_id)
        if fingerprint is None:
            continue  # carried-forward revision added by the closure
        assert (record.payload_hash, record.signature) == fingerprint
        assert record.system_to == T_POLICY_V3

    closures = dhaka.store.closures_for_source(outcome.source_id or "")
    assert len(closures) == 2
    for closure in closures:
        stored = dhaka.store.get_closure(closure.closure_id)
        assert stored is not None
        payload, payload_hash, signature, key_id = stored
        assert payload == closure
        assert payload_hash == sha256_hex(canonical_json_bytes(payload))
        assert verify_with_registry(
            canonical_json_bytes(payload), signature, key_id, dhaka.registry
        ) == (True, None)


def test_knowledge_checkpoints_are_real_ingestion_moments(
    dhaka_seeded: OfficeHarness,
) -> None:
    checkpoints = knowledge_checkpoints(_loan_views(dhaka_seeded))
    assert T_POLICY_V2 in checkpoints
    assert T_POLICY_V3 in checkpoints
    assert checkpoints == sorted(checkpoints)


def test_carried_history_is_queryable_but_not_published_as_new_findings(
    dhaka_full: OfficeHarness,
) -> None:
    views = _loan_views(dhaka_full)
    carried_ids = {
        view.revision.revision_id for view in views if view.carried_forward
    }
    assert carried_ids

    findings = dhaka_full.store.list_findings()
    assert findings
    for record in findings:
        assert not (set(record.payload.claim_revision_ids) & carried_ids)
    stale = [
        record
        for record in findings
        if record.payload.finding_type is FindingType.STALE_GUIDANCE
    ]
    assert len(stale) == 1
