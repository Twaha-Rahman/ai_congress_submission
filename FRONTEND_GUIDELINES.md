# Meridian frontend: design and interaction notes

Status: implemented starting point for a style/UX review, not an approved final
design system. Findings and Sources share the patterns below; refine them before
applying these rules to the remaining workflows.

## Scope and visual reference

The first slice is **Findings and investigation**: an office-scoped queue,
evidence comparison, source inspection, chronology, and reviewer decisions. The
second slice is **Sources and PDF ingestion**: a source library, trusted upload
metadata, processing status and whole-version replacement. The third slice is **Verification and lineage**: source-copy checks, signed answer
bundles and authorized evidence connections. Questions and cross-office audit remain
later slices.
Do not add navigation destinations until their workflows exist.

`DESIGN.md` was installed using `npx getdesign@latest add claude`. Use its warm
canvas, editorial serif/sans pairing, cream surfaces, hairlines, restrained coral,
and low-shadow layout. Meridian retains its own name and globe mark. The design
reference is inspiration, not a claim of affiliation with Claude or Anthropic.

## Tokens and type

Tokens live in `frontend/src/styles.css`; use variables when extending components.

- Light canvas `#faf9f5`, soft surface `#f5f0e8`, and inset/card surface `#efe9de`.
  Queue cards use `#f7f4ee`, raised evidence/dialogs `#fffdf8`, selected findings
  pale coral `#f9ece2`, and keycaps `#f1ede6`.
- Warm ink `#141413`, body `#3d3d3a`, secondary text `#6c6a64`.
- Hairlines `#e6dfd8`; functional input borders `#8d877c` for stronger contrast.
- Coral `#cc785c` for small accents. Primary buttons use the reference's darker
  coral `#a9583e` so small light labels remain readable.
- Warning ink `#93482f` on `#f6e9e0`; resolved/success ink `#356454` on `#e9efea`.
  These are semantic accents, not alternative page backgrounds.
- Light/dark/system appearance is selected in the header. Default to System and
  persist only the preference in local storage. Apply it before the first paint;
  follow system changes while System is selected. Dark mode uses neutral charcoal
  surfaces and warm cream text. Navigation is `#171719`, the workspace `#1e1e20`,
  queue cards `#242426`, and raised evidence/dialogs `#2c2c2f`. Selected findings
  use a coral-tinted `#3b2c27` surface and an inset vertical marker. Use the
  shared variables for controls, popups, dialogs and scrollbars. Original PDF pages
  retain their document colors. Theme preference stays out of shared finding URLs.
- Surface tokens describe their role: chrome, header, queue, selected, scope, field,
  raised, secondary control and keycap. Dark mode separates light coral text/focus
  (`--primary`) from richer coral button fills (`--primary-fill`) and pressed fills.
  Policy evidence gets a teal header/icon/top edge; informal evidence gets coral.
  Keep authority labels explicit and retain neutral styling for procedures or
  unavailable metadata. These accents do not indicate integrity verification.
- Both themes share the full inset selection marker, quieter navigation counter,
  authority-colored evidence headers/icons/top edges, 10px authority/version labels and
  27px rule summaries (increasing on wide screens). Keep these component rules
  outside theme selectors; vary palette tokens between themes.
- Cormorant Garamond 500 for display headings and rule summaries, as the reference's
  public substitute for its licensed display face. Inter 400/500/600 for controls
  and body. Both are bundled locally; no runtime font network dependency.
- Main explanation and exact quotes are 14px on desktop, with generous line height.
  Use small captions only for secondary metadata, not essential findings or actions.
- Prefer 4/8/12/16/24/32px spacing, 8px controls/cards, 12px dialogs. Most depth comes
  from surfaces and borders. Reserve a shadow for modal elevation.

## Layout and reusable patterns

- Desktop: quiet persistent navigation, compact office/role header, queue on the
  left, investigation on the right. Source passages sit side by side where readable.
- Medium widths: reduce navigation, then stack evidence cards rather than shrinking
  quotes. At 760px and below, show either the queue or selected finding, with an
  explicit back action. Never require horizontal page scrolling.
- Keep the queue scrollable while the investigation is open. `viewState.ts` owns
  URL parsing and serialization: office, full finding ID and tag, search, status,
  type, severity, sort, active tab, mobile queue/detail pane, auto-refresh and open
  source clause/mode/page/zoom. Browser history and reload must restore this state.
  Notices, shortcut preferences, and unsaved review text stay out of shared URLs.
