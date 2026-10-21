"""Upload review badges follow authorized current findings, not ingestion history."""
import asyncio

import pytest

from meridian.contracts.common import JobStatus, Mode, utc_now
from meridian.office_api.job_reviews import source_review_summaries
from meridian.storage.store import new_id
from meridian.integrity.canonical import canonical_json_bytes
from meridian.security.auth import Permission
from test_activity_versions import endpoints, principal


def create_job(office, source, kind="pdf"):
    job=office.store.create_job(kind=kind,mode=Mode.REPLAY,request={"manifest":source.manifest.model_dump(mode="json")})
    office.store.update_job(job.job_id,status=JobStatus.NEEDS_REVIEW,source_id=source.source_id,review_reason="policy_comparison_limit",finished=True)
    return office.store.get_job(job.job_id)


def review(get, finding, reviewer, action):
    class Request:
        async def json(self):
            return {"action":action,"reason":"Review completed for this upload","expected_snapshot_id":finding.snapshot_id}
    return asyncio.run(get("/v1/findings/{finding_id}/reviews","POST")(finding.payload.finding_id,Request(),principal=reviewer))


@pytest.mark.parametrize("kind",["pdf","slack","policy_comparison"])
def test_upload_review_progress_changes_without_rewriting_processing_history(dhaka_full,monkeypatch,kind):
    office=dhaka_full;get=endpoints(office,monkeypatch)
    reviewer=principal(Permission.READ_LOCAL,Permission.READ_RESTRICTED,Permission.REVIEW,Permission.AUDIT_READ)
    source=next(source for source in office.store.list_sources() if source.source_type=="slack")
    job=create_job(office,source,kind)
    original_finished=job.finished_at
    records=[record for record in office.store.list_findings(source_ids=[source.source_id],limit=None) if record.payload.detail.get("assessment")!="historical" and record.payload.explanation_code.value!="revision_not_current"]
    assert records
    def current():return get("/v1/jobs/{job_id}")(job.job_id,principal=reviewer)["job"]
    assert current()["review_summary"]["state"]=="needs_review"
    office.store.insert_claim_review(source_id=source.source_id,reason_code="policy_comparison_limit",detail={"detail":"Coverage incomplete"})
    for finding in records:review(get,finding,reviewer,"acknowledge")
    assert current()["review_summary"]["state"]=="acknowledged"
    for n,finding in enumerate(records):review(get,finding,reviewer,"resolve" if n%2 else "dismiss")
    updated=current()
    assert updated["review_summary"]["state"]=="reviewed"
    assert updated["review_summary"]["total"]==len(records)
    assert updated["review_summary"]["open"]==0
    assert updated["status"]=="needs_review" and updated["review_reason"]=="policy_comparison_limit"
    assert office.store.get_job(job.job_id).finished_at==original_finished
    assert any(not item["resolved"] for item in office.store.list_claim_reviews(source_id=source.source_id))
    assert next(item for item in get("/v1/jobs")(limit=50,principal=reviewer)["jobs"] if item["job_id"]==job.job_id)["review_summary"]==updated["review_summary"]
    assert get("/v1/activity/{event_id}")(f"processing:{job.job_id}",principal=reviewer)["event"]["outcome"]=="reviewed"
    # A newly published finding requires review again, without erasing prior reviews.
    previous=records[0]
    payload=previous.payload.model_copy(update={"created_at":utc_now(),"finding_id":new_id("finding"),"finding_key":new_id("finding_key")})
    with office.store.db.transaction() as connection:
        office.store.insert_finding_snapshot(connection,payload=payload,signature=office.signer.sign(canonical_json_bytes(payload)),key_id=office.signer.key_id,alert=True)
    assert current()["review_summary"]["state"]=="needs_review"
    assert current()["review_summary"]["open"]==1


def test_progress_is_version_specific_permission_filtered_and_not_capped_at_200(dhaka_full,monkeypatch):
    office=dhaka_full;get=endpoints(office,monkeypatch)
    reviewer=principal(Permission.READ_LOCAL,Permission.READ_RESTRICTED)
    reader=principal(Permission.READ_LOCAL)
    public=office.store.find_source_version("dhaka_lending_policy","v3")
    earlier=office.store.find_source_version("dhaka_lending_policy","v2")
    job=create_job(office,public)
    previous=create_job(office,earlier)
    full=get("/v1/jobs/{job_id}")(job.job_id,principal=reviewer)["job"]["review_summary"]
    limited=get("/v1/jobs/{job_id}")(job.job_id,principal=reader)["job"]["review_summary"]
    assert limited["total"]<full["total"]
    earlier_count=get("/v1/jobs/{job_id}")(previous.job_id,principal=reviewer)["job"]["review_summary"]["total"]
    model=next(record.payload for record in office.store.list_findings(source_ids=[public.source_id],limit=None) if record.payload.detail.get("assessment")!="historical" and record.payload.explanation_code.value!="revision_not_current")
    with office.store.db.transaction() as connection:
        for n in range(205):
            payload=model.model_copy(update={"finding_id":new_id("finding"),"finding_key":f"progress-limit-{n}"})
            office.store.insert_finding_snapshot(connection,payload=payload,signature=office.signer.sign(canonical_json_bytes(payload)),key_id=office.signer.key_id,alert=True)
    assert get("/v1/jobs/{job_id}")(job.job_id,principal=reviewer)["job"]["review_summary"]["total"]==full["total"]+205
    # Findings involving v3 cannot inflate the earlier version's count.
    assert get("/v1/jobs/{job_id}")(previous.job_id,principal=reviewer)["job"]["review_summary"]["total"]==earlier_count
    unrelated=office.store.find_source_version("dhaka_records_procedure","v1")
    assert source_review_summaries(office.store,[unrelated.source_id],finding_readable=lambda _:True)[unrelated.source_id]["state"]=="none"
