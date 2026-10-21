# Live Slack integration

The office API owns a read-only Socket Mode connection and a durable SQLite inbox.
It runs automatically with `make local-up` or Docker Compose when that office's
Slack credentials are configured. No public webhook, tunnel, Slack write scope or
separate connector command is required.

## Connect an office

1. Create a Slack app from [the app manifest](../config/slack/app-manifest.yml).
   Give it an office-specific name. Use **a separate app per office**, even in one
   workspace: Slack distributes events across connections for the same app, so
   sharing an app between office listeners could acknowledge an event at the wrong
   office. Duplicate configured app tokens are rejected locally.
2. Enable Socket Mode. Create an app-level token with `connections:write` and
   install the app to the workspace. The bot needs `channels:read` and
   `channels:history`, with the `message.channels` and `member_left_channel` bot
   event subscriptions in the manifest. No `chat:write` permission is needed.
3. Put the app-level and bot tokens in the ignored root `.env`, using
   `DHAKA_SLACK_APP_TOKEN` / `DHAKA_SLACK_BOT_TOKEN`, or the corresponding
   `FRANKFURT_` variables. Keep tokens out of browser storage, URLs and commits.
   Existing environment variables override `.env` values.
4. Invite the app to each channel to monitor. The first release supports public,
   unshared channels only. Private channels, DMs, Slack Connect/shared channels and
   archived channels are rejected.
5. Restart the office processes with `make local-down && make local-up`. This
   preserves their databases, sources and keys. Restart `make frontend` if the
   frontend bridge's uploader credential has changed.
6. In **Sources → Live Slack → Add channel**, enter the channel ID, policy family,
   applicability and reader scope. Choose hosted processing and structured claim
   export separately. Both are off by default. With hosted processing off, an
   explicitly approved office-local model is needed to extract statements.

The workspace identity is bound from Slack's `auth.test`; changing tokens to a
new workspace fails visibly instead of silently mixing that workspace's channels
with the existing office connection. Each office derives its own tenant/region
server-side. Only an authorized uploader can read or change connector settings;
the local reviewer browser uses its configured office uploader connection.

## Processing behavior

- The receiver commits the event and the channel's trusted configuration before
  acknowledging its Socket Mode envelope. Duplicate event IDs do not create jobs.
  Model work runs on the existing single office worker, outside acknowledgement.
- Each logical message is identified by workspace, channel and exact Slack `ts`.
  Edits create `v2`, `v3`, etc.; event timestamps are compared as decimals, never
  floating-point identities. Delayed older events cannot overwrite newer state.
- Source authority is always `informal`; content cannot change authority,
  sensitivity, applicability or permissions. Configuration is snapshotted at
  receipt. Changing it later does not silently broaden earlier events' access.
- Text messages and thread replies use the same general-policy extraction and
  comparison path as uploaded documents. Replies include the preserved parent
  message. If the parent is unavailable, processing requires review instead of
  interpreting a context-free reply. Parent edits/deletions withdraw affected
  replies and schedule context refreshes with their original access configuration.
- Edits, deletions and loss of channel access append signed source withdrawals and
  revision closures, then retire affected findings. Current source Q&A excludes
  withdrawn originals even if extraction previously produced no claims. Historical
  answers retain their original evidence; ordinary past-knowledge queries can still
  inspect earlier versions. No Slack event overwrites original captured bytes.
- Retained captured payloads are part of Meridian's immutable audit store. A Slack
  deletion withdraws current use; it is **not** a physical purge of stored history.
  This release does not implement a retention/purge policy.
- **Pause processing** stops new connector model jobs from starting; events are
  still saved and lifecycle withdrawals are applied. An already-running provider
  request may finish. Resume survives an office restart and releases queued work.
  PDF jobs and manually saved Slack ingestion remain independent of this switch.
- **Stop monitoring** stops new capture for that channel; already imported evidence
  remains. Access revocation instead withdraws current evidence and cancels obsolete
  queued work. A separate periodic reader checks channel access without blocking
  envelope acknowledgements; pending events and queued jobs are also checked immediately before model processing.
- Connection errors reconnect with bounded backoff. Captured pending events and
  queued model jobs recover after restart. The UI shows the last event, pending and
  failed/review jobs, and a persistent coverage warning after a disconnect.

## Limits and recovery

Live events cover activity while the app is subscribed and connected. Socket Mode
retries plus the durable inbox protect captured work; they do not establish complete
channel history. Initial history import, complete thread-history import and automatic
backfill after downtime are not implemented. Connection gaps remain visible, and the
app never claims they were filled. Missing thread parents can be retrieved individually
through `conversations.history`; unavailable context remains a review item.