- Keep the page heading to “Findings.” Avoid promotional sidebar copy, explanatory
  taglines and duplicate footer slogans in the workspace.
- Summary counts use compact 44px bordered surfaces, 21px numbers and readable labels.
  Pair each count with a 16px icon: alert, findings list, and reviewed check.
  Emphasize attention in coral and reviewed in teal. On mobile, use three equal
  columns. Severity/review badges use 12px semibold labels, semantic fills and
  visible borders; keep queue variants compact without losing their status color.
- Office and filter controls use `Select.tsx`, a shared select-only combobox with
  styled trigger and option surfaces. Keep the native keyboard conventions:
  arrows/Home/End move the active option, typing finds a label, Enter/Space selects,
  Escape cancels, and Tab closes without trapping focus. Checkmarks mark the selected
  option; active focus and selection remain distinct. Popups stay inside the visible
  content width and flip above the trigger when space below is limited.
- The queue sort control supports severity, newest, oldest, review status and finding
  ID. Default severity order breaks ties by newest first, then a stable identifier.
  Pin even the initially displayed finding in the URL. Sorting and auto-refresh
  preserve that selection and never mutate backend data.
- Show the short finding tag prominently in the detail header and in queue rows.
  Tags use `#` plus the final eight ID characters in uppercase. Search accepts tags
  with or without `#`, full IDs, partial IDs and ordinary evidence text, regardless
  of case. Clicking the header tag copies it and announces success without changing
  search or selection. Animate the fixed-width icon inside the button and tint it
  on success; announce the result to screen readers without adding visible text
  below the tag or moving content. Respect reduced motion. Report clipboard
  failures with an alert icon, tooltip and live announcement. Share URLs contain both
  tag and full ID. Tag-only links resolve against authorized results; ambiguous or
  inaccessible tags must not silently open a different finding.
- Highlight literal, case-insensitive search matches only in review queue titles,
  types, amount scopes, tags and matching excerpts. Keep the detailed investigation
  and source dialogs free of search highlighting. Source-viewer citation highlights
  remain separate from search matches.
  Use the shared `Highlight.tsx` component and theme-aware amber tokens. Preserve
  source text verbatim and render it as React text, never injected HTML. When a
  result matches only an evidence quote or full identifier, show a short matching
  excerpt in the queue so its inclusion is clear. Hash-prefixed queries mark only
  identifiers. Clearing search removes the highlights.
- Use named, real icons from Lucide. Icon-only actions need accessible labels.
  Unknown values must say they are unavailable instead of inventing metadata.
- `components.tsx`: buttons via shared CSS, severity/review badges, empty/loading/error
  states, native modal dialogs. `FindingDetail.tsx`: evidence cards, source inspector,
  chronology, history and review actions. Reuse these views in later answer workflows.
- Every screen needs explicit loading, empty, unavailable and permission states.
  Never replace a failed request with sample success data or fake counters.

## Meaning must stay explicit

Keep these concepts distinct in both copy and appearance:

- **Severity** describes the finding's importance. A high-severity finding remains
  high severity after someone acknowledges it.
- **Review state** is Open, Acknowledged, Resolved or Dismissed. Acknowledging leaves
  the issue available for follow-up. Resolving records the reviewer's reason; it
  does not correct Slack, edit policy, or prove compliance.
- **Authority** comes from trusted source metadata: policy, procedure or informal.
  Extracted claims and model modes cannot elevate source authority.
- **Extraction mode** is live, cached or replay. Multiple evidence passages may
  have different modes. Show the real values, not a single global “live” badge.
- **Integrity** is separate from all of these. This slice displays signed snapshot
  references but does not run verification. Say “verification not run here”; do not
  show a green verification check. Later verification UI must preserve
  passed/failed/not-checked distinctions.
- **Dates** distinguish publication, applicability/effective time, ingestion/knowledge
  time and detection. All displayed times are UTC. Chronology follows explicit
  supersession links; it must not infer replacement from a higher version number.

Render money from integer cents and preserve inclusive/exclusive boundaries. The
stale-guidance example is **above $25,000 and up to $50,000**. Join bounds with words
instead of a comma after the amount (for example, **above $0 and up to $25,000**).
Do not shorten it to an
ambiguous “$25k–$50k” or include exactly $25,000.

