import { useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronsUpDown,
  KeyRound,
  LoaderCircle,
  LogOut,
  UserRound,
} from "lucide-react";
import { humanize } from "./presentation";
import type { Session } from "./types";

export default function AccountMenu({
  session,
  onPassword,
  onLogout,
}: {
  session: Session;
  onPassword: () => void;
  onLogout: () => Promise<void>;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [last, setLast] = useState(false);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="sidebar-account account-trigger"
        aria-label={`Your account: ${session.user.username}`}
        title={`${session.user.username} · ${humanize(session.role)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => {
          setLast(false);
          setOpen((value) => !value);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setLast(event.key === "ArrowUp");
            setOpen(true);
          }
        }}
      >
        <UserRound size={17} />
        <span className="account-trigger-name">
          {session.user.username}
          <small>{humanize(session.role)}</small>
        </span>
        <ChevronsUpDown size={14} className="account-trigger-chevron" />
      </button>
      {open &&
        trigger.current &&
        createPortal(
          <AccountPopup
            id={id}
            anchor={trigger.current}
            session={session}
            last={last}
            onClose={(restore) => {
              setOpen(false);
              if (restore) trigger.current?.focus({ preventScroll: true });
            }}
            onPassword={() => {
              setOpen(false);
              trigger.current?.focus({ preventScroll: true });
              onPassword();
            }}
            onLogout={onLogout}
          />,
          document.body,
        )}
    </>
  );
}

function AccountPopup({
  id,
  anchor,
  session,
  last,
  onClose,
  onPassword,
  onLogout,
}: {
  id: string;
  anchor: HTMLButtonElement;
  session: Session;
  last: boolean;
  onClose: (restore: boolean) => void;
  onPassword: () => void;
  onLogout: () => Promise<void>;
}) {
  const root = useRef<HTMLDivElement>(null);
  const signOut = useRef<HTMLButtonElement>(null);
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const close = useRef(onClose);
  close.current = onClose;
  const busy = useRef(pending);
  busy.current = pending;
  useLayoutEffect(() => {
    const popup = root.current!;
    popup.showPopover?.();
    function place() {
      const rect = anchor.getBoundingClientRect(),
        bounds = popup.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = viewport?.offsetLeft || 0,
        topEdge = viewport?.offsetTop || 0;
      const width = Math.min(
        document.documentElement.getBoundingClientRect().width,
        viewport?.width || innerWidth,
      );
      const height = viewport?.height || innerHeight;
      const top =
        rect.bottom + bounds.height + 8 <= topEdge + height - 8
          ? rect.bottom + 8
          : rect.top - bounds.height - 8;
      setPosition({
        left: Math.max(
          leftEdge + 8,
          Math.min(rect.left, leftEdge + width - bounds.width - 8),
        ),
        top: Math.max(
          topEdge + 8,
          Math.min(top, topEdge + height - bounds.height - 8),
        ),
        ready: true,
      });
    }
    function outside(event: PointerEvent) {
      if (
        !busy.current &&
        !popup.contains(event.target as Node) &&
        !anchor.contains(event.target as Node)
      )
        close.current(false);
    }
    function leave(event: FocusEvent) {
      if (
        !busy.current &&
        !popup.contains(event.target as Node) &&
        !anchor.contains(event.target as Node)
      )
        close.current(false);
    }
    place();
    const observer = new ResizeObserver(place);
    observer.observe(popup);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", leave);
    return () => {
      observer.disconnect();
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", leave);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
    };
  }, [anchor, last]);
  useLayoutEffect(() => {
    if (!position.ready) return;
    const items =
      root.current!.querySelectorAll<HTMLButtonElement>("[role=menuitem]");
    items[last ? items.length - 1 : 0]?.focus({ preventScroll: true });
  }, [position.ready, last]);
  useLayoutEffect(() => {
    if (pending) root.current?.focus({ preventScroll: true });
    else if (error) signOut.current?.focus({ preventScroll: true });
  }, [pending, error]);
  async function logout() {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      await onLogout();
    } catch (e) {
      setError((e as Error).message);
      setPending(false);
    }
  }
  return (
    <div
      ref={root}
      id={id}
      role="menu"
      tabIndex={-1}
      aria-label="Account actions"
      aria-busy={pending}
      popover="manual"
      className="account-menu"
      style={{
        left: position.left,
        top: position.top,
        visibility: position.ready ? "visible" : "hidden",
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Escape") {
          event.preventDefault();
          if (!pending) onClose(true);
          return;
        }
        if (event.key === "Tab") {
          event.preventDefault();
          if (pending) return;
          const stops = [
            ...document.querySelectorAll<HTMLElement>(
              'a[href], button:not(:disabled), input:not(:disabled):not([type=hidden]), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
            ),
          ].filter(
            (element) =>
              element.tabIndex >= 0 &&
              element.getClientRects().length &&
              !root.current!.contains(element),
          );
          const index = stops.indexOf(anchor),
            next =
              stops[
                (index + (event.shiftKey ? -1 : 1) + stops.length) %
                  stops.length
              ];
          onClose(false);
          (next || anchor).focus({ preventScroll: true });
          return;
        }
        const items = [
          ...root.current!.querySelectorAll<HTMLButtonElement>(
            "[role=menuitem]:not(:disabled)",
          ),
        ];
        const index = items.indexOf(
          document.activeElement as HTMLButtonElement,
        );
        const next =
          event.key === "ArrowDown"
            ? (index + 1) % items.length
            : event.key === "ArrowUp"
              ? (index - 1 + items.length) % items.length
              : event.key === "Home"
                ? 0
                : event.key === "End"
                  ? items.length - 1
                  : -1;
        if (next >= 0) {
          event.preventDefault();
          items[next]?.focus({ preventScroll: true });
        }
      }}
    >
      <div className="account-menu-identity" role="presentation">
        <strong>{session.user.username}</strong>
        <span>{humanize(session.role)}</span>
      </div>
      <button
        type="button"
        role="menuitem"
        tabIndex={-1}
        className="account-menu-action"
        disabled={pending}
        onClick={onPassword}
      >
        <KeyRound size={16} />
        Change password
      </button>
      <div className="account-menu-divider" role="separator" />
      <button
        ref={signOut}
        type="button"
        role="menuitem"
        tabIndex={-1}
        className="account-menu-action"
        disabled={pending}
        onClick={logout}
      >
        {pending ? (
          <LoaderCircle size={16} className="spin" />
        ) : (
          <LogOut size={16} />
        )}
        <span>{pending ? "Signing out…" : "Sign out"}</span>
      </button>
      {error && (
        <p className="account-menu-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