Only message text is extracted. Files, images, canvases, reactions, bot output and
unsupported message subtypes are not imported as policy sources. The connector
never posts, edits, reacts to or deletes anything in Slack. No cross-office Slack
content flows through the gateway.

For expired/revoked credentials, reinstall/update the app and restart the office.
For a channel that became inaccessible, correct access and explicitly add it again;
it will not be silently re-enabled. Temporary API failures retain pending events
and retry later. Existing model retry budgets apply to model jobs, whose detailed
status is available under **Sources → Recent activity**.

## API and verification

- `GET /v1/integrations/slack`: secret-free office status, channel configurations,
  counts, recent event/job states and connection-gap information; uploader only.
- `POST /v1/integrations/slack`: `pause`, `resume`, `check`, `save_channel`, or
  `remove_channel`; uploader only. `save_channel` verifies public-channel membership
  with Slack before persisting its configuration. No endpoint accepts Slack tokens.
- `POST /v1/ingestions/slack`: existing authorized saved-event ingestion is unchanged.

Tests in `tests/test_slack_live.py` use isolated databases, a simulated Socket Mode
connection, mocked Slack HTTP and mocked model responses. They exercise durable
acknowledgement ordering, deduplication, restart, public-channel boundaries, exact
identities, edits/deletions, signed withdrawals, historical/raw retrieval, thread
refresh, pause and the real office worker. Frontend bridge tests enforce uploader,
office and same-origin boundaries. These are not a real-workspace/live-provider
acceptance claim.

Slack references: [Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/),
[message events](https://docs.slack.dev/reference/events/message/),
[history](https://docs.slack.dev/reference/methods/conversations.history/).

Verification for this implementation: **198 backend tests**, **76 frontend tests**,
a production frontend build, and headless browser checks at 320, 390, 760 and 1440px
in light/dark themes passed. Browser requests to Slack settings were simulated;
ordinary office databases were not reset or used for ingestion tests. No real Slack
workspace connection or paid model call was made. Backend tests used
`LLM_RESPONSE_FORMAT=json_schema .venv/bin/python -m pytest`; the existing offline
model doubles expect that response format, independently of the demo's configured
live JSON-object provider mode.


## Import saved Slack JSON in the browser

Use **Sources → Import Slack JSON**, or **Import saved Slack** from a processing
status dialog. This is an authorized saved-source upload and does not require a
live Slack connection or Slack app tokens. Reader workspaces cannot import.

The file must be a UTF-8 JSON object with either one `event` or an `events` array.
An optional `channel` object supplies its ID/name; channel IDs inside events must
agree. For example:

```json
{
  "channel": { "id": "C_EXAMPLE", "name": "team-guidance" },
  "events": [
    { "type": "message", "ts": "2026-10-21T09:00:00Z", "user": "U_EXAMPLE",
      "text": "Employees submit travel expenses through the company portal." }
  ]
}
```

The dialog's downloadable example uses the same format. Slack epoch timestamps
(e.g. `1792454400.123456`) and timezone-aware ISO timestamps are supported, with
microsecond precision preserved. Publication time is derived from the newest
message; the pipeline assigns individual message times to extracted statements.
Each timestamp may appear only once per channel batch. Thread replies require the
parent snapshot in the same file. A batch is limited to 200 messages, 100,000 text
characters and 5 MiB, and is never silently truncated. Complete workspace exports,
ZIP archives, mixed-channel batches and edit/delete event notifications are rejected.

Source authority is fixed to informal, cross-office export is disabled, and access
defaults to restricted readers. Hosted processing requires an explicit choice; an
approved local model uses a source with hosted processing off. The browser bridge
uses the office uploader identity, revalidates the file structure, rebuilds the
manifest, derives publication time and fixes tenant/office/type/authority/mode before
forwarding to `/v1/ingestions/slack`. File-provided manifests cannot grant authority
or change the destination office.

Imports are independent snapshots, not live subscriptions or implicit replacements
of previously imported messages. The existing durable pipeline detects identical
source/version content; changed content needs a distinct version. Saved JSON is
normalized into the API's canonical message payload, so preserved source bytes
represent that payload, not the original file's formatting or byte-order mark.

Status and stage timings appear in Recent activity. Opening the import dialog from
a processing job preserves that job's selection; successful submission adds the new
job without switching away from it. Failed submissions retain the file and form,
and advise checking recent activity before an ambiguous network failure is retried.

Saved-import verification passed 87 frontend checks, the production build, and
light/dark browser checks at 320–1440px. A separate isolated HTTP/API check exercised
shared JavaScript validation, authenticated ingestion, the real worker, source
publication and original-content retrieval with one simulated model call. Its empty
office correctly required review because no authoritative reference policy existed.
No ordinary office data was reset, no live Slack call was made, and no paid model
call was used for these checks.
