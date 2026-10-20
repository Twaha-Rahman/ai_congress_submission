# Meridian frontend: first-slice design notes

Status: implemented starting point for a style/UX review, not an approved final
design system. Refine the findings workspace before applying these rules to the
remaining workflows.

## Scope and visual reference

The first slice is **Findings and investigation**: an office-scoped queue,
evidence comparison, source inspection, chronology, and reviewer decisions. Sources
and ingestion, questions, verification, and cross-office audit are later slices.
Do not add navigation destinations until their workflows exist.

`DESIGN.md` was installed using `npx getdesign@latest add claude`. Use its warm
canvas, editorial serif/sans pairing, cream surfaces, hairlines, restrained coral,
and low-shadow layout. Meridian retains its own name and globe mark. The design
reference is inspiration, not a claim of affiliation with Claude or Anthropic.

## Tokens and type

Tokens live in `frontend/src/styles.css`; use variables when extending components.

- Canvas `#faf9f5`, soft surface `#f5f0e8`, selected/card surface `#efe9de`.
- Warm ink `#141413`, body `#3d3d3a`, secondary text `#6c6a64`.
- Hairlines `#e6dfd8`; functional input borders `#8d877c` for stronger contrast.
- Coral `#cc785c` for small accents. Primary buttons use the reference's darker
  coral `#a9583e` so small light labels remain readable.
- Warning ink `#93482f` on `#f6e9e0`; resolved/success ink `#356454` on `#e9efea`.
  These are semantic accents, not alternative page backgrounds.
- Light/dark/system appearance is selected in the header. Default to System and
  persist only the preference in local storage. Apply it before the first paint;
  follow system changes while System is selected. Dark mode uses warm charcoal
  canvas/surfaces and cream text, with brighter coral/teal semantic inks. Use the
  shared variables for controls, popups, dialogs and scrollbars. Original PDF pages
  retain their document colors. Theme preference stays out of shared finding URLs.
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
- Provide visible focus indicators, a skip link, labels on all controls, text with
  semantic colors, status/error announcements, and reduced-motion support.
  Queue cards use an inset focus outline so scrolling and J/K navigation never
  clip the ring at the list's edges.
- Keyboard shortcuts are discoverable through the header button, `?`, or `F1`.
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
  and `Shift+R` toggles auto-refresh. Navigation moves keyboard focus to the selected item.
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
or the evidence arrangement here before implementing the Sources slice.

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
