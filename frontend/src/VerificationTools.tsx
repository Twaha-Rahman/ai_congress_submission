import { useEffect, useRef } from "react";
import { ArrowDownToLine, ChevronDown } from "lucide-react";
import { downloadJson } from "./verification";

export default function VerificationExports({ items }: { items: { label: string; filename: string; value: unknown }[] }) {
  const root = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node) && root.current) root.current.open = false; };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !root.current?.open) return;
      event.preventDefault(); event.stopPropagation(); root.current.open = false; root.current.querySelector('summary')?.focus();
    };
    const leave = (event: FocusEvent) => { if (!root.current?.contains(event.target as Node) && root.current) root.current.open = false; };
    document.addEventListener('focusin', leave);
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('focusin', leave); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, []);
  if (!items.length) return null;
  return <details ref={root} className="verification-exports">
    <summary className="button secondary"><ArrowDownToLine size={15} />Export<ChevronDown size={14} /></summary>
    <div aria-label="Available exports">{items.map(item => <button key={item.filename} type="button" onClick={() => {
      downloadJson(item.value, item.filename); if (root.current) { root.current.open = false; root.current.querySelector('summary')?.focus(); }
    }}><ArrowDownToLine size={15} /><span>{item.label}<small>JSON file</small></span></button>)}</div>
  </details>;
}
