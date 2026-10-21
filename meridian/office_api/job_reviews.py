"""Current finding-review progress, separate from immutable ingestion outcomes."""


def source_review_summaries(store, source_ids, *, finding_readable):
    ids = {source_id for source_id in source_ids if source_id}
    summaries = {source_id: {"total": 0, "open": 0, "acknowledged": 0, "resolved": 0, "dismissed": 0} for source_id in ids}
    for record in store.list_findings(source_ids=sorted(ids), limit=None):
        payload = record.payload
        if (payload.detail.get("assessment") == "historical"
                or payload.explanation_code.value == "revision_not_current"
                or not finding_readable(record)):
            continue
        for source_id in {evidence.source_id for evidence in payload.evidence} & ids:
            summaries[source_id]["total"] += 1
            summaries[source_id][record.review_state.value] += 1
    for summary in summaries.values():
        summary["state"] = ("needs_review" if summary["open"] else "acknowledged" if summary["acknowledged"] else "reviewed" if summary["total"] else "none")
    return summaries


def job_review_state(job, summary):
    if job.status in {"succeeded", "needs_review"} and summary and summary["total"]:
        return summary["state"]
    return job.status
