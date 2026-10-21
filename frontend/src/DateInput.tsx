import { useEffect, useId, useLayoutEffect, useRef, useState, type InputHTMLAttributes, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Clock3 } from "lucide-react";
import { addDays, calendarLabel, monthDays, pickerValue, shiftMonth, timeMinutes, timeSlots, timeValid, todayKey, validDate } from "./datePicker";
import "./datePicker.css";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { type?: "date" | "datetime-local" };

/** Native form values and validation with an explicit, themed selection dialog. */
export default function DateInput({ type = "date", onClick, onKeyDown, ...props }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const generatedId = useId();
  const fieldId = props.id || generatedId;
  const [open, setOpen] = useState(false);
  const timed = type === "datetime-local";
  function show() {
    if (input.current?.matches(':disabled') || props.readOnly) return;
    setOpen(true);
  }
  function close(restore = true) {
    setOpen(false);
    if (restore) input.current?.focus({ preventScroll: true });
  }
  function commit(value: string) {
    const field = input.current!;
    // Use the native setter and a real input event so React's existing controlled
    // onChange handlers receive the exact same format as a native date input.
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
    close();
  }
  return <span className="date-input-control">
    <input {...props} id={fieldId} ref={input} type={type} className={`date-input-field ${props.className || ""}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? `${fieldId}-picker` : undefined}
      onClick={event => { onClick?.(event); if (event.defaultPrevented || props.readOnly) return; event.preventDefault(); event.currentTarget.focus({ preventScroll: true }); show(); }}
      onKeyDown={event => {
        onKeyDown?.(event);
        if (event.defaultPrevented || event.nativeEvent.isComposing) return;
        if ((event.altKey && event.key === "ArrowDown") || event.key === "F4") { event.preventDefault(); event.stopPropagation(); show(); }
      }} />
    <CalendarDays className="date-input-icon" size={16} aria-hidden="true" />
    {open && input.current && createPortal(<DatePicker anchor={input.current} value={input.current.value} pickerId={`${fieldId}-picker`} timed={timed} min={input.current.min} max={input.current.max} step={input.current.step} onClose={close} onApply={commit} />, input.current.closest("dialog") || document.body)}
  </span>;
}

export function DatePicker({ anchor, value, pickerId, timed, min = "", max = "", step = "", label, onClose, onApply }: {
  anchor: HTMLElement; value: string; pickerId: string; timed: boolean;
  min?: string; max?: string; step?: string; label?: string;
  onClose: (restore?: boolean) => void; onApply: (value: string) => void;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const grid = useRef<HTMLTableElement>(null);
  const monthButton = useRef<HTMLButtonElement>(null);
  const timeList = useRef<HTMLDivElement>(null);
  let initial = validDate(value.slice(0, 10)) ? value.slice(0, 10) : todayKey();
  if (validDate(min.slice(0, 10)) && initial < min.slice(0, 10)) initial = min.slice(0, 10);
  if (validDate(max.slice(0, 10)) && initial > max.slice(0, 10)) initial = max.slice(0, 10);
  const [day, setDay] = useState(initial);
  const [cursor, setCursor] = useState(initial);
  const [month, setMonth] = useState(initial);
  const [time, setTime] = useState(value.includes("T") ? value.split("T")[1] : "09:00");
  const [timeCursor, setTimeCursor] = useState(Math.min(47, Math.floor(timeMinutes(time) / 30)));
  const [chooseMonth, setChooseMonth] = useState(false);
  const [year, setYear] = useState(initial.slice(0, 4));
  const [position, setPosition] = useState({ left: 0, top: 0, ready: false });
  const today = todayKey();
  const candidate = pickerValue(day, time, timed);
  const probe = document.createElement("input");
  probe.type = timed ? "datetime-local" : "date";
  probe.min = min; probe.max = max; probe.step = step;
  probe.value = candidate;
  const canApply = !!candidate && probe.validity.valid;
  const title = calendarLabel(month, { month: "long", year: "numeric" });
  const days = monthDays(month);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const choosingMonth = useRef(chooseMonth); choosingMonth.current = chooseMonth;

  useLayoutEffect(() => {
    const popup = root.current!;
    popup.showPopover?.();
    function place() {
      const rect = anchor.getBoundingClientRect(), bounds = popup.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = viewport?.offsetLeft || 0, topEdge = viewport?.offsetTop || 0;
      const width = Math.min(document.documentElement.clientWidth, viewport?.width || window.innerWidth);
      const height = viewport?.height || window.innerHeight;
      const top = rect.bottom + 8 + bounds.height <= topEdge + height - 8 ? rect.bottom + 8 : rect.top - bounds.height - 8;
      setPosition({ left: Math.max(leftEdge + 8, Math.min(rect.left, leftEdge + width - bounds.width - 8)), top: Math.max(topEdge + 8, Math.min(top, topEdge + height - bounds.height - 8)), ready: true });
    }
    place();
    const observer = new ResizeObserver(place); observer.observe(popup);
    window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place); window.visualViewport?.addEventListener("scroll", place);
    function outside(event: PointerEvent) {
      if (!popup.contains(event.target as Node) && !anchor.contains(event.target as Node)) closeRef.current(false);
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape" || event.isComposing) return;
      // Capture before an enclosing upload dialog can treat Escape as its cancel.
      // This also covers the frame before focus enters the calendar.
      event.preventDefault(); event.stopPropagation();
      if (choosingMonth.current) { setChooseMonth(false); requestAnimationFrame(() => monthButton.current?.focus()); }
      else closeRef.current();
    }
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", escape, true);
    requestAnimationFrame(() => {
      (grid.current?.querySelector<HTMLButtonElement>('[tabindex="0"]:not(:disabled)') || monthButton.current)?.focus({ preventScroll: true });
      const selected = timeList.current?.querySelector<HTMLElement>('[tabindex="0"]');
      if (selected && timeList.current) { timeList.current.scrollTop = selected.offsetTop - timeList.current.offsetTop - 80; timeList.current.scrollLeft = selected.offsetLeft - timeList.current.offsetLeft - 60; }
    });
    return () => {
      observer.disconnect(); document.removeEventListener("pointerdown", outside, true); document.removeEventListener("keydown", escape, true);
      window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place); window.visualViewport?.removeEventListener("scroll", place);
    };
  }, [anchor]);
  useEffect(() => {
    if (anchor.matches(':disabled') || (anchor instanceof HTMLInputElement && anchor.readOnly)) onClose(false);
  });
  function enabled(value: string) {
    return !!value && (!min || value >= min.slice(0, 10)) && (!max || value <= max.slice(0, 10));
  }
  function focusDay(value: string) {
    if (validDate(min.slice(0, 10)) && value < min.slice(0, 10)) value = min.slice(0, 10);
    if (validDate(max.slice(0, 10)) && value > max.slice(0, 10)) value = max.slice(0, 10);
    setCursor(value); setMonth(value);
    requestAnimationFrame(() => grid.current?.querySelector<HTMLButtonElement>(`[data-date="${value}"]`)?.focus({ preventScroll: true }));
  }
  function moveMonth(count: number) {
    const next = shiftMonth(cursor, count); setMonth(next); setCursor(next); setYear(next.slice(0, 4));
  }
  function calendarKey(event: KeyboardEvent) {
    const weekday = (new Date(`${cursor}T12:00:00Z`).getUTCDay() + 6) % 7;
    const next = event.key === "ArrowLeft" ? addDays(cursor, -1) : event.key === "ArrowRight" ? addDays(cursor, 1) : event.key === "ArrowUp" ? addDays(cursor, -7) : event.key === "ArrowDown" ? addDays(cursor, 7) : event.key === "Home" ? addDays(cursor, -weekday) : event.key === "End" ? addDays(cursor, 6 - weekday) : event.key === "PageUp" ? shiftMonth(cursor, event.shiftKey ? -12 : -1) : event.key === "PageDown" ? shiftMonth(cursor, event.shiftKey ? 12 : 1) : "";
    if (!next) return;
    event.preventDefault(); focusDay(next);
  }
  return <div ref={root} popover="manual" role="dialog" aria-label={label || (timed ? "Choose date and time" : "Choose date")} id={pickerId} className={`date-picker ${timed ? "date-picker-timed" : ""}`}
    style={{ left: position.left, top: position.top, visibility: position.ready ? "visible" : "hidden" }}
    onKeyDown={event => {
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        if (chooseMonth) { setChooseMonth(false); requestAnimationFrame(() => monthButton.current?.focus()); } else onClose();
      }
      if (event.key === "Tab") {
        const stops = [...root.current!.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]')].filter(el => el.tabIndex >= 0 && el.getClientRects().length);
        const index = stops.indexOf(document.activeElement as HTMLElement);
        if (event.shiftKey && index <= 0) { event.preventDefault(); stops.at(-1)?.focus(); }
        else if (!event.shiftKey && index === stops.length - 1) { event.preventDefault(); stops[0]?.focus(); }
      }
    }}>
    <div className="date-picker-body">
      <div className="date-picker-calendar">
        <header className="date-picker-heading">
          <button type="button" className="icon-button" aria-label="Previous month" disabled={month.slice(0, 7) === "0001-01"} onClick={() => moveMonth(-1)}><ChevronLeft size={16} /></button>
          <button ref={monthButton} type="button" className="date-picker-month" aria-expanded={chooseMonth} onClick={() => { setChooseMonth(value => !value); setYear(month.slice(0, 4)); }}><span aria-live="polite">{title}</span><ChevronDown size={12} /></button>
          <button type="button" className="icon-button" aria-label="Next month" disabled={month.slice(0, 7) === "9999-12"} onClick={() => moveMonth(1)}><ChevronRight size={16} /></button>
        </header>
        {chooseMonth ? <div className="date-picker-months">
          <label htmlFor={`${id}-year`}>Year<input id={`${id}-year`} type="number" min={1} max={9999} value={year} onChange={event => { setYear(event.target.value); const next = Number(event.target.value); if (Number.isInteger(next) && next >= 1 && next <= 9999) { const value = `${String(next).padStart(4, "0")}-${month.slice(5, 7)}-01`; setMonth(value); setCursor(value); } }} onBlur={() => setYear(month.slice(0, 4))} /></label>
          <div>{Array.from({ length: 12 }, (_, index) => { const value = `${month.slice(0, 4)}-${String(index + 1).padStart(2, "0")}-01`; return <button type="button" key={index} aria-pressed={month.slice(5, 7) === value.slice(5, 7)} onClick={() => { setChooseMonth(false); focusDay(value); }}>{calendarLabel(value, { month: "short" })}</button>; })}</div>
        </div> : <table ref={grid} className="date-picker-grid" role="grid" aria-label={title} onKeyDown={calendarKey}>
          <thead><tr>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map(name => <th key={name} scope="col"><abbr title={name}>{name.slice(0, 2)}</abbr></th>)}</tr></thead>
          <tbody>{Array.from({ length: 6 }, (_, row) => <tr key={row}>{days.slice(row * 7, row * 7 + 7).map((value, index) => <td key={index} aria-selected={value === day}>{value ? <button type="button" data-date={value} tabIndex={value === cursor ? 0 : -1} disabled={!enabled(value)} aria-label={calendarLabel(value, { dateStyle: "full" })} aria-current={value === today ? "date" : undefined} className={`${value === day ? "is-selected" : ""} ${value.slice(0, 7) !== month.slice(0, 7) ? "outside-month" : ""}`}
            onFocus={() => setCursor(value)} onClick={() => { setDay(value); setCursor(value); setMonth(value); }}>{Number(value.slice(-2))}</button> : null}</td>)}</tr>)}</tbody>
        </table>}
      </div>
      {timed && <section className="date-picker-time" aria-label="Time selection">
        <label htmlFor={`${id}-time`}><Clock3 size={13} />Time (UTC)</label>
        <input id={`${id}-time`} type="text" aria-label="Exact time (UTC)" aria-invalid={!timeValid(time)} value={time} placeholder="HH:mm" maxLength={12} spellCheck={false} onChange={event => setTime(event.target.value)} />
        <div ref={timeList} className="date-picker-slots" role="listbox" aria-label="Times (UTC)" onKeyDown={event => {
          const next = event.key === "ArrowDown" || event.key === "ArrowRight" ? Math.min(47, timeCursor + 1) : event.key === "ArrowUp" || event.key === "ArrowLeft" ? Math.max(0, timeCursor - 1) : event.key === "Home" ? 0 : event.key === "End" ? 47 : -1;
          if (next < 0) return; event.preventDefault(); setTimeCursor(next); timeList.current?.querySelector<HTMLButtonElement>(`[data-time="${timeSlots[next]}"]`)?.focus();
        }}>{timeSlots.map((value, index) => <button key={value} type="button" role="option" data-time={value} aria-selected={time === value || time === `${value}:00` || time === `${value}:00.000`} tabIndex={index === timeCursor ? 0 : -1} onFocus={() => setTimeCursor(index)} onClick={() => setTime(value)}>{value}</button>)}</div>
      </section>}
    </div>
    {!canApply && <p className="date-picker-error" role="status">{!timeValid(time) && timed ? "Use HH:mm or HH:mm:ss.SSS." : "Choose a date and time within the allowed range."}</p>}
    <footer className="date-picker-footer"><button type="button" className="button secondary" onClick={() => onClose()}>Cancel</button><span>{calendarLabel(day, { day: "numeric", month: "short", year: "numeric" })}</span><button type="button" className="button primary" disabled={!canApply} onClick={() => onApply(candidate)}>Apply</button></footer>
  </div>;
}
