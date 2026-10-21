import type { InputHTMLAttributes, MouseEvent } from "react";

/** Native date semantics and keyboard editing, with the whole field opening the picker. */
export default function DateInput({ type = "date", onClick, onKeyDown, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { type?: "date" | "datetime-local" }) {
  function open(input: HTMLInputElement) {
    if (input.disabled || input.readOnly || !input.showPicker) return false;
    try { input.showPicker(); return true; } catch { return false; }
  }
  function click(event: MouseEvent<HTMLInputElement>) {
    onClick?.(event);
    if (event.defaultPrevented) return;
    event.currentTarget.focus({ preventScroll: true });
    // Suppress the native icon's second activation only if showPicker succeeded.
    // Unsupported browsers retain their regular input interaction.
    if (open(event.currentTarget)) event.preventDefault();
  }
  return <input {...props} type={type} onClick={click} onKeyDown={event => {
    onKeyDown?.(event);
    if (!event.defaultPrevented && !event.nativeEvent.isComposing && event.altKey && event.key === "ArrowDown" && open(event.currentTarget)) event.preventDefault();
  }} />;
}
