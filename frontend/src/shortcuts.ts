export const shortcutDescriptions = [
  { keys: "/", label: "Search the current page" },
  { keys: "N", label: "Focus the question form (Questions / Cross-office)" },
  { keys: "U", label: "Upload a policy PDF (when permitted)" },
  { keys: "J / K", label: "Next / previous finding, answer or evidence record" },
  { keys: "A", label: "Acknowledge selected finding" },
  { keys: "R", label: "Resolve selected finding" },
  { keys: "D", label: "Dismiss selected finding" },
  { keys: "E / T / H", label: "Evidence / chronology / review history" },
  { keys: "S", label: "Open sort options" },
  { keys: "O", label: "Open office options" },
  { keys: "Shift + R", label: "Toggle auto-refresh" },
  { keys: "Shift + T", label: "Open theme options" },
  { keys: "V", label: "Open verification from a finding or answer / run the selected check" },
  { keys: "I / L", label: "Check integrity / trace evidence (Verification)" },
  { keys: "Shift + E", label: "Open exports (Questions / Cross-office / Verification)" },
  { keys: "Shift + S", label: "Share view (Questions / Cross-office / Verification)" },
  { keys: "Ctrl / ⌘ + Enter", label: "Submit the open review, upload, question or verification form" },
  { keys: "Esc", label: "Leave search or close a dropdown or dialog" },
  { keys: "? / F1", label: "Show keyboard shortcuts" },
];
export type ShortcutAction =
  | "search"
  | "next"
  | "previous"
  | "acknowledge"
  | "resolve"
  | "dismiss"
  | "evidence"
  | "timeline"
  | "reviews"
  | "sort"
  | "office"
  | "refresh"
  | "theme"
  | "help"
  | "upload"
  | "verify"
  | "lineage"
  | "integrity"
  | "export"
  | "share"
  | "compose";
// Upload opens a form and never sends a file immediately.
export function shortcutForKey(
  event: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean },
  enabled: boolean,
): ShortcutAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (event.key === "F1") return "help";
  if (!enabled) return null;
  const actions: Record<string, ShortcutAction> = {
    "/": "search",
    n: "compose",
    j: "next",
    k: "previous",
    a: "acknowledge",
    r: "resolve",
    d: "dismiss",
    e: "evidence",
    t: "timeline",
    h: "reviews",
    s: "sort",
    o: "office",
    R: "refresh",
    T: "theme",
    "?": "help",
    u: "upload",
    v: "verify",
    l: "lineage",
    i: "integrity",
    E: "export",
    S: "share",
  };
  return actions[event.key] || null;
}
