"""Slack replay-event normalization.

Only *saved* events are accepted (no live Slack authorisation in the MVP).  Each
message becomes one clause whose exact parser text is the message text; message
publication time is source metadata, and the backend receipt time is separate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from ..contracts.common import PARSER_VERSION, ensure_utc
from .pdf import ParsedClause, ParsedDocument, UnsupportedDocument


@dataclass(frozen=True)
class SlackMessage:
    event_id: str
    ts: datetime
    user_id: str | None
    user_name: str | None
    channel_id: str | None
    channel_name: str | None
    text: str


def parse_slack_payload(data: bytes) -> list[SlackMessage]:
    """Parse a saved Slack event payload (single message or message list)."""

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnsupportedDocument("invalid_slack_json", f"payload is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise UnsupportedDocument("invalid_slack_json", "top-level payload must be a JSON object")

    channel = payload.get("channel") if isinstance(payload.get("channel"), dict) else {}
    events: list[dict] = []
    if isinstance(payload.get("event"), dict):
        events.append(payload["event"])
    if isinstance(payload.get("events"), list):
        events.extend(item for item in payload["events"] if isinstance(item, dict))
    if not events:
        raise UnsupportedDocument("invalid_slack_json", "no 'event' or 'events' entries were found")

    messages: list[SlackMessage] = []
    for item in events:
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise UnsupportedDocument("invalid_slack_event", "message text is missing")
        ts_raw = item.get("ts") or item.get("event_ts")
        if not isinstance(ts_raw, str):
            raise UnsupportedDocument("invalid_slack_event", "message timestamp is missing")
        messages.append(
            SlackMessage(
                event_id=str(item.get("event_id") or item.get("client_msg_id") or f"msg_{len(messages)}"),
                ts=_parse_ts(ts_raw),
                user_id=item.get("user"),
                user_name=item.get("user_name") or item.get("username"),
                channel_id=(channel or {}).get("id"),
                channel_name=(channel or {}).get("name"),
                text=text.strip(),
            )
        )
    return messages


def _parse_ts(raw: str) -> datetime:
    text = raw.strip()
    if text.replace(".", "", 1).isdigit():
        # Slack epoch style ("1772615700.000100") is accepted as a fallback.
        from ..integrations.slack import slack_time
        return slack_time(text if "." in text else text + ".000000")
    try:
        return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise UnsupportedDocument("invalid_slack_event", f"unsupported timestamp {raw!r}") from exc


def slack_to_document(messages: list[SlackMessage], *, parser_version: str = PARSER_VERSION) -> ParsedDocument:
    clauses = [
        ParsedClause(
            index=index,
            page=1,
            section=None,
            text=message.text,
            start_char=0,
            end_char=len(message.text),
        )
        for index, message in enumerate(messages)
    ]
    return ParsedDocument(
        page_count=1,
        clauses=clauses,
        parser_version=parser_version,
        text_length=sum(len(clause.text) for clause in clauses),
        warnings=["slack_publication_time_used_as_valid_from"],
    )
