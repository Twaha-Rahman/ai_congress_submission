import { useEffect, useRef, type ReactNode } from "react";
import {
  AlertCircle,
  Check,
  Circle,
  CircleCheck,
  Clock3,
  Info,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import type { Finding, ReviewState } from "./types";
import { humanize } from "./presentation";

export function AutoRefreshButton({ enabled, refreshing, onToggle, shortcutsEnabled, title }: {
  enabled: boolean; refreshing: boolean; onToggle: () => void;
  shortcutsEnabled: boolean; title: string;
}) {
  return <button className="button secondary refresh-button" onClick={onToggle}
    aria-label="Auto-refresh" aria-pressed={enabled} title={title}
    aria-keyshortcuts={shortcutsEnabled ? "Shift+R" : undefined}>
    <RefreshCw size={15} className={refreshing ? "spin" : ""} />
    <span className="auto-refresh-label">Auto-refresh</span>
    <span className="auto-refresh-toggle" aria-hidden="true"><span /></span>
    <span className="auto-refresh-state">{enabled ? "On" : "Off"}</span>
    {shortcutsEnabled && <ShortcutHint>Shift+R</ShortcutHint>}
  </button>;
}

export function ShortcutHint({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <kbd className={`shortcut-hint ${className}`} aria-hidden="true">
      {children}
    </kbd>
  );
}

export function SeverityBadge({ severity }: { severity: Finding["severity"] }) {
  const Icon = severity === "high" ? AlertCircle : Info;
  return (
    <span className={`badge severity severity-${severity}`}>
      <Icon size={13} />
      {severity === "high"
        ? "High severity"
        : severity === "review"
          ? "Interpretation needed"
          : "Informational"}
    </span>
  );
}
export function ReviewBadge({ state }: { state: ReviewState }) {
  const Icon =
    state === "resolved"
      ? CircleCheck
      : state === "acknowledged"
        ? Clock3
        : state === "dismissed"
          ? Check
          : Circle;
  return (
    <span className={`badge review-state state-${state}`}>
      <Icon size={13} />
      {humanize(state)}
    </span>
  );
}
export function Loading({ label = "Loading findings…" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={23} />
      <p>{label}</p>
    </div>
  );
}
export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon || <Info size={25} />}</div>
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function ErrorState({
  error,
  retry,
  title = "We couldn’t load this workspace",
}: {
  error: string;
  retry: () => void;
  title?: string;
}) {
  return (
    <div role="alert">
      <EmptyState
        icon={<AlertCircle size={25} />}
        title={title}
        action={
          <button className="button secondary" onClick={retry}>
            Try again
          </button>
        }
      >
        {error}
      </EmptyState>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  className = "",
  busy = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  const isBusy = useRef(busy);
  const pressedBackdrop = useRef(false);
  close.current = onClose;
  isBusy.current = busy;
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement as HTMLElement | null;
    dialog.showModal();
    const cancel = (event: Event) => {
      event.preventDefault();
      if (!isBusy.current) close.current();
    };
    dialog.addEventListener("cancel", cancel);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      dialog.removeEventListener("cancel", cancel);
      dialog.close();
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`dialog ${className}`}
      aria-labelledby="dialog-title"
      aria-busy={busy}
      onPointerDown={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        pressedBackdrop.current =
          event.target === event.currentTarget &&
          (event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom);
      }}
      onPointerCancel={() => {
        pressedBackdrop.current = false;
      }}
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const outside =
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom;
        if (
          pressedBackdrop.current &&
          event.target === event.currentTarget &&
          outside &&
          !isBusy.current
        )
          close.current();
        pressedBackdrop.current = false;
      }}
    >
      <header className="dialog-header">
        <h2 id="dialog-title">{title}</h2>
        <button
          autoFocus
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
          disabled={busy}
        >
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
