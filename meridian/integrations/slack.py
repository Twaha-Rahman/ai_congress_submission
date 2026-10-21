"""Read-only Slack Socket Mode connector with an office-local durable inbox.

The socket only authenticates, validates delivery scope, commits an inbox event and
acks it. The existing single office worker serializes lifecycle changes and model
jobs; no provider call runs on Slack's acknowledgement path.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx
from pydantic import Field

from ..contracts.common import StrictModel, PolicyScope, utc_now, canonical_datetime
from ..contracts.manifest import SourceManifest
from ..integrity.canonical import canonical_json_bytes, sha256_hex


def slack_time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,12}\.\d{1,6}", value):
        raise ValueError("Invalid Slack timestamp")
    seconds, fraction = value.split(".")
    return datetime.fromtimestamp(int(seconds), timezone.utc).replace(microsecond=int(fraction.ljust(6, "0")))


class ChannelConfig(StrictModel):
    channel_id: str = Field(pattern=r"^C[A-Z0-9]{2,30}$")
    channel_name: str = Field(min_length=1, max_length=100)
    policy_family: str = Field(min_length=1, max_length=128)
    scope: PolicyScope
    sensitivity: str = Field(pattern=r"^(demo_shareable|restricted)$")
    hosted_model: bool = False
    office_export: bool = False


class SlackUnavailable(Exception):
    def __init__(self, message, *, code=None):
        super().__init__(message)
        self.code = code


class SlackConnector:
    def __init__(self, store, settings, *, transport=None, socket_factory=None):
        self.store, self.settings = store, settings
        self.transport, self.socket_factory = transport, socket_factory
        prefix = settings.region.upper()
        self.app_token = os.getenv(f"{prefix}_SLACK_APP_TOKEN", "")
        self.bot_token = os.getenv(f"{prefix}_SLACK_BOT_TOKEN", "")
        other = "FRANKFURT" if prefix == "DHAKA" else "DHAKA"
        self.configuration_error = bool(self.app_token and self.app_token == os.getenv(f"{other}_SLACK_APP_TOKEN"))
        self.state = "not_configured" if not self.configured else "connecting"
        self.error: str | None = "Use a separate Slack app for each office connector." if self.configuration_error else None
        self._stop = threading.Event()
        self._socket = None
        self._thread = None
        self._audit_thread = None

    @property
    def configured(self):
        return bool(self.app_token and self.bot_token) and not self.configuration_error

    @property
    def scope(self):
        return (self.store.tenant_id, self.store.region)

    def connection(self):
        with self.store.db.reader() as conn:
            row = conn.execute("SELECT * FROM slack_connections WHERE tenant_id=? AND region=?", self.scope).fetchone()
        return dict(row) if row else {"paused": 0, "team_id": None, "team_name": None, "coverage_gap_at": None, "connected_at": None}

    def mark_connection(self, *, connected: bool):
        now = canonical_datetime(utc_now())
        with self.store.db.transaction() as conn:
            if connected:
                conn.execute("UPDATE slack_connections SET connected_at=?,updated_at=? WHERE tenant_id=? AND region=?", (now, now, *self.scope))
            else:
                conn.execute("UPDATE slack_connections SET coverage_gap_at=?,updated_at=? WHERE tenant_id=? AND region=?", (now, now, *self.scope))

    def set_paused(self, paused: bool):
        with self.store.db.transaction() as conn:
            conn.execute("""INSERT INTO slack_connections (tenant_id,region,paused,updated_at) VALUES (?,?,?,?)
                ON CONFLICT (tenant_id,region) DO UPDATE SET paused=excluded.paused,updated_at=excluded.updated_at""",
                (*self.scope, int(paused), canonical_datetime(utc_now())))

    def call(self, method: str, **data):
        if not self.configured:
            raise SlackUnavailable("Slack credentials are not configured for this office.")
        try:
            with httpx.Client(transport=self.transport, timeout=8, follow_redirects=False) as client:
                headers = {"Authorization": f"Bearer {self.app_token if method == 'apps.connections.open' else self.bot_token}"}
                if method in {"conversations.info", "conversations.history"}:
                    response = client.get(f"https://slack.com/api/{method}", params=data, headers=headers)
                else:
                    response = client.post(f"https://slack.com/api/{method}", json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
            if not isinstance(result, dict) or not result.get("ok"):
                code = result.get("error", "slack_error") if isinstance(result, dict) else "invalid_response"
                raise SlackUnavailable(f"Slack request failed: {code}" if re.fullmatch(r"[a-z_]+", str(code)) else "Slack request failed.", code=code)
            return result
        except (httpx.HTTPError, ValueError) as exc:
            # Never expose exception strings containing credential-bearing websocket URLs.
            raise SlackUnavailable("Slack connection failed. Check connectivity and app permissions.") from exc

    def authenticate(self):
        auth = self.call("auth.test")
        team = auth.get("team_id")
        if not isinstance(team, str) or not re.fullmatch(r"T[A-Z0-9]+", team):
            raise SlackUnavailable("Slack returned an invalid workspace.")
        self.bot_user = auth.get("user_id")
        previous = self.connection()
        if previous["team_id"] and previous["team_id"] != team:
            raise SlackUnavailable("The configured Slack workspace differs from this office's saved connection.")
        with self.store.db.transaction() as conn:
            conn.execute("""INSERT INTO slack_connections (tenant_id,region,team_id,team_name,updated_at)
                VALUES (?,?,?,?,?) ON CONFLICT (tenant_id,region) DO UPDATE SET
                team_id=excluded.team_id,team_name=excluded.team_name,updated_at=excluded.updated_at""",
                (*self.scope, team, str(auth.get("team", team))[:100], canonical_datetime(utc_now())))
        return team

    def save_channel(self, config: ChannelConfig):
        self.authenticate()
        channel = self.call("conversations.info", channel=config.channel_id).get("channel", {})
        if (not channel.get("is_member") or channel.get("is_private") or channel.get("is_archived")
                or channel.get("is_shared") or channel.get("is_ext_shared") or channel.get("is_im") or channel.get("is_mpim")):
            raise SlackUnavailable("Choose an unshared public channel the app has joined.")
        trusted = config.model_copy(update={"channel_name": str(channel.get("name", config.channel_id))[:100]})
        with self.store.db.transaction() as conn:
            conn.execute("""INSERT INTO slack_channels (tenant_id,region,channel_id,config_json,enabled)
                VALUES (?,?,?,?,1) ON CONFLICT (tenant_id,region,channel_id) DO UPDATE SET
                config_json=excluded.config_json,enabled=1""", (*self.scope, config.channel_id, trusted.model_dump_json()))

    def disable_channel(self, channel_id):
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE slack_channels SET enabled=0 WHERE tenant_id=? AND region=? AND channel_id=?", (*self.scope, channel_id))

    def revoke_channel(self, channel_id, reason):
        with self.store.db.transaction() as conn:
            row = conn.execute("SELECT config_json FROM slack_channels WHERE tenant_id=? AND region=? AND channel_id=? AND enabled=1", (*self.scope, channel_id)).fetchone()
            if not row:
                return
            conn.execute("UPDATE slack_channels SET enabled=0 WHERE tenant_id=? AND region=? AND channel_id=?", (*self.scope, channel_id))
            from ..storage.store import new_id
            connection = self.connection()
            conn.execute("INSERT INTO slack_inbox (tenant_id,region,event_id,team_id,channel_id,payload_json,config_json,received_at,status) VALUES (?,?,?,?,?,?,?,?,?)",
                (*self.scope, new_id("access"), connection["team_id"], channel_id,
                 json.dumps({"reason": reason}), row[0], canonical_datetime(utc_now()), "pending"))

    def check_channels(self):
        with self.store.db.reader() as conn:
            rows = conn.execute("SELECT channel_id FROM slack_channels WHERE tenant_id=? AND region=? AND enabled=1", self.scope).fetchall()
        for row in rows:
            try:
                channel = self.call("conversations.info", channel=row[0]).get("channel", {})
                if not self.channel_allowed(channel):
                    self.revoke_channel(row[0], "Slack channel access changed.")
            except SlackUnavailable as exc:
                if exc.code in {"channel_not_found", "not_in_channel", "missing_scope", "token_revoked", "invalid_auth", "account_inactive"}:
                    self.revoke_channel(row[0], "Slack channel access is no longer available.")
                else:
                    raise

    @staticmethod
    def channel_allowed(channel):
        return bool(channel.get("is_member")) and not any(channel.get(k) for k in
            ("is_private", "is_archived", "is_shared", "is_ext_shared", "is_im", "is_mpim"))

    def status(self):
        connection = self.connection()
        with self.store.db.reader() as conn:
            channels = conn.execute("SELECT config_json FROM slack_channels WHERE tenant_id=? AND region=? AND enabled=1 ORDER BY channel_id", self.scope).fetchall()
            counts = conn.execute("""SELECT COALESCE(j.status,i.status) AS status,COUNT(*) AS n
                FROM slack_inbox i LEFT JOIN jobs j ON i.job_id=j.job_id
                WHERE i.tenant_id=? AND i.region=? GROUP BY COALESCE(j.status,i.status)""", self.scope).fetchall()
            recent = conn.execute("""SELECT i.event_id,i.channel_id,COALESCE(j.status,i.status) AS status,
                COALESCE(j.review_reason,i.reason) AS reason,i.job_id,i.received_at FROM slack_inbox i
                LEFT JOIN jobs j ON i.job_id=j.job_id
                WHERE i.tenant_id=? AND i.region=? ORDER BY i.received_at DESC LIMIT 12""", self.scope).fetchall()
        return {"configured": self.configured, "state": self.state, "paused": bool(connection["paused"]),
            "workspace": {"id": connection["team_id"], "name": connection["team_name"]},
            "error": self.error, "coverage_gap_at": connection["coverage_gap_at"], "channels": [json.loads(r[0]) for r in channels],
            "counts": {r["status"]: r["n"] for r in counts}, "recent": [dict(r) for r in recent],
            "last_event_at": recent[0]["received_at"] if recent else None}

    def receive(self, payload: dict) -> bool:
        """Return only after durable capture (or explicit scope rejection)."""
        if not isinstance(payload, dict):
            return False
        connection = self.connection()
        event = payload.get("event")
        if not isinstance(event, dict) or payload.get("team_id") != connection["team_id"]:
            return False
        # Stop rather than ingest after channel visibility/membership changes.
        if event.get("type") in {"channel_left", "channel_archive", "channel_deleted", "channel_shared"}:
            self.revoke_channel(event.get("channel"), "Slack channel access changed."); return False
        if event.get("type") == "member_left_channel" and event.get("user") == getattr(self, "bot_user", None):
            self.revoke_channel(event.get("channel"), "Slack channel access changed."); return False
        if event.get("subtype") == "channel_convert_to_private":
            self.revoke_channel(event.get("channel"), "Slack channel became private."); return False
        if event.get("type") != "message" or event.get("subtype") not in {None, "message_changed", "message_deleted", "thread_broadcast"}:
            return False
        if not isinstance(payload.get("event_id"), str) or not re.fullmatch(r"Ev[A-Za-z0-9]{1,120}", payload["event_id"]):
            return False
        with self.store.db.transaction() as conn:
            channel = conn.execute("SELECT config_json FROM slack_channels WHERE tenant_id=? AND region=? AND channel_id=? AND enabled=1", (*self.scope, event.get("channel"))).fetchone()
            if not channel:
                return False
            # Snapshot the trusted configuration; later edits cannot silently widen an event's permissions.
            added = conn.execute("""INSERT OR IGNORE INTO slack_inbox
                (tenant_id,region,event_id,team_id,channel_id,payload_json,config_json,received_at,status)
                VALUES (?,?,?,?,?,?,?,?,?)""", (*self.scope, payload["event_id"], payload["team_id"], event["channel"],
                json.dumps(payload), channel[0], canonical_datetime(utc_now()), "pending"))
            return added.rowcount == 1

    def start(self):
        if self.configured:
            self._thread = threading.Thread(target=self.run, name=f"slack-{self.settings.region.lower()}", daemon=True)
            self._thread.start()
            def audit():
                while not self._stop.wait(60):
                    if self.state == "connected":
                        try:
                            self.check_channels()
                        except SlackUnavailable:
                            self.error = "Slack channel access checks are delayed."
            self._audit_thread = threading.Thread(target=audit, name=f"slack-access-{self.settings.region.lower()}", daemon=True)
            self._audit_thread.start()

    def stop(self):
        self._stop.set()
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=10)
        if self._audit_thread:
            self._audit_thread.join(timeout=10)

    def run(self):
        from websockets.sync.client import connect
        delay = 1
        if self.connection().get("connected_at"):
            self.mark_connection(connected=False)
        while not self._stop.is_set():
            try:
                self.state = "connecting"
                self.authenticate()
                opened = self.call("apps.connections.open")
                url = opened.get("url", "")
                parsed = urlparse(url)
                if parsed.scheme != "wss" or not parsed.hostname or not parsed.hostname.endswith(".slack.com"):
                    raise SlackUnavailable("Slack returned an invalid socket address.")
                with (self.socket_factory or connect)(url, open_timeout=8, max_size=2 * 1024 * 1024) as socket:
                    self._socket = socket
                    self.state, self.error, delay = "connected", None, 1
                    self.mark_connection(connected=True)
                    while not self._stop.is_set():
                        try:
                            envelope = json.loads(socket.recv(timeout=1))
                        except TimeoutError:
                            continue
                        if envelope.get("type") == "disconnect":
                            self.mark_connection(connected=False)
                            break
                        if envelope.get("type") == "events_api":
                            payload = envelope.get("payload", {})
                            if payload.get("type") in {"app_uninstalled", "tokens_revoked"} or payload.get("event", {}).get("type") in {"app_uninstalled", "tokens_revoked"}:
                                with self.store.db.reader() as conn:
                                    channels = conn.execute("SELECT channel_id FROM slack_channels WHERE tenant_id=? AND region=? AND enabled=1", self.scope).fetchall()
                                for channel in channels:
                                    self.revoke_channel(channel[0], "Slack app access was revoked.")
                                socket.send(json.dumps({"envelope_id": envelope["envelope_id"]}))
                                self.state, self.error = "disconnected", "Slack access was revoked. Reinstall the app and restart the office."
                                return
                            self.receive(payload)
                            # Failed persistence raises: don't acknowledge data we didn't save.
                            socket.send(json.dumps({"envelope_id": envelope["envelope_id"]}))
            except Exception as exc:
                if isinstance(exc, SlackUnavailable) and exc.code in {"invalid_auth", "token_revoked", "account_inactive"}:
                    with self.store.db.reader() as conn:
                        channels = conn.execute("SELECT channel_id FROM slack_channels WHERE tenant_id=? AND region=? AND enabled=1", self.scope).fetchall()
                    for channel in channels:
                        self.revoke_channel(channel[0], "Slack app access was revoked.")
                self.mark_connection(connected=False)
                self.state = "disconnected"
                self.error = str(exc) if isinstance(exc, SlackUnavailable) else "Slack disconnected. Retrying automatically."
            finally:
                self._socket = None
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 60)
        self.mark_connection(connected=False)
        self.state = "disconnected"

    def process_once(self, signer) -> bool:
        """Called only by the office worker, before claiming its next model job."""
        import time
        if time.monotonic() < getattr(self, "retry_after", 0):
            return False
        with self.store.db.reader() as conn:
            row = conn.execute("SELECT * FROM slack_inbox WHERE tenant_id=? AND region=? AND status='pending' ORDER BY received_at,event_id LIMIT 1", self.scope).fetchone()
        if not row:
            return False
        try:
            if row["event_id"].startswith("access_"):
                with self.store.db.transaction() as conn:
                    self._withdraw(conn, signer, row["team_id"], row["channel_id"], None, json.loads(row["payload_json"])["reason"])
                self._finish(row["event_id"], "blocked", "Channel access withdrawn.")
                return True
            channel = self.call("conversations.info", channel=row["channel_id"]).get("channel", {})
            if not self.channel_allowed(channel):
                with self.store.db.transaction() as conn:
                    self._withdraw(conn, signer, row["team_id"], row["channel_id"], None, "Slack channel access changed")
                self.disable_channel(row["channel_id"])
                self._finish(row["event_id"], "blocked", "Channel access changed; current evidence withdrawn.")
                return True
            self._dispatch(dict(row), signer)
            if self.state == "connected":
                self.error = None
        except SlackUnavailable as exc:
            if exc.code in {"channel_not_found", "not_in_channel", "missing_scope", "token_revoked", "invalid_auth", "account_inactive"}:
                with self.store.db.transaction() as conn:
                    self._withdraw(conn, signer, row["team_id"], row["channel_id"], None, "Slack channel access is no longer available.")
                self.disable_channel(row["channel_id"])
                self._finish(row["event_id"], "blocked", "Channel access is no longer available.")
                return True
            self.error = "Slack channel access could not be checked. Pending events will retry."
            self.retry_after = time.monotonic() + 30
            return False
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            self._finish(row["event_id"], "needs_review", "Message or thread context could not be normalized.")
        return True

    def _finish(self, event_id, status, reason=None):
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE slack_inbox SET status=?,reason=?,processed_at=? WHERE tenant_id=? AND region=? AND event_id=?", (status, reason, canonical_datetime(utc_now()), *self.scope, event_id))

    def _withdraw(self, conn, signer, team, channel, message_ts, reason):
        """Append signed withdrawal/claim closures; retain original bytes and audit."""
        from ..contracts.claims import RevisionClosure
        from ..storage.store import new_id
        from ..rules.general import retire_policy_assessment
        sql = "SELECT source_id FROM slack_source_links WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=?"
        args = (*self.scope, team, channel)
        if message_ts is not None:
            sql += " AND (message_ts=? OR thread_ts=?)"; args += (message_ts, message_ts)
        linked_ids = {r["source_id"] for r in conn.execute(sql, args).fetchall()}
        # Publication can commit just before a crash interrupts link_result. Resolve
        # the stable identity too, so recovery cannot leave that source current.
        prefix = f"slack:{team}:{channel}:"
        if message_ts is None:
            recovered = conn.execute("SELECT source_id FROM sources WHERE tenant_id=? AND region=? AND source_identity LIKE ?", (*self.scope, prefix + "%")).fetchall()
        else:
            recovered = conn.execute("""SELECT source_id FROM sources WHERE tenant_id=? AND region=? AND
                (source_identity=? OR source_identity IN (SELECT ? || message_ts FROM slack_messages
                WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=? AND thread_ts=?))""",
                (*self.scope, prefix + message_ts, prefix, *self.scope, team, channel, message_ts)).fetchall()
        linked_ids.update(r["source_id"] for r in recovered)
        now = utc_now()
        revisions = set()
        for source_id in sorted(linked_ids):
            if conn.execute("SELECT 1 FROM source_withdrawals WHERE source_id=?", (source_id,)).fetchone():
                continue
            payload = {"source_id": source_id, "tenant_id": self.store.tenant_id, "region": self.store.region,
                "reason": reason, "withdrawn_at": canonical_datetime(now)}
            raw = canonical_json_bytes(payload)
            conn.execute("INSERT INTO source_withdrawals VALUES (?,?,?,?,?,?,?,?)", (source_id, *self.scope, canonical_datetime(now), raw.decode(), sha256_hex(raw), signer.sign(raw), signer.key_id))
            conn.execute("UPDATE sources SET status='withdrawn' WHERE source_id=?", (source_id,))
            for record in self.store.claims_for_source(source_id, connection=conn):
                if record.system_to is not None:
                    continue
                p = record.payload
                closure = RevisionClosure(tenant_id=p.tenant_id, region=p.region, closure_id=new_id("closure"),
                    revision_id=p.revision_id, closure_kind="retirement", system_to=now,
                    policy_family=p.policy_family, created_at=now)
                self.store.insert_closure(conn, closure, signature=signer.sign(canonical_json_bytes(closure)), key_id=signer.key_id)
                revisions.add(p.revision_id)
        for finding in self.store.list_findings(limit=100000, connection=conn):
            if revisions.intersection(finding.payload.claim_revision_ids) and finding.payload.detail.get("assessment") != "historical":
                retire_policy_assessment(conn, self.store, finding, signer=signer, now=now, explanation=reason)
        # A newer event also cancels obsolete queued retries, even when no source was published.
        for job in conn.execute("SELECT job_id,request_json FROM jobs WHERE tenant_id=? AND region=? AND status='queued' AND kind='slack'", self.scope).fetchall():
            metadata = json.loads(job["request_json"]).get("slack", {})
            if (metadata.get("team_id") == team and metadata.get("channel_id") == channel
                    and (message_ts is None or metadata.get("message_ts") == message_ts or metadata.get("thread_ts") == message_ts)):
                conn.execute("UPDATE jobs SET status='failed',error_code='source_withdrawn',review_reason=?,finished_at=?,updated_at=? WHERE job_id=?", (reason, canonical_datetime(now), canonical_datetime(now), job["job_id"]))

    def _dispatch(self, row, signer):
        from ..storage.store import new_id
        payload = json.loads(row["payload_json"])
        event = payload["event"]
        subtype = event.get("subtype")
        deleted = subtype == "message_deleted"
        message = event.get("message", {}) if subtype == "message_changed" else event
        ts = event.get("deleted_ts") if deleted else message["ts"]
        slack_time(ts)
        stamp = event.get("event_ts") or event.get("ts") or ts
        slack_time(stamp)
        identity = (*self.scope, row["team_id"], row["channel_id"], ts)
        with self.store.db.reader() as conn:
            old = conn.execute("SELECT * FROM slack_messages WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=? AND message_ts=?", identity).fetchone()
        refresh = row["event_id"].startswith("context:")
        if old and not refresh and Decimal(old["event_ts"]) >= Decimal(stamp):
            self._finish(row["event_id"], "ignored", "A newer message revision is already known."); return
        if refresh and (not old or old["deleted"]):
            self._finish(row["event_id"], "ignored", "Message was withdrawn."); return
        config = ChannelConfig.model_validate_json(row["config_json"])
        thread = message.get("thread_ts") if not deleted else old["thread_ts"] if old else None
        if thread == ts:
            thread = None
        context = None
        context_scope_mismatch = False
        if not deleted and (not isinstance(message.get("text"), str) or not message["text"].strip()):
            # An edit removing readable text must still withdraw the previous version.
            deleted = True
        if not deleted:
            if message.get("bot_id") or (getattr(self, "bot_user", None) and message.get("user") == self.bot_user):
                self._finish(row["event_id"], "ignored", "Bot message."); return
            if thread:
                slack_time(thread)
                with self.store.db.reader() as conn:
                    parent = conn.execute("SELECT * FROM slack_messages WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=? AND message_ts=?", (*self.scope, row["team_id"], row["channel_id"], thread)).fetchone()
                if parent and parent["deleted"]:
                    context = None
                elif parent:
                    context = json.loads(parent["message_json"])
                    parent_config = ChannelConfig.model_validate_json(parent["config_json"])
                    context_scope_mismatch = parent_config.scope != config.scope
                    config = config.model_copy(update={
                        "sensitivity": "restricted" if "restricted" in {config.sensitivity, parent_config.sensitivity} else "demo_shareable",
                        "hosted_model": config.hosted_model and parent_config.hosted_model,
                        "office_export": config.office_export and parent_config.office_export,
                    })
                else:
                    messages = self.call("conversations.history", channel=row["channel_id"], oldest=thread, latest=thread, inclusive=True, limit=1).get("messages", [])
                    context = next((m for m in messages if m.get("ts") == thread and m.get("text")), None)
        now = canonical_datetime(utc_now())
        with self.store.db.transaction() as conn:
            self._withdraw(conn, signer, row["team_id"], row["channel_id"], ts,
                "Slack message was deleted." if subtype == "message_deleted" else "Slack message or its thread context changed.")
            conn.execute("""INSERT INTO slack_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT (tenant_id,region,team_id,channel_id,message_ts) DO UPDATE SET
                event_ts=excluded.event_ts,thread_ts=excluded.thread_ts,message_json=excluded.message_json,
                config_json=excluded.config_json,revision=slack_messages.revision+1,deleted=excluded.deleted""",
                (*identity, old["event_ts"] if refresh else stamp, thread, json.dumps(message), config.model_dump_json(), 1, int(deleted)))
            revision = conn.execute("SELECT revision FROM slack_messages WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=? AND message_ts=?", identity).fetchone()[0]
            # Root changes refresh known replies with their own original text and dates.
            if not thread and not refresh:
                children = conn.execute("SELECT * FROM slack_messages WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=? AND thread_ts=? AND deleted=0", (*self.scope, row["team_id"], row["channel_id"], ts)).fetchall()
                for child in children:
                    child_event = json.loads(child["message_json"])
                    child_event["channel"] = row["channel_id"]
                    child_event["event_ts"] = child["event_ts"]
                    key = "context:" + sha256_hex(f'{row["event_id"]}/{child["message_ts"]}'.encode())[:40]
                    conn.execute("INSERT OR IGNORE INTO slack_inbox (tenant_id,region,event_id,team_id,channel_id,payload_json,config_json,received_at,status) VALUES (?,?,?,?,?,?,?,?,?)",
                        (*self.scope, key, row["team_id"], row["channel_id"], json.dumps({"event": child_event}), child["config_json"], now, "pending"))
            if deleted:
                status, reason, job_id = "processed", "Message withdrawn.", None
            elif thread and (not context or context_scope_mismatch):
                status, reason, job_id = "needs_review", (
                    "Thread applicability changed; review its context before extraction." if context_scope_mismatch
                    else "Thread parent is unavailable; no standalone claim was extracted."), None
            else:
                messages = ([context] if context else []) + [message]
                normalized = {"channel": {"id": row["channel_id"], "name": config.channel_name},
                    "events": [{"text": m["text"], "ts": m["ts"], "user": m.get("user"), "event_id": f'{row["team_id"]}:{row["channel_id"]}:{m["ts"]}'} for m in messages],
                    "slack_event": payload}
                raw = canonical_json_bytes(normalized)
                version = f"v{revision}"
                manifest = SourceManifest(tenant_id=self.store.tenant_id, region=self.store.region,
                    source_identity=f'slack:{row["team_id"]}:{row["channel_id"]}:{ts}', version_label=version,
                    source_type="slack", subject="general_policy", authority="informal", policy_family=config.policy_family,
                    scope=config.scope, effective_from=None, effective_to=None,
                    rationale=f"#{config.channel_name} · {slack_time(ts).strftime('%d %b %Y %H:%M UTC')}",
                    publication_time=max(slack_time(m["ts"]) for m in messages), sensitivity=config.sensitivity,
                    permissions={"hosted_model": config.hosted_model, "office_export": config.office_export})
                staged = self.settings.source_dir / "_staging" / f"slack-{sha256_hex(row['event_id'].encode())[:32]}.json"
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(raw)
                job_id = new_id("job")
                request = {"manifest": manifest.model_dump(mode="json"), "file_ref": str(staged),
                    "request_id": row["event_id"], "uploaded_by": "slack_connector",
                    "slack": {"team_id": row["team_id"], "channel_id": row["channel_id"], "message_ts": ts, "thread_ts": thread}}
                conn.execute("""INSERT INTO jobs (job_id,tenant_id,region,kind,status,mode,request_json,created_at,updated_at)
                    VALUES (?,?,?,'slack','queued','live',?,?,?)""", (job_id, *self.scope, json.dumps(request), now, now))
                status, reason = "queued", None
            conn.execute("UPDATE slack_inbox SET status=?,reason=?,job_id=?,processed_at=? WHERE tenant_id=? AND region=? AND event_id=?", (status, reason, job_id, now, *self.scope, row["event_id"]))

    def jobs_paused(self):
        import time
        return not self.configured or bool(self.connection()["paused"]) or time.monotonic() < getattr(self, "retry_after", 0)

    def authorize_job(self, job, signer):
        """Recheck access after queueing/pausing, immediately before model egress."""
        from ..contracts.common import JobStatus
        import time
        metadata = job.request.get("slack")
        if not metadata:
            return True
        try:
            channel = self.call("conversations.info", channel=metadata["channel_id"]).get("channel", {})
            if not self.channel_allowed(channel):
                raise SlackUnavailable("Slack channel access changed.", code="not_in_channel")
            with self.store.db.reader() as conn:
                current = conn.execute("SELECT revision,deleted FROM slack_messages WHERE tenant_id=? AND region=? AND team_id=? AND channel_id=? AND message_ts=?",
                    (*self.scope, metadata["team_id"], metadata["channel_id"], metadata["message_ts"])).fetchone()
            if not current or current["deleted"] or f'v{current["revision"]}' != job.request["manifest"]["version_label"]:
                self.store.update_job(job.job_id, status=JobStatus.FAILED, error_code="source_withdrawn", review_reason="A newer Slack revision is already known.", finished=True)
                return False
            return True
        except SlackUnavailable as exc:
            if exc.code in {"channel_not_found", "not_in_channel", "missing_scope", "token_revoked", "invalid_auth", "account_inactive"}:
                with self.store.db.transaction() as conn:
                    self._withdraw(conn, signer, metadata["team_id"], metadata["channel_id"], None, "Slack channel access changed.")
                self.disable_channel(metadata["channel_id"])
                self.store.update_job(job.job_id, status=JobStatus.FAILED, error_code="forbidden", review_reason="Slack channel access is no longer available.", finished=True)
            else:
                # A permission lookup is not a model attempt and must not exhaust its retry budget.
                with self.store.db.transaction() as conn:
                    conn.execute("UPDATE jobs SET status='queued',attempts=MAX(0,attempts-1),started_at=NULL,error_code='provider_error',review_reason=? WHERE job_id=? AND tenant_id=? AND region=?",
                        ("Slack access check delayed. Retrying automatically.", job.job_id, *self.scope))
                self.retry_after = time.monotonic() + 30
            return False

    def link_result(self, job, source_id):
        metadata = job.request.get("slack")
        if not metadata or not source_id:
            return
        with self.store.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO slack_source_links VALUES (?,?,?,?,?,?,?)",
                (source_id, *self.scope, metadata["team_id"], metadata["channel_id"], metadata["message_ts"], metadata.get("thread_ts")))


def source_slack_link(store, source_id):
    with store.db.reader() as conn:
        row = conn.execute("SELECT * FROM slack_source_links WHERE source_id=? AND tenant_id=? AND region=?", (source_id, store.tenant_id, store.region)).fetchone()
    if not row:
        return None
    return {"team_id": row["team_id"], "channel_id": row["channel_id"], "message_ts": row["message_ts"],
        "url": f'https://app.slack.com/client/{row["team_id"]}/{row["channel_id"]}?message_ts={row["message_ts"]}'}
