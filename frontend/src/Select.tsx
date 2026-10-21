import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { ShortcutHint } from "./components";

export interface SelectOption {
  value: string;
  label: string;
}

/** Select-only combobox: focus stays on the trigger while options use active-descendant. */
export default function Select({
  label,
  value,
  options,
  onChange,
  icon,
  compact = false,
  triggerRef,
  shortcut,
}: {
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  icon?: ReactNode;
  compact?: boolean;
  triggerRef?: RefObject<HTMLButtonElement | null>;
  shortcut?: string;
}) {
  const id = useId();
  const internalRef = useRef<HTMLButtonElement>(null);
  const trigger = triggerRef || internalRef;
  const popup = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState({
    left: 0,
    top: 0,
    width: 190,
    maxHeight: 280,
  });
  const typed = useRef({ value: "", at: 0 });
  const selected = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );

  function show(index = selected) {
    setActive(index);
    setOpen(true);
  }
  function choose(index: number) {
    onChange(options[index].value);
    setOpen(false);
    trigger.current?.focus();
  }

  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = trigger.current!.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth;
      const width = Math.min(Math.max(rect.width, 190), viewportWidth - 16);
      const menu = popup.current!;
      // Measure at the final width, including wrapped labels, padding and borders.
      // Estimating row heights can leave even a single option one pixel clipped.
      const previousWidth = menu.style.width;
      const previousMaxHeight = menu.style.maxHeight;
      const previousScrollTop = menu.scrollTop;
      menu.style.width = `${width}px`;
      menu.style.maxHeight = "none";
      const desired = Math.min(Math.ceil(menu.getBoundingClientRect().height), 290);
      menu.style.width = previousWidth;
      menu.style.maxHeight = previousMaxHeight;
      menu.scrollTop = previousScrollTop;
      const below = window.innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const flip = below < desired && above > below;
      const height = Math.min(desired, flip ? above : below);
      setPosition({
        left: Math.max(8, Math.min(rect.left, viewportWidth - width - 8)),
        top: flip ? rect.top - height - 6 : rect.bottom + 6,
        width,
        maxHeight: Math.max(40, height),
      });
    }
    function outside(event: PointerEvent) {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !popup.current?.contains(event.target as Node)
      )
        setOpen(false);
    }
    function leave(event: FocusEvent) {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !popup.current?.contains(event.target as Node)
      )
        setOpen(false);
    }
    function scroll(event: Event) {
      if (!popup.current?.contains(event.target as Node)) place();
    }
    place();
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", leave);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", scroll, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", leave);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [open, options.length, trigger]);
  useEffect(() => {
    if (open)
      document
        .getElementById(`${id}-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      event.nativeEvent.isComposing
    )
      return;
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (!open)
        show(
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? options.length - 1
              : selected,
        );
      else
        setActive((index) =>
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? options.length - 1
              : (index +
                  (event.key === "ArrowDown" ? 1 : -1) +
                  options.length) %
                options.length,
        );
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) choose(active);
      else show();
      return;
    }
    if (event.key.length === 1) {
      event.preventDefault();
      const now = Date.now();
      const character = event.key.toLowerCase();
      let query =
        now - typed.current.at > 650
          ? character
          : typed.current.value + character;
      // Repeated letters cycle through options that start with that letter.
      if ([...query].every((char) => char === character)) query = character;
      typed.current = { value: query, at: now };
      const start = open ? active : selected;
      const index = Array.from(
        { length: options.length },
        (_, i) => (start + i + (query.length === 1 ? 1 : 0)) % options.length,
      ).find((i) => options[i].label.toLowerCase().startsWith(query));
      if (index !== undefined) {
        setActive(index);
        setOpen(true);
      }
    }
  }

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`select-trigger ${compact ? "select-compact" : ""}`}
        role="combobox"
        aria-label={label}
        aria-keyshortcuts={shortcut}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${id}-list` : undefined}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        title={`${label}: ${options[selected]?.label}${shortcut ? ` (${shortcut})` : ""}`}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={keyDown}
      >
        {icon}
        <span>{compact ? label : options[selected]?.label}</span>
        {shortcut && <ShortcutHint>{shortcut}</ShortcutHint>}
        <ChevronDown
          size={14}
          className={open ? "select-chevron expanded" : "select-chevron"}
        />
      </button>
      {open &&
        createPortal(
          <div
            ref={popup}
            id={`${id}-list`}
            role="listbox"
            aria-label={label}
            className="select-options"
            style={position}
          >
            {options.map((option, index) => (
              <div
                key={option.value}
                id={`${id}-${index}`}
                role="option"
                aria-selected={option.value === value}
                className={`select-option ${index === active ? "option-active" : ""}`}
                onPointerMove={() => setActive(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(index)}
              >
                <span>{option.label}</span>
                {option.value === value && <Check size={14} />}
              </div>
            ))}
          </div>,
          trigger.current?.closest("dialog") || document.body,
        )}
    </>
  );
}