Source quotations stay verbatim. Clearly identify their version and location. The
source inspector offers metadata, a browser viewer, an original download, and
optional technical identifiers. `SourcePreview.tsx` loads the authorized original
through the existing bridge. PDF.js renders the cited page locally and highlights
text runs containing a unique quote, allowing for whitespace and ligatures. The
caption says “Highlighted lines contain the cited passage”; this is a location aid,
not an integrity check. Missing/repeated matches receive an explicit message, not
an invented highlight. Provide page controls, zoom, return-to-citation and readable
page text. Saved Slack JSON is rendered as text with the matching passage marked.
The viewer, worker, fonts, character maps and WebAssembly resources are self-hosted.

## Interaction and access

- Reviews require a nonblank reason. Show pending state, prevent duplicate clicks,
  and acknowledge success only after the server confirms it.
- Keep the form and reason after an error. A failed/uncertain response must not
  silently retry a write. Refresh the finding before retrying an uncertain outcome.
- Send the snapshot being reviewed. Conflicts ask the operator to refresh. Stored
  review events appear after reload and remain associated with their snapshot.
- Reader mode has no review actions; the bridge and office API also enforce this.
  Restricted findings are absent from unauthorized results, not shown as redacted
  teasers. Office changes clear previous-office evidence while loading.
- Dialogs use native modal semantics, trap focus, support Escape, restore focus on
  close, and prevent background scrolling. A click that starts and ends outside
  the dialog dismisses it; clicks inside and drags from inside must not. Preserve
  pending-save guards. Reserve the root scrollbar gutter to keep background content
  stationary when opening or closing a dialog. Tab panels support arrow/Home/End keys.
  Direct E/T/H shortcuts focus and select the tab using its active underline,
  without the rectangular outline. Restore the normal focus ring when using Tab,
  arrow/Home/End navigation, or returning focus later; do not suppress tab focus
  indicators globally.
- Provide visible focus indicators, a skip link, labels on all controls, text with
  semantic colors, status/error announcements, and reduced-motion support.
  Queue cards use an inset focus outline so scrolling and J/K navigation never
  clip the ring at the list's edges.
- Keyboard shortcuts are discoverable through the header button, `?`, or `F1`.
  Desktop controls show compact, muted keycaps: `/` in search, changing to `Esc`
  while the input is focused; `S` for sort; `O` for office; `E`/`T`/`H` beside the
  detail tabs; and `A`/`R`/`D` on review actions. Show `J`/`K` once beside the queue
  result count. Use the shared `ShortcutHint` component; hide these hints on mobile
  and when single-key shortcuts are disabled. Keep accessible control labels free
  of decorative keycap text and expose shortcuts through `aria-keyshortcuts`.
  The header also shows `F1` for Shortcuts and `Shift+R` for Auto-refresh. F1 remains
  available, with its hint, when single-key shortcuts are disabled.
  Hide the header keyboard button at mobile widths; do not replace it with an
  unexplained keyboard icon. Physical-keyboard shortcuts remain available.
  Single-key shortcuts can be disabled in that panel; save only this boolean
  preference in local storage. Pause them while typing, during composition, in
  dropdowns and in open dialogs. Preserve browser/assistive modifier combinations.
  `F1` can also open help from a focused search/filter control.
  Escape in search returns focus to the selected queue card without clearing the
  query or changing the URL. If no result is selected, focus the workspace instead.
  Keep this available when single-key shortcuts are disabled; preserve composition
  and modified key combinations.
- Shortcuts: `/` search, `J`/`K` next/previous finding, `A` acknowledge, `R` resolve,
  `D` dismiss, `E` evidence, `T` chronology, `H` review history, `S` sort, `O` office,
  `U` opens PDF upload when permitted, and `Shift+R` toggles auto-refresh. Navigation
  moves keyboard focus to the selected item.
  Review shortcuts open a reason form; they never save a decision immediately.
  In that form, `Ctrl+Enter` or `⌘+Enter` submits only when the reason is nonblank
  and a save is not already in progress. Escape dismisses the form without saving.
- The local bridge uses server-configured demo credentials and loopback hostnames.
  Browser code must never import server modules, receive bearer tokens, or carry
  credentials in Vite variables, source URLs, local storage or source control.
- Auto-refresh is a pressed-state toggle, initially off, with a 10-second polling
  cadence. Keep it stoppable while requests are pending. Pause in hidden tabs,
  during editing, while a dropdown is open, and while source/review/help dialogs
  are open. Preserve the selected finding, tab and filters throughout polling.

