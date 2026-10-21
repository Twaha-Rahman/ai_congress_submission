import { DatabaseSync } from "node:sqlite";
import {
  randomBytes,
  randomUUID,
  scrypt,
  scryptSync,
  timingSafeEqual,
  createHash,
  createHmac,
} from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const derive = promisify(scrypt);
const cost = { N: 32768, r: 8, p: 3, maxmem: 64 * 1024 * 1024 };
const root = fileURLToPath(new URL("../../", import.meta.url));
export const cookieName = "meridian_session";
export const sessionSeconds = 12 * 60 * 60;
const idleSeconds = 30 * 60;
export const roleNames = ["admin", "reviewer", "uploader", "reader"];
export class AuthError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
const fail = (status, code, message) => {
  throw new AuthError(status, code, message);
};
const digest = (value) => createHash("sha256").update(value).digest("hex");
const encodeHash = (salt, key) =>
  `scrypt$${salt.toString("base64url")}$${key.toString("base64url")}`;
const publicUser = (row) => ({
  id: row.id,
  username: row.username,
  role: row.role,
  offices: JSON.parse(row.offices_json),
  readRestricted: !!row.read_restricted,
  active: !!row.active,
  createdAt: row.created_at,
  lastLogin: row.last_login,
});
export function capabilities(user) {
  return {
    review: ["admin", "reviewer"].includes(user.role),
    upload: ["admin", "reviewer", "uploader"].includes(user.role),
    audit: ["admin", "reviewer"].includes(user.role),
    manage: user.role === "admin",
  };
}
function password(value) {
  if (typeof value !== "string" || value.length < 8 || value.length > 128)
    fail(422, "invalid_input", "Use a password between 8 and 128 characters.");
  return value;
}
async function hashPassword(value) {
  const salt = randomBytes(16);
  return encodeHash(salt, await derive(value, salt, 64, cost));
}
async function matches(value, encoded) {
  const [kind, salt, key] = encoded.split("$");
  if (kind !== "scrypt" || !salt || !key) return false;
  const expected = Buffer.from(key, "base64url"),
    actual = await derive(value, Buffer.from(salt, "base64url"), 64, cost);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}
function settings(value) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    fail(422, "invalid_input", "Supply the account settings.");
  if (!roleNames.includes(value.role))
    fail(422, "invalid_input", "Choose a valid privilege level.");
  if (
    typeof value.active !== "boolean" ||
    typeof value.readRestricted !== "boolean"
  )
    fail(422, "invalid_input", "Choose account status and source access.");
  if (
    !Array.isArray(value.offices) ||
    !value.offices.length ||
    value.offices.length > 2 ||
    new Set(value.offices).size !== value.offices.length ||
    value.offices.some((office) => !["dhaka", "frankfurt"].includes(office))
  )
    fail(422, "invalid_input", "Choose at least one office.");
  return {
    role: value.role,
    active: value.active,
    offices:
      value.role === "admin"
        ? ["dhaka", "frankfurt"]
        : [...value.offices].sort(),
    readRestricted: value.role === "admin" || value.readRestricted,
  };
}
export function sessionCookie(token, secure = false) {
  return `${cookieName}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${token ? sessionSeconds : 0}${secure ? "; Secure" : ""}`;
}
export function readCookie(req) {
  const cookies = (req.headers.cookie || "")
    .split(";")
    .map((item) => item.trim());
  const value =
    cookies
      .find((item) => item.startsWith(`${cookieName}=`))
      ?.slice(cookieName.length + 1) || "";
  return /^[A-Za-z0-9_-]{43}$/.test(value) ? value : "";
}
export function sameOriginWrite(req) {
  if (
    req.headers["x-meridian-ui"] !== "1" ||
    req.headers["sec-fetch-site"] === "cross-site"
  )
    return false;
  if (!req.headers.origin) return true;
  try {
    const origin = new URL(req.headers.origin);
    return (
      origin.host === req.headers.host &&
      origin.protocol === (req.socket.encrypted ? "https:" : "http:")
    );
  } catch {
    return false;
  }
}

