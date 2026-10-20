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
- Keep the queue scrollable while the investigation is open. Preserve search,
  office, status, type, severity and selected finding in the URL; browser history
  must continue to work.
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
stale-guidance example is **above $25,000, up to $50,000**. Do not shorten it to an
ambiguous “$25k–$50k” or include exactly $25,000.

Source quotations stay verbatim. Clearly identify their version and location. The
source inspector shows metadata, an original download, and optional technical
identifiers. Do not pretend an exact PDF highlight or cryptographic check was run.

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
  close, and prevent background scrolling. Tab panels support arrow/Home/End keys.
- Provide visible focus indicators, a skip link, labels on all controls, text with
  semantic colors, status/error announcements, and reduced-motion support.
- The local bridge uses server-configured demo credentials and loopback hostnames.
  Browser code must never import server modules, receive bearer tokens, or carry
  credentials in Vite variables, source URLs, local storage or source control.

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
