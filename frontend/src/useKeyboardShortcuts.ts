import { useEffect, useState } from "react";
import { shortcutForKey, type ShortcutAction } from "./shortcuts";

const preferenceKey = "meridian.keyboardShortcuts.enabled";
export function useShortcutPreference() {
  const [enabled, setEnabled] = useState(() => {
    try {
      return localStorage.getItem(preferenceKey) !== "false";
    } catch {
      return true;
    }
  });
  return [
    enabled,
    (value: boolean) => {
      setEnabled(value);
      try {
        localStorage.setItem(preferenceKey, String(value));
      } catch {
        /* Optional preference storage. */
      }
    },
  ] as const;
}

export function useKeyboardShortcuts(
  enabled: boolean,
  actions: Partial<Record<ShortcutAction, () => void>>,
) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (
        event.defaultPrevented ||
        event.repeat ||
        event.isComposing ||
        document.querySelector("dialog[open]")
      )
        return;
      const element = event.target instanceof Element ? event.target : null;
      if (
        element?.closest(
          "input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='combobox'], [role='listbox']",
        )
      )
        return;
      const action = shortcutForKey(event, enabled);
      if (action && actions[action]) {
        event.preventDefault();
        actions[action]!();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, actions]);
}