export function createAuthStore(
  env = process.env,
  { now = () => Math.floor(Date.now() / 1000) } = {},
) {
  const path = resolve(
    root,
    env.UI_AUTH_DB_PATH || "runtime/ui/accounts.sqlite",
  );
  const keyPath = resolve(
    root,
    env.UI_AUTH_KEY_PATH || "runtime/auth-bridge/key",
  );
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  mkdirSync(dirname(keyPath), { recursive: true, mode: 0o700 });
  try {
    writeFileSync(keyPath, randomBytes(32), { flag: "wx", mode: 0o600 });
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
  }
  const signingKey = readFileSync(keyPath);
  if (signingKey.length !== 32)
    throw new Error("The UI authentication signing key must contain 32 bytes.");
  const db = new DatabaseSync(path);
  chmodSync(path, 0o600);
  db.exec(`PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,role TEXT NOT NULL,offices_json TEXT NOT NULL,read_restricted INTEGER NOT NULL,active INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,last_login TEXT);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),user_version INTEGER NOT NULL,created_at INTEGER NOT NULL,last_seen INTEGER NOT NULL,expires_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS session_user ON sessions(user_id);
    CREATE TABLE IF NOT EXISTS login_attempts(scope TEXT PRIMARY KEY,failures INTEGER NOT NULL,started_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS account_events(id TEXT PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,created_at TEXT NOT NULL);`);
  const iso = () => new Date(now() * 1000).toISOString();
  const transaction = (callback) => {
    db.exec("BEGIN IMMEDIATE");
    try {
      const result = callback();
      db.exec("COMMIT");
      return result;
    } catch (error) {
      db.exec("ROLLBACK");
      throw error;
    }
  };
  const event = (actor, action, target) =>
    db
      .prepare("INSERT INTO account_events VALUES (?,?,?,?,?)")
      .run(randomUUID(), actor, action, target, iso());
  // Bootstrap only an empty account database. Restart never restores a changed default password.
  transaction(() => {
    if (!db.prepare("SELECT 1 FROM users LIMIT 1").get()) {
      const salt = randomBytes(16),
        hash = encodeHash(salt, scryptSync("admin", salt, 64, cost));
      db.prepare(
        "INSERT INTO users(id,username,password_hash,role,offices_json,read_restricted,active,created_at) VALUES (?,?,?,?,?,?,?,?)",
      ).run(
        randomUUID(),
        "admin",
        hash,
        "admin",
        JSON.stringify(["dhaka", "frankfurt"]),
        1,
        1,
        iso(),
      );
      event("system", "bootstrap", "admin");
    }
  });
  const dummy = encodeHash(
    Buffer.alloc(16),
    scryptSync("unknown-account", Buffer.alloc(16), 64, cost),
  );
  const get = (id) => db.prepare("SELECT * FROM users WHERE id=?").get(id);
  function requireAdmin(user) {
    const current = get(user?.id);
    if (!current?.active || current.role !== "admin")
      fail(403, "forbidden", "Administrator access is required.");
    return current;
  }
  function issue(row) {
    const token = randomBytes(32).toString("base64url"),
      time = now();
    db.prepare("DELETE FROM sessions WHERE expires_at<=? OR last_seen<=?").run(
      time,
      time - idleSeconds,
    );
    db.prepare("INSERT INTO sessions VALUES (?,?,?,?,?,?)").run(
      digest(token),
      row.id,
      row.version,
      time,
      time,
      time + sessionSeconds,
    );
    return { token, user: publicUser(row) };
  }
  function guardLastAdmin(current, next) {
    if (
      current.role === "admin" &&
      current.active &&
      (next.role !== "admin" || !next.active) &&
      db
        .prepare(
          "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1",
        )
        .get().n <= 1
    )
      fail(409, "conflict", "Keep at least one enabled administrator.");
  }
  return {
    keyPath,
    path,
    close() {
      db.close();
    },
    authenticate(req) {
      const token = readCookie(req);
      if (!token) return null;
      const hashed = digest(token),
        time = now();
      const session = db
        .prepare("SELECT * FROM sessions WHERE token_hash=?")
        .get(hashed);
      if (!session) return null;
      const row = get(session.user_id);
      if (
        !row?.active ||
        row.version !== session.user_version ||
        session.expires_at <= time ||
        session.last_seen <= time - idleSeconds
      ) {
        db.prepare("DELETE FROM sessions WHERE token_hash=?").run(hashed);
        return null;
      }
      db.prepare("UPDATE sessions SET last_seen=? WHERE token_hash=?").run(
        time,
        hashed,
      );
      return { user: publicUser(row), sessionHash: hashed };
    },
    async login(username, secret, address = "local") {
      const name =
          typeof username === "string" ? username.trim().toLowerCase() : "",
        valid =
          typeof secret === "string" &&
          secret.length > 0 &&
          secret.length <= 128;
      const scopes = [
          `name:${digest(name.slice(0, 128))}`,
          `address:${digest(address)}`,
        ],
        time = now();
      db.prepare("DELETE FROM login_attempts WHERE started_at<=?").run(
        time - 15 * 60,
      );
      transaction(() => {
        for (const scope of scopes) {
          const attempts = db
            .prepare("SELECT * FROM login_attempts WHERE scope=?")
            .get(scope);
          if (
            attempts &&
            attempts.failures >= (scope.startsWith("name:") ? 8 : 60)
          )
            fail(
              429,
              "rate_limited",
              "Too many sign-in attempts. Try again in 15 minutes.",
            );
        }
        for (const scope of scopes)
          db.prepare(
            "INSERT INTO login_attempts VALUES (?,1,?) ON CONFLICT(scope) DO UPDATE SET failures=failures+1",
          ).run(scope, time);
      });
      const row = db.prepare("SELECT * FROM users WHERE username=?").get(name);
      const verified = await matches(
        valid ? secret : "",
        row?.password_hash || dummy,
      );
      if (!valid || !row?.active || !verified) {
        fail(401, "invalid_credentials", "Username or password is incorrect.");
      }
      return transaction(() => {
        const current = get(row.id);
        if (!current?.active || current.password_hash !== row.password_hash)
          fail(
            401,
            "invalid_credentials",
            "Username or password is incorrect.",
          );
        db.prepare("DELETE FROM login_attempts WHERE scope=?").run(scopes[0]);
        db.prepare(
          "UPDATE login_attempts SET failures=MAX(0,failures-1) WHERE scope=?",
        ).run(scopes[1]);
        db.prepare("UPDATE users SET last_login=? WHERE id=?").run(
          iso(),
          row.id,
        );
        event(row.id, "login", row.id);
        return issue(get(row.id));
      });
    },
    logout(session) {
      if (session) {
        db.prepare("DELETE FROM sessions WHERE token_hash=?").run(
          session.sessionHash,
        );
        event(session.user.id, "logout", session.user.id);
      }
    },
    listUsers(actor) {
      requireAdmin(actor);
      return db
        .prepare("SELECT * FROM users ORDER BY username")
        .all()
        .map(publicUser);
    },
    async createUser(actor, body) {
      requireAdmin(actor);
      if (
        Object.keys(body || {}).some(
          (key) =>
            ![
              "username",
              "password",
              "role",
              "offices",
              "readRestricted",
              "active",
            ].includes(key),
        )
      )
        fail(422, "invalid_input", "Unsupported account settings.");
      const username =
        typeof body.username === "string"
          ? body.username.trim().toLowerCase()
          : "";
      if (!/^[a-z0-9][a-z0-9._-]{2,63}$/.test(username))
        fail(
          422,
          "invalid_input",
          "Use 3–64 letters, digits, periods, underscores or hyphens for the username.",
        );
      const options = settings(body),
        hash = await hashPassword(password(body.password));
      return transaction(() => {
        requireAdmin(actor);
        if (db.prepare("SELECT 1 FROM users WHERE username=?").get(username))
          fail(409, "conflict", "That username is already in use.");
        const id = randomUUID();
        db.prepare(
          "INSERT INTO users(id,username,password_hash,role,offices_json,read_restricted,active,created_at) VALUES (?,?,?,?,?,?,?,?)",
        ).run(
          id,
          username,
          hash,
          options.role,
          JSON.stringify(options.offices),
          Number(options.readRestricted),
          Number(options.active),
          iso(),
        );
        event(actor.id, "create_user", id);
        return publicUser(get(id));
      });
    },
    updateUser(actor, id, body) {
      requireAdmin(actor);
      if (
        Object.keys(body || {}).some(
          (key) =>
            !["role", "offices", "readRestricted", "active"].includes(key),
        )
      )
        fail(422, "invalid_input", "Unsupported account settings.");
      const options = settings(body);
      return transaction(() => {
        requireAdmin(actor);
        const current = get(id);
        if (!current) fail(404, "not_found", "Account not found.");
        guardLastAdmin(current, options);
        if (id === actor.id)
          fail(
            409,
            "conflict",
            "Ask another administrator to change your own access.",
          );
        db.prepare(
          "UPDATE users SET role=?,offices_json=?,read_restricted=?,active=?,version=version+1 WHERE id=?",
        ).run(
          options.role,
          JSON.stringify(options.offices),
          Number(options.readRestricted),
          Number(options.active),
          id,
        );
        db.prepare("DELETE FROM sessions WHERE user_id=?").run(id);
        event(actor.id, "update_access", id);
        return publicUser(get(id));
      });
    },
    async resetPassword(actor, id, secret) {
      requireAdmin(actor);
      if (actor.id === id)
        fail(409, "conflict", "Use Change password for your own account.");
      const hash = await hashPassword(password(secret));
      return transaction(() => {
        requireAdmin(actor);
        if (!get(id)) fail(404, "not_found", "Account not found.");
        db.prepare(
          "UPDATE users SET password_hash=?,version=version+1 WHERE id=?",
        ).run(hash, id);
        db.prepare("DELETE FROM sessions WHERE user_id=?").run(id);
        event(actor.id, "reset_password", id);
        return publicUser(get(id));
      });
    },
    async changePassword(session, currentPassword, newPassword) {
      const row = get(session.user.id);
      if (
        typeof currentPassword !== "string" ||
        currentPassword.length > 128 ||
        !(await matches(currentPassword, row?.password_hash || dummy))
      )
        fail(422, "invalid_password", "Current password is incorrect.");
      password(newPassword);
      if (newPassword === currentPassword)
        fail(422, "invalid_input", "Choose a different password.");
      const hash = await hashPassword(newPassword);
      return transaction(() => {
        const current = get(row.id);
        if (
          !current?.active ||
          current.version !== row.version ||
          !db
            .prepare("SELECT 1 FROM sessions WHERE token_hash=?")
            .get(session.sessionHash)
        )
          fail(401, "unauthenticated", "Sign in again to continue.");
        db.prepare(
          "UPDATE users SET password_hash=?,version=version+1 WHERE id=?",
        ).run(hash, row.id);
        db.prepare("DELETE FROM sessions WHERE user_id=?").run(row.id);
        event(row.id, "change_password", row.id);
        return issue(get(row.id));
      });
    },
    delegationToken(user, office, tenant) {
      const payload = Buffer.from(
        JSON.stringify({
          v: 1,
          sub: user.id,
          username: user.username,
          role: user.role,
          offices: user.offices,
          restricted: user.readRestricted,
          office: office.toUpperCase(),
          tenant,
          iat: now(),
          exp: now() + 45,
        }),
      ).toString("base64url");
      const signed = `ui1.${payload}`;
      return `${signed}.${createHmac("sha256", signingKey).update(signed).digest("base64url")}`;
    },
  };
}
