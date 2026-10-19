"""Source ingestion: PDF/Slack normalisation, durable jobs and publication."""

from .pdf import ParsedClause, ParsedDocument, UnsupportedDocument, parse_pdf_bytes
from .pipeline import (
    IngestionOutcome,
    ManifestSourceMismatch,
    PreparedSource,
    VersionPayloadMismatch,
    build_source_version,
    clause_id_for,
    content_hash_of,
    ingest_prepared,
    prepare_pdf_source,
    prepare_slack_source,
    store_original,
)
from .slack import SlackMessage, parse_slack_payload, slack_to_document
from .worker import EgressRecorder, OfficeWorker

__all__ = [
    "EgressRecorder",
    "IngestionOutcome",
    "ManifestSourceMismatch",
    "OfficeWorker",
    "ParsedClause",
    "ParsedDocument",
    "PreparedSource",
    "SlackMessage",
    "UnsupportedDocument",
    "VersionPayloadMismatch",
    "build_source_version",
    "clause_id_for",
    "content_hash_of",
    "ingest_prepared",
    "parse_pdf_bytes",
    "parse_slack_payload",
    "prepare_pdf_source",
    "prepare_slack_source",
    "slack_to_document",
    "store_original",
]
