import { useEffect, useId, useState } from "react";
import { AlertCircle, Check, Copy } from "lucide-react";

/** Copy stays beside the URL; confirmation never changes the control's dimensions. */
export default function ShareLink() {
  const id = useId();
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state !== "copied") return;
    const timer = setTimeout(() => setState("idle"), 1800);
    return () => clearTimeout(timer);
  }, [state]);
  async function copy() {
    try { await navigator.clipboard.writeText(window.location.href); setState("copied"); }
    catch { setState("failed"); }
  }
  return <div className="share-link">
    <label htmlFor={id}>View link</label>
    <div className="share-link-control">
      <input id={id} readOnly value={window.location.href} onFocus={event => event.currentTarget.select()} />
      <button type="button" className={`icon-button share-link-copy copy-${state}`} onClick={copy} aria-label="Copy link" title={state === "copied" ? "Link copied" : state === "failed" ? "Copy failed; select the link and copy it manually" : "Copy link"} aria-describedby={`${id}-status`}>
        {state === "copied" ? <Check size={18} /> : state === "failed" ? <AlertCircle size={18} /> : <Copy size={18} />}
      </button>
    </div>
    <p id={`${id}-status`} className={`share-link-status ${state === "failed" ? "copy-failed" : "sr-only"}`} role="status">{state === "copied" ? "Link copied" : state === "failed" ? "Could not copy. Select the link and copy it manually." : ""}</p>
  </div>;
}
