import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import Select from "./Select";

type Theme = "light" | "dark" | "system";
const storageKey = "meridian-theme";
function themePreference(value: string | null | undefined): Theme {
  return value === "light" || value === "dark" ? value : "system";
}

export default function ThemeSelect() {
  const [theme, setTheme] = useState<Theme>(() =>
    themePreference(document.documentElement.dataset.themePreference),
  );
  useEffect(() => {
    const system = window.matchMedia("(prefers-color-scheme: dark)");
    function apply() {
      const resolved =
        theme === "system" ? (system.matches ? "dark" : "light") : theme;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.dataset.themePreference = theme;
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", resolved === "dark" ? "#1e1e20" : "#faf9f5");
    }
    apply();
    system.addEventListener("change", apply);
    return () => system.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    function sync(event: StorageEvent) {
      if (event.key === storageKey || event.key === null)
        setTheme(themePreference(event.newValue));
    }
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return (
    <div className="theme-select">
      <Select
        label="Theme"
        value={theme}
        icon={<Icon size={16} />}
        options={[
          { value: "light", label: "Light" },
          { value: "dark", label: "Dark" },
          { value: "system", label: "System" },
        ]}
        onChange={(value) => {
          const next = themePreference(value);
          setTheme(next);
          try {
            localStorage.setItem(storageKey, next);
          } catch {
            // Still works when storage is unavailable.
          }
        }}
      />
    </div>
  );
}
