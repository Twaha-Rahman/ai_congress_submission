import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, LoaderCircle } from "lucide-react";
import { Modal } from "./components";
import { api } from "./api";
import PasswordField, { submitAccountForm } from "./PasswordField";
import type { Session } from "./types";

export default function Account({
  session,
  onClose,
  onSessionChange,
}: {
  session: Session;
  onClose: () => void;
  onSessionChange: (session: Session) => void;
}) {
  const form = useRef<HTMLFormElement>(null);
  const done = useRef<HTMLButtonElement>(null);
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (saved) done.current?.focus({ preventScroll: true });
    else
      form.current
        ?.querySelector<HTMLInputElement>(
          'input[autocomplete="current-password"]',
        )
        ?.focus({ preventScroll: true });
  }, [saved]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || saved) return;
    if (password !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onSessionChange(
        await api<Session>("auth/password", {
          method: "POST",
          body: JSON.stringify({
            currentPassword: current,
            newPassword: password,
          }),
        }),
      );
      setCurrent("");
      setPassword("");
      setConfirm("");
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Change password"
      onClose={onClose}
      busy={busy}
      className="account-dialog password-dialog"
    >
      <form
        ref={form}
        onSubmit={submit}
        onKeyDown={submitAccountForm}
        className="account-editor"
        aria-busy={busy}
      >
        <div className="dialog-body account-form">
          {saved ? (
            <div className="password-change-success" role="status">
              <Check size={22} />
              <h3>Password changed</h3>
            </div>
          ) : (
            <>
              <input
                type="text"
                name="username"
                value={session.user.username}
                autoComplete="username"
                readOnly
                hidden
              />
              <PasswordField
                label="Current password"
                value={current}
                onChange={setCurrent}
                minimum={1}
                autoComplete="current-password"
                disabled={busy}
              />
              <PasswordField
                label="New password"
                value={password}
                onChange={setPassword}
                disabled={busy}
              />
              <small className="account-hint">8–128 characters</small>
              <PasswordField
                label="Confirm new password"
                value={confirm}
                onChange={setConfirm}
                disabled={busy}
              />
              <div className="account-feedback" role="alert">
                {error}
              </div>
            </>
          )}
        </div>
        <footer className="dialog-footer">
          {saved ? (
            <button
              ref={done}
              type="button"
              className="button primary"
              onClick={onClose}
            >
              Done
            </button>
          ) : (
            <>
              <button
                type="button"
                className="button secondary"
                onClick={onClose}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                className="button primary"
                type="submit"
                disabled={busy || !current || !password || !confirm}
              >
                {busy && <LoaderCircle size={16} className="spin" />}
                {busy ? "Saving…" : "Save password"}
              </button>
            </>
          )}
        </footer>
      </form>
    </Modal>
  );
}
