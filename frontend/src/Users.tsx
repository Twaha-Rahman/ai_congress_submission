import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Check,
  KeyRound,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Users as UsersIcon,
} from "lucide-react";
import { api } from "./api";
import { EmptyState, Loading, Modal, ShortcutHint } from "./components";
import Highlight from "./Highlight";
import PasswordField, { submitAccountForm } from "./PasswordField";
import Select from "./Select";
import { date, humanize } from "./presentation";
import { useKeyboardShortcuts } from "./useKeyboardShortcuts";
import type { Office, Session, UserAccount, UserRole } from "./types";

const roles = [
  { value: "admin", label: "Admin" },
  { value: "reviewer", label: "Reviewer" },
  { value: "uploader", label: "Uploader" },
  { value: "reader", label: "Reader" },
];
const roleHelp: Record<UserRole, string> = {
  admin: "Manage users, review findings, upload and read sources.",
  reviewer: "Review findings, upload sources and view activity.",
  uploader: "Upload sources and ask questions.",
  reader: "Read sources and ask questions.",
};
type Editor =
  | { kind: "create" }
  | { kind: "edit" | "reset"; user: UserAccount };

export default function Users({
  session,
  shortcutsEnabled,
  onAccount,
  onHelp,
}: {
  session: Session;
  shortcutsEnabled: boolean;
  onAccount: () => void;
  onHelp: () => void;
}) {
  const [users, setUsers] = useState<UserAccount[] | null>(null),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0),
    [search, setSearch] = useState(""),
    [role, setRole] = useState("all"),
    [status, setStatus] = useState("all"),
    [editor, setEditor] = useState<Editor | null>(null),
    [notice, setNotice] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!session.canManageUsers) return;
    const controller = new AbortController();
    setBusy(true);
    api<{ users: UserAccount[] }>("auth/users", { signal: controller.signal })
      .then((data) => {
        setUsers(data.users);
        setError("");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [revision, session.canManageUsers]);
  useKeyboardShortcuts(shortcutsEnabled, {
    search: () => searchRef.current?.focus(),
    compose: () => setEditor({ kind: "create" }),
    help: onHelp,
  });
  if (!session.canManageUsers)
    return (
      <EmptyState icon={<UsersIcon />} title="Admin access required">
        Your account cannot manage users.
      </EmptyState>
    );
  const visible = (users || []).filter(
    (user) =>
      (role === "all" || user.role === role) &&
      (status === "all" || (status === "enabled") === user.active) &&
      user.username.toLowerCase().includes(search.trim().toLowerCase()),
  );
  function saved(message: string) {
    setEditor(null);
    setNotice(message);
    setRevision((n) => n + 1);
  }
  return (
    <>
      <header className="page-heading users-heading">
        <div>
          <span className="eyebrow">Administration</span>
          <h1>Users</h1>
        </div>
        <div className="users-heading-actions">
          <button
            className="button secondary shortcuts-button"
            onClick={onHelp}
          >
            Shortcuts<ShortcutHint>F1</ShortcutHint>
          </button>
          <button
            className="button primary"
            onClick={() => {
              setNotice("");
              setEditor({ kind: "create" });
            }}
          >
            <Plus size={17} />
            Create user{shortcutsEnabled && <ShortcutHint>N</ShortcutHint>}
          </button>
        </div>
      </header>
      <section className="users-panel" aria-label="User accounts">
        <div className="users-toolbar">
          <div className="search-input">
            <Search size={17} />
            <input
              ref={searchRef}
              aria-label="Search usernames"
              value={search}
              placeholder="Search usernames…"
              onChange={(e) => setSearch(e.target.value)}
            />
            {shortcutsEnabled && <ShortcutHint>/</ShortcutHint>}
          </div>
          <Select
            label="Privilege"
            value={role}
            onChange={setRole}
            options={[{ value: "all", label: "All privileges" }, ...roles]}
          />
          <Select
            label="Account status"
            value={status}
            onChange={setStatus}
            options={[
              { value: "all", label: "All accounts" },
              { value: "enabled", label: "Enabled" },
              { value: "disabled", label: "Disabled" },
            ]}
          />
          <button
            className="icon-button"
            aria-label="Refresh users"
            title="Refresh users"
            disabled={busy}
            onClick={() => setRevision((n) => n + 1)}
          >
            <RefreshCw size={17} className={busy ? "spin" : ""} />
          </button>
        </div>
        <div className="users-feedback" aria-live="polite">
          {error ? (
            <span className="account-error" role="alert">
              {error}
            </span>
          ) : notice ? (
            <span className="account-success">
              <Check size={16} />
              {notice}
            </span>
          ) : (
            <span>
              {users
                ? `${visible.length} ${visible.length === 1 ? "user" : "users"}`
                : ""}
            </span>
          )}
        </div>
        {!users ? (
          busy ? (
            <Loading label="Loading users…" />
          ) : (
            <button
              className="button secondary"
              onClick={() => setRevision((n) => n + 1)}
            >
              Try again
            </button>
          )
        ) : visible.length === 0 ? (
          <EmptyState icon={<UsersIcon />} title="No matching users">
            Change the search or filters.
          </EmptyState>
        ) : (
          <div className="users-list">
            {visible.map((user) => (
              <article className="user-row" key={user.id}>
                <div className="user-name">
                  <span className="avatar" aria-hidden="true">
                    {user.username.slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <h2>
                      <Highlight text={user.username} query={search} />
                      {user.id === session.user.id && (
                        <span className="user-self">You</span>
                      )}
                    </h2>
                    <span>
                      {user.lastLogin
                        ? `Last sign-in ${date(user.lastLogin, true)}`
                        : "No sign-in yet"}
                    </span>
                  </div>
                </div>
                <div className="user-access">
                  <strong>{humanize(user.role)}</strong>
                  <span>{user.offices.map(humanize).join(" · ")}</span>
                  <span>
                    {user.readRestricted
                      ? "Restricted sources allowed"
                      : "Standard sources"}
                  </span>
                </div>
                <span className={`user-status ${user.active ? "enabled" : ""}`}>
                  {user.active ? "Enabled" : "Disabled"}
                </span>
                <div className="user-actions">
                  {user.id === session.user.id ? (
                    <button className="button secondary" onClick={onAccount}>
                      <KeyRound size={15} />
                      Change password
                    </button>
                  ) : (
                    <>
                      <button
                        className="button secondary"
                        onClick={() => setEditor({ kind: "edit", user })}
                      >
                        <Settings2 size={15} />
                        Edit access
                      </button>
                      <button
                        className="icon-button"
                        aria-label={`Reset password for ${user.username}`}
                        title="Reset password"
                        onClick={() => setEditor({ kind: "reset", user })}
                      >
                        <KeyRound size={17} />
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      {editor && (
        <UserEditor
          editor={editor}
          onClose={() => setEditor(null)}
          onSaved={saved}
        />
      )}
    </>
  );
}

function UserEditor({
  editor,
  onClose,
  onSaved,
}: {
  editor: Editor;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const existing = editor.kind === "create" ? null : editor.user;
  const [username, setUsername] = useState(existing?.username || ""),
    [password, setPassword] = useState(""),
    [confirm, setConfirm] = useState(""),
    [role, setRole] = useState<UserRole>(existing?.role || "reader"),
    [offices, setOffices] = useState<Office[]>(existing?.offices || ["dhaka"]),
    [restricted, setRestricted] = useState(existing?.readRestricted || false),
    [active, setActive] = useState(existing?.active ?? true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const reset = editor.kind === "reset",
    create = editor.kind === "create";
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if ((create || reset) && password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    if (!reset && !offices.length && role !== "admin") {
      setError("Choose at least one office.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const settings = {
        role,
        offices: role === "admin" ? ["dhaka", "frankfurt"] : offices,
        readRestricted: role === "admin" || restricted,
        active,
      };
      await api(
        create
          ? "auth/users"
          : `auth/users/${existing!.id}${reset ? "/password" : ""}`,
        {
          method: create || reset ? "POST" : "PATCH",
          body: JSON.stringify(
            reset
              ? { password }
              : create
                ? { ...settings, username, password }
                : settings,
          ),
        },
      );
      onSaved(
        create
          ? `Created ${username.trim().toLowerCase()}`
          : reset
            ? `Password reset for ${username}`
            : `Access updated for ${username}`,
      );
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <Modal
      title={create ? "Create user" : reset ? "Reset password" : "Edit access"}
      onClose={onClose}
      busy={busy}
      className="account-dialog"
    >
      <form
        onSubmit={submit}
        onKeyDown={submitAccountForm}
        className="account-editor"
        aria-busy={busy}
      >
        <div className="dialog-body account-form">
          <div className="account-field">
            <label htmlFor="account-username">Username</label>
            <input
              id="account-username"
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              readOnly={!create}
              disabled={busy}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              required
              minLength={3}
              maxLength={64}
              pattern="[a-zA-Z0-9][a-zA-Z0-9._\-]{2,63}"
            />
            {create && (
              <small className="account-hint">
                3–64 letters, digits, periods, underscores or hyphens
              </small>
            )}
          </div>
          {(create || reset) && (
            <>
              <PasswordField
                label={create ? "Initial password" : "New password"}
                value={password}
                onChange={setPassword}
                disabled={busy}
              />
              <small className="account-hint">8–128 characters</small>
              <PasswordField
                label="Confirm password"
                value={confirm}
                onChange={setConfirm}
                disabled={busy}
              />
            </>
          )}
          {!reset && (
            <>
              <fieldset disabled={busy} className="account-settings">
                <div className="account-field">
                  <label>Privilege</label>
                  <Select
                    label="Privilege"
                    value={role}
                    onChange={(value) => setRole(value as UserRole)}
                    options={roles}
                  />
                  <small className="account-hint">{roleHelp[role]}</small>
                </div>
                <fieldset
                  className="account-offices"
                  disabled={role === "admin"}
                >
                  <legend>Office access</legend>
                  {(["dhaka", "frankfurt"] as Office[]).map((office) => (
                    <label key={office}>
                      <input
                        type="checkbox"
                        checked={role === "admin" || offices.includes(office)}
                        onChange={(e) =>
                          setOffices(
                            e.target.checked
                              ? [...offices, office]
                              : offices.filter((value) => value !== office),
                          )
                        }
                      />
                      {humanize(office)}
                    </label>
                  ))}
                </fieldset>
                <label className="account-checkbox">
                  <input
                    type="checkbox"
                    checked={role === "admin" || restricted}
                    disabled={role === "admin"}
                    onChange={(e) => setRestricted(e.target.checked)}
                  />
                  Allow restricted sources
                </label>
                <label className="account-checkbox">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={(e) => setActive(e.target.checked)}
                  />
                  Account enabled
                </label>
              </fieldset>
            </>
          )}
          <div className="account-feedback" role="alert">
            {error}
          </div>
        </div>
        <footer className="dialog-footer">
          <button
            type="button"
            className="button secondary"
            onClick={onClose}
            disabled={busy}
          >
            Cancel
          </button>
          <button type="submit" className="button primary" disabled={busy}>
            {busy && <LoaderCircle size={16} className="spin" />}
            {create ? "Create user" : reset ? "Reset password" : "Save access"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
