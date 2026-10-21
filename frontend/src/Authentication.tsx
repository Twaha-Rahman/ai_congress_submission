import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, LoaderCircle, LogIn } from "lucide-react";
import App from "./App";
import { api, ApiError } from "./api";
import { Loading } from "./components";
import PasswordField, { submitAccountForm } from "./PasswordField";
import ThemeSelect from "./ThemeSelect";
import type { Session } from "./types";

export default function Authentication() {
  const [session, setSession] = useState<Session | null>(null),
    [checking, setChecking] = useState(true),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!session) document.title = "Sign in · Meridian";
  }, [session]);
  const channel = useRef<BroadcastChannel | null>(null),
    generation = useRef(0),
    active = useRef<Session | null>(null);
  active.current = session;
  useEffect(() => {
    const controller = new AbortController(),
      epoch = ++generation.current;
    api<Session>("session", { signal: controller.signal })
      .then((value) => {
        if (epoch === generation.current) {
          setSession(value);
          setError("");
        }
      })
      .catch((e) => {
        if (e.name !== "AbortError" && epoch === generation.current) {
          if (e instanceof ApiError && e.status === 401) setSession(null);
          setError(e instanceof ApiError && e.status === 401 ? "" : e.message);
        }
      })
      .finally(() => {
        if (epoch === generation.current) setChecking(false);
      });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    const expired = () => {
      ++generation.current;
      setSession(null);
      setChecking(false);
      setError("");
    };
    const refresh = () => setRevision((n) => n + 1);
    try {
      channel.current = new BroadcastChannel("meridian-accounts");
      channel.current.onmessage = (event) => {
        if (event.data === "logout") expired();
        else if (event.data === "changed") refresh();
      };
    } catch {
      /* Optional cross-tab synchronization. */
    }
    window.addEventListener("meridian:unauthenticated", expired);
    const focused = () => {
      if (active.current) refresh();
    };
    window.addEventListener("focus", focused);
    return () => {
      window.removeEventListener("meridian:unauthenticated", expired);
      window.removeEventListener("focus", focused);
      channel.current?.close();
      channel.current = null;
    };
  }, []);
  function updated(value: Session) {
    ++generation.current;
    setChecking(false);
    setSession(value);
    setError("");
    channel.current?.postMessage("changed");
  }
  function signedIn(value: Session) {
    const url = new URL(window.location.href);
    if (
      (url.pathname === "/users" && !value.canManageUsers) ||
      (url.pathname === "/activity" && !value.activity) ||
      (url.pathname === "/comparisons" && value.offices.length < 2)
    ) {
      url.pathname = "/findings";
      url.search = "";
      window.history.replaceState({}, "", url);
    }
    updated(value);
  }
  async function logout() {
    await api("auth/logout", { method: "POST" });
    ++generation.current;
    setSession(null);
    setError("");
    channel.current?.postMessage("logout");
  }
  return session ? (
    <App
      key={`${session.user.id}:${session.role}:${session.offices.join(",")}:${session.user.readRestricted}`}
      session={session}
      onSessionChange={updated}
      onLogout={logout}
    />
  ) : (
    <div className="auth-shell">
      <div className="auth-theme">
        <ThemeSelect shortcutsEnabled={false} />
      </div>
      <section className="auth-card">
        <a className="auth-brand" href="/">
          <img src="/meridian.svg" width="36" height="36" alt="" />
          meridian<span>.</span>
        </a>
        {checking ? (
          <Loading label="Checking sign-in…" />
        ) : error ? (
          <>
            <h1>Sign-in unavailable</h1>
            <p role="alert" className="account-error">
              {error}
            </p>
            <button
              className="button secondary"
              onClick={() => {
                setChecking(true);
                setRevision((n) => n + 1);
              }}
            >
              Try again
            </button>
          </>
        ) : (
          <Login onLogin={signedIn} />
        )}
      </section>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      onLogin(
        await api<Session>("auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1>Sign in</h1>
      <form
        className="account-form"
        onSubmit={submit}
        onKeyDown={submitAccountForm}
        aria-busy={busy}
      >
        <div className="account-field">
          <label htmlFor="login-username">Username</label>
          <input
            id="login-username"
            name="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            maxLength={64}
            autoFocus
            disabled={busy}
          />
        </div>
        <PasswordField
          label="Password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          minimum={1}
          disabled={busy}
        />
        <div className="account-feedback" role="alert">
          {error && (
            <>
              <AlertCircle size={16} />
              <span>{error}</span>
            </>
          )}
        </div>
        <button type="submit" className="button primary" disabled={busy}>
          {busy ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <LogIn size={17} />
          )}{" "}
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </>
  );
}
