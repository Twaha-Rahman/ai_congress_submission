# Activity and source-version comparison

## Activity

Open **Activity** from the sidebar in a reviewer workspace. The office selector
chooses the office whose records and counters are displayed. The viewer includes:

- Published sources and recorded source withdrawals.
- Current durable processing-job snapshots, with mode, attempts, timestamps,
  current stage and errors. Open the job for its full stage timings. These rows
  are not an append-only history of every processing transition.
- Persisted finding review decisions, including actor, reason and referenced
  snapshot.
- Office-to-office and hosted-model transfers, with actual payload/raw-text byte
  counts, outcomes, request IDs, fingerprints and recorded model metadata.

Search names, reasons, requests or metadata, filter by type/outcome and choose UTC
start/end dates directly. Counters are office-wide transfer totals, independent of
list filters; zero-byte totals remain zero. Transfer details can filter the list
to the same request. Record details link to the original source, processing job
or finding as appropriate. Loaded records and individual records can be exported.
Exported filters describe the successfully loaded result, even after a failed
refresh. Share view preserves filters and the selected record in the URL.

Refresh failures retain the existing list and its position. Auto-refresh is an
explicit toggle and pauses during dialogs or editing. Refreshing a list with older
pages loaded retains those records, updates matching records and preserves a cursor
to any newly discovered gap. Search matches in visible text and metadata excerpts
are highlighted. Single-key shortcuts follow the existing preference and typing
and dialog guards; `/`, Shift+R, Shift+E and Shift+S are available.

The read-only office APIs are `GET /v1/activity` and
`GET /v1/activity/{category}:{id}`. List options are `category`, `outcome`, `q`,
`since`, `until`, `limit` (1–100) and an authenticated encrypted `cursor`. Dates require timezones.
Records sort by UTC timestamp with microsecond precision, then a stable event ID.
Cursor contents do not expose scanned restricted IDs; restarting the API requires
refreshing the list before loading more. Each page scans at most 1,000 candidates and returns a cursor when more remain;
a sparse search can require **Load more activity** even when a page is empty.
The summary uses the existing audited transfer totals and model-call counters.
These projections do not claim that every user action is recorded or that the UI
has cryptographically verified the audit history. Gateway relay logs remain a
separate gateway API; this view shows office records.

Both APIs require the office/tenant-scoped `audit_read` and `read_local` permissions.
Source/job/review visibility is checked against the underlying source access.
The frontend bridge uses the configured reviewer principal, never an uploader or
service identity. Reader workspaces cannot access these routes. Request bodies,
staged file paths, raw model prompts/responses and credentials are not returned.
Destination URLs omit credentials, query strings and fragments.

## Source versions

In **Sources**, choose a source row's **Compare versions** action, or open
**Inspect source → Compare versions**. Choose a base and compared version, or swap
them. The two versions must have the same trusted source identity in the same
office and both must be readable. A source with one accessible version has a clear
empty state; inaccessible versions are not advertised.

The comparison shows added, removed, changed and unchanged parser passages,
side-by-side on desktop and stacked on mobile. Text changes use explicit labels,
underlining for additions and strikethrough for removals. Search highlights coexist
with those change markers, including phrases crossing a change boundary. Filter
the passage list or inspect either version's original at the passage's page.
Closing the original returns to the comparison. The wide PDF inspector is reused.

Metadata changes are separate and start collapsed: authority, scope, access,
processing/export permissions, dates, declared conditions, rationale and explicit
supersession. Source-file identity and parsed-text identity are reported separately.
A newer version label never creates a replacement relationship. A recorded
replacement can cover particular passages/scopes; its full manifest details appear
under metadata changes.

Share preserves the source, base/compared direction, filter and search in the URL.
Export downloads the complete loaded comparison. `/` focuses passage search;
Shift+E exports and Shift+S opens the comparison link, with the existing keyboard
preference/typing guards. Escape closes the dialog.

The read-only APIs are `GET /v1/sources/{id}/versions` and
`GET /v1/sources/{base}/diff?other={compared}`. Versions are retrieved by trusted
identity without the source library's 100-record limit, then filtered for access.
The diff uses preserved parser text, exact-text anchors and document-order
alignment inside replacements. Moving text may appear as removal/addition; this
is not a semantic policy comparison or a PDF layout/image diff. No model call is
made. More than 10,000 combined passages or 2,000,000 combined text characters is
rejected explicitly. Very large replacement passages use whole-passage markers
instead of expensive word matching; literal text is never silently truncated.

## Verification

Backend tests use isolated offices for source/review/transfer records, role and
tenant boundaries, hidden versions, cursor ties and subsecond order, date
validation, source withdrawals and exact reconstruction of both diff sides.
Frontend tests cover bridge methods/principals, URL restoration, stable refresh
merging and search/diff boundary handling. Headless browser checks use a temporary
backend and frontend on ports 8091/5176, with real read-only APIs and stored original
PDFs. They cover pagination, failed refreshes without list movement, shared links,
reversed comparisons, original-source inspection/return, reader and single-version
states, and 320–1440px layouts in both themes. No working-office data, live Slack
workspace or paid model call is used.
