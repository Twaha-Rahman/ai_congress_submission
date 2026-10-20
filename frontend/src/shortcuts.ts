export const shortcutDescriptions = [
  { keys: "/", label: "Search findings or a finding ID" },
  { keys: "J / K", label: "Next / previous finding" },
  { keys: "A", label: "Acknowledge selected finding" },
  { keys: "R", label: "Resolve selected finding" },
  { keys: "D", label: "Dismiss selected finding" },
  { keys: "E / T / H", label: "Evidence / chronology / review history" },
  { keys: "S", label: "Open sort options" },
  { keys: "O", label: "Open office options" },
  { keys: "Shift + R", label: "Toggle auto-refresh" },
  { keys: "Ctrl / ⌘ + Enter", label: "Submit a review with a reason" },
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
  | "help";
export function shortcutForKey(
  event: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean },
  enabled: boolean,
): ShortcutAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (event.key === "F1") return "help";
  if (!enabled) return null;
  const actions: Record<string, ShortcutAction> = {
    "/": "search",
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
    "?": "help",
  };
  return actions[event.key] || null;
}
