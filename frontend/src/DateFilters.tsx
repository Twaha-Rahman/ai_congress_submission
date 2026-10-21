import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronDown, Clock3, RotateCcw } from "lucide-react";
import { DatePicker } from "./DateInput";
import type { QuestionDraft } from "./questions";
import "./dateFilters.css";

function displayDate(value: string) {
  const date = new Date(`${value}Z`);
  if (!Number.isFinite(date.getTime())) return "Choose date";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(date) + " UTC";
}

function DateFilter({ label, active, value, defaultLabel, onApply, onReset, icon: Icon }: {
  label: string; active: boolean; value: string; defaultLabel: string;
  onApply: (value: string) => void; onReset: () => void; icon: typeof CalendarDays;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState("");
  function close(restore = true) { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); }
  const text = active ? displayDate(value) : defaultLabel;
  return <div className={`date-filter-control ${active ? "has-custom-date" : ""}`}>
    <button ref={trigger} type="button" className="date-filter-trigger" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? `${id}-picker` : undefined}
      aria-label={`${label}: ${text}`} title={active ? `${label}: ${value.replace("T", " ")} UTC` : `${label}: ${defaultLabel}`}
      onClick={() => { setSeed(active && value ? value : new Date().toISOString().slice(0, 23)); setOpen(true); }}>
      <Icon size={16} /><span className="date-filter-content"><span>{label}</span><strong>{text}</strong></span><ChevronDown size={14} />
    </button>
    {active && <button type="button" className="icon-button date-filter-reset" aria-label={`Reset ${label.toLowerCase()} to ${defaultLabel}`} title={`Reset to ${defaultLabel}`}
      onClick={() => { onReset(); trigger.current?.focus({ preventScroll: true }); }}><RotateCcw size={14} /></button>}
    {open && trigger.current && createPortal(<DatePicker anchor={trigger.current} value={seed} pickerId={`${id}-picker`} label={`Choose ${label.toLowerCase()} (UTC)`} timed step="0.001"
      onClose={close} onApply={next => { onApply(next); close(); }} />, trigger.current.closest("dialog") || document.body)}
  </div>;
}

export default function DateFilters({ draft, onChange }: { draft: QuestionDraft; onChange: (patch: Partial<QuestionDraft>) => void }) {
  return <div className="query-date-controls" role="group" aria-label="Policy and knowledge dates">
    <DateFilter label="Policy date" defaultLabel="Now" active={draft.dated} value={draft.validAt} icon={CalendarDays}
      onApply={value => onChange({ dated: true, validAt: value })} onReset={() => onChange({ dated: false })} />
    <DateFilter label="Knowledge cutoff" defaultLabel="Latest" active={draft.historical} value={draft.knownAt} icon={Clock3}
      onApply={value => onChange({ historical: true, knownAt: value })} onReset={() => onChange({ historical: false, knownAt: "" })} />
  </div>;
}