## Review this slice before expanding

Walk through this on a normal laptop and the actual projector:

1. Find the stale guidance without knowing its finding ID.
2. Explain which amount boundaries are affected and which source is authoritative.
3. Read both exact quotes without opening another screen.
4. Inspect the policy source and download its original.
5. Explain the difference between the February effective date, March Slack date and
   the date Meridian ingested the material.
6. Acknowledge with a reason, refresh, and locate that reason in history.
7. Distinguish severity, reviewer state, extraction mode and integrity status.

Target roughly one minute for the primary investigation once the screen is familiar.
Judge clarity, not speed alone. Record any changes to type sizes, spacing, terminology
or the evidence arrangement here before extending either workspace.

## Validation recorded for this implementation

- Production TypeScript/Vite build and focused bridge/presentation tests.
- Full offline backend suite, including history persistence, restricted finding
  access, and stale snapshot rejection.
- Browser checks against a separate QA database: persisted review and reload,
  filters, source metadata, chronology, office switch, empty search, unavailable
  finding, reader restrictions, modal dismissal/focus restoration, and desktop/mobile
  layout. No hosted model calls are needed to operate this workspace.
- The physical projector has not been tested; that remains a team rehearsal check.

The controls refinement was additionally checked for tag searches, actual queue
ordering, dropdown type-ahead and arrow navigation, shortcut suppression during
typing, the persistent disable preference, mobile popup bounds, and keyboard review
submission against a separately configured QA database. Confirm the QA service's
`/health` reports the intended database before testing writes; office-specific
`DHAKA_DB_PATH` / `FRANKFURT_DB_PATH` settings override generic `DB_PATH` settings.

The sharing/source-viewer refinement passed all 21 frontend tests and the production
build. Browser checks covered clipboard confirmation, stable selection after sort,
shared filters/tabs/source location and zoom, tag-only and unknown-tag links,
10-second auto-refresh and stopping polling, and mobile layouts without horizontal
overflow. Original PDF and saved Slack previews were checked in the built server,
including the locally served PDF worker and citation highlights. These checks used
read-only requests against the existing demo data.

The appearance/dialog refinement passed the production build and all 21 frontend
tests. Browser checks covered saved theme reload, keyboard theme selection,
simulated system theme changes, dark-mode PDF rendering, 320px/390px mobile
layouts, fixed-size copy success/failure feedback, outside-click dismissal,
inside-click/drag protection, focus restoration and zero horizontal movement of
the workspace when the shortcuts dialog opens.

The dark-theme polish was checked on desktop and 320px/390px mobile layouts,
including raised source dialogs, original PDF rendering and switching back to the
light palette. Sampled dark text combinations exceeded 4.5:1 contrast, including
primary and pressed button labels; input boundaries and focus accents exceeded
3:1 in the targeted palette checks.

## Sources and PDF ingestion

- Use the same navigation, theme tokens, styled Select, Modal and keyboard hints.
  Mobile navigation exposes Findings and Sources; hints remain hidden at mobile
  widths. `/` searches sources and Escape leaves search without clearing it.
- Keep the library and recent processing activity distinct. Source rows show their
  real type, authority, version, category and dates. Show restricted access clearly.
  Library inspection opens the authorized original without fabricating a citation
  highlight. An actual finding still opens at its cited passage.
- URL state includes source search/type/sort, selected processing job, open document
  and page/zoom; source-filtered Findings links retain the selected source. Unsent
  metadata, files, consent and credentials stay out of the URL.
- Upload is a native modal with a fixed header/footer and a separately scrollable
  form. Account for the actual header/footer height rather than viewport arithmetic
  that can clip submission controls. Keep validation/error space stable and preserve
  the draft when dismissing or when a request fails. Single-key shortcuts must not
  fire while editing. Ctrl/Meta+Enter uses native form validation.
- Show trusted name, version, category, authority, publication/effective dates and
  applicability as explicit form inputs. Additional access, end date and scope labels
  belong under Additional settings. Do not infer authority or replacement from text.
  Whole-version replacement locks trusted name/category/scope, loads actual clause
  IDs and requires a different version and later effective start.
- Check one nonempty PDF, its header and 20 MiB size cap in the browser and bridge.
  Parsing still occurs on the backend; an accepted request is not a processed source.
  Explain text-only support, hosted processing and office boundaries before submit.
  Hosted consent starts unchecked. Approved local endpoints disable hosted egress.
