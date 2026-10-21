import { useState, type FormEvent } from "react";
import { Check, LoaderCircle, LogOut } from "lucide-react";
import { Modal } from "./components";
import { api } from "./api";
import PasswordField, { submitAccountForm } from "./PasswordField";
import { humanize } from "./presentation";
import type { Session } from "./types";

export default function Account({
  session,
  onClose,
  onSessionChange,
  onLogout,
}: {
  session: Session;
  onClose: () => void;
  onSessionChange: (session: Session) => void;
  onLogout: () => Promise<void>;
}) {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState<"password" | "logout" | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const busy = pending !== null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setSaved(false);
    if (password !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setPending("password");
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
      setPending(null);
    }
  }

  async function logout() {
    setPending("logout");
    setError("");
    try {
      await onLogout();
    } catch (e) {
      setError((e as Error).message);
      setPending(null);
    }
  }

  return (
    <Modal
      title="Your account"
      onClose={onClose}
      busy={busy}
      className="account-dialog"
    >
      <div className="dialog-body">
        <div className="account-identity">
          <strong>{session.user.username}</strong>
          <span>{humanize(session.role)}</span>
        </div>
        <form
          className="account-form"
          onSubmit={submit}
          onKeyDown={submitAccountForm}
          aria-busy={pending === "password"}
        >
          <h3>Change password</h3>
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
          {saved && (
            <p className="account-success" role="status">
              <Check size={16} />
              Password changed
            </p>
          )}
          <button className="button primary" type="submit" disabled={busy}>
            {pending === "password" && (
              <LoaderCircle size={16} className="spin" />
            )}
            Change password
          </button>
        </form>
      </div>
      <footer className="dialog-footer">
        <button className="button secondary" onClick={logout} disabled={busy}>
          {pending === "logout" ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <LogOut size={16} />
          )}
          Sign out
        </button>
        <button className="button secondary" onClick={onClose} disabled={busy}>
          Done
        </button>
      </footer>
    </Modal>
  );
}