- Enable upload only with a server-configured office uploader credential in reviewer
  mode. The bridge stamps tenant, office, PDF/general-policy subject and live mode;
  it never accepts a browser-selected identity. Reader restrictions remain enforced
  on the server. No model calls or bearer credentials belong in browser code.
- Render durable job states, review reasons and failures as received. Processed is
  not a compliance certificate. Successful queueing enables auto-refresh with an
  explicit notice: three seconds while active, ten seconds otherwise, paused during
  editing, hidden tabs and dialogs. The toggle remains stoppable during requests.
  Never automatically retry a POST after an uncertain response. Comparison retry
  preserves originals and prior assessments; it does not rerun failed extraction.

The Sources implementation passed 39 frontend tests, the production build and 126
backend tests. Browser checks used isolated office databases and a controlled local
model endpoint, with no paid calls. Checks covered real upload and explicit policy
replacement, original PDF viewing, reader restrictions, office switching, preserved
form/file/consent after a request failure, manual resubmission, corrupt PDFs and
model failure, keyboard search/Escape/upload, outside dismissal without width shift,
and 320px/390px/768px layouts in the shared light/dark palette. A failure check also
found and fixed premature staged-file deletion during model retries, with regression
coverage for recovery and exhausted attempts. Physical-projector and actual hosted
model quality still require rehearsal.


## Verification and lineage

- Use the shared navigation, themed controls, Select, Modal, source viewer and key
  hints. Keep the page heading to “Verification.” The heading wraps at narrow widths;
  do not squeeze the Share button outside the viewport.
- Entry points are Trace evidence from a finding and Verify source from source
  inspection. The workspace also opens source copies, stored answers by ID and
  imported answer bundles. Do not imply that a source-copy check verifies a finding
  snapshot signature or an answer, or that general-policy Q&A now exists.
- Keep Passed, Failed and Not checked independent, with a labelled icon, semantic
  fill and consistent badge height. Counts summarize these categories, not an
  aggregate claim of correctness. Disclose skipped/withheld evidence even when a
  broader check reports Passed. Lineage nodes remain neutral recorded provenance.
- Verification is explicit. Do not poll, replace a selected file, flash disabled
  controls during background reads, or silently submit a check after selecting a
  file. Pending checks prevent duplicate submissions; changing evidence aborts the
  obsolete request and discards its result. Keep errors and selected files available
  for retry. Report export preserves the actual server result.
- Group the trace into conclusions, statements, passages and sources, with a selected
  node inspector and direct connections. Keep long lists bounded and scrollable.
  Keyboard focus rings stay inside node cards. Show a source name and version as
  distinct elements; render quotations verbatim without search highlights. A selected
  node persists when searching, including when it is outside the filtered nodes.
- Source inspection opens at the recorded page and passage; store its passage node
  in the URL independently of the selected graph node. Outside click/Escape close
  inspection, preserve the page width and restore focus. Uploaded-bundle topology is
  explicitly supplied data, not verified local history, and cannot open local source
  records through a claimed ID.
- URL state includes kind/target, node, passage, search, check filter and source
  location. File bytes, filenames, unsaved answer IDs and check results stay out of
  shared links. Explain that imported files need to be selected again after reload.
- `/` searches lineage, Escape leaves search, J/K move visible nodes in visual order,
  L focuses lineage, and V runs a ready check (or opens the current finding's trace
  from Findings). Show keycaps for the primary actions on desktop only. Preserve
  F1, theme/office shortcuts and the existing shortcut preference.
- Header finding tags and Share view copy with a fixed-size in-button icon animation
  and a screen-reader announcement. Clipboard success/failure must not insert visible
  text beneath controls or move the layout.
- The bridge uses the configured reader/reviewer principal for verification, never
  an uploader/service credential. Verification POSTs are read operations but still
  require the workspace origin/header. Allowlist only the source/bundle and lineage
  routes; bound bodies to 20 MiB and keep bearer credentials on the server.

Verification was checked against a separate replay-backed office with real signed
records and real HTTP verification: original, metadata-only and changed PDFs;
original, altered-answer and undisclosed-passage bundles; stored answer export;
reader access; invalid files/IDs; shared source inspection; clipboard confirmation;
keyboard search/navigation; modal dismissal and stable page width; cancelled
checks discarding late responses; long filenames and clipboard-denial feedback. Both themes fit
320, 390, 760, 1024 and 1440px widths. No paid calls or resets of the working office
sources were needed for these checks.
