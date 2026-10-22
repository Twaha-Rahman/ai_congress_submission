import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import { DatabaseSync } from "node:sqlite";
import { createAuthStore, sessionCookie } from "./auth.mjs";
import { createApiHandler } from "./api.mjs";

function setup(t) {
  const dir = mkdtempSync(join(tmpdir(), "meridian-auth-"));
  const env = {
    UI_AUTH_DB_PATH: join(dir, "accounts.sqlite"),
    UI_AUTH_KEY_PATH: join(dir, "key"),
    UI_ROLE: "reader",
  };
  let time = 1800000000;
  const store = createAuthStore(env, { now: () => time });
  t.after(() => {
    store.close();
    rmSync(dir, { recursive: true, force: true });
  });
  return {
    dir,
    env,
    store,
    advance: (seconds) => {
      time += seconds;
    },
  };
}
const request = (token) => ({
  headers: { cookie: `meridian_session=${token}` },
});
const options = (overrides = {}) => ({
  username: "alice",
  password: "initial-password",
  role: "reader",
  offices: ["dhaka"],
  readRestricted: false,
  active: true,
  ...overrides,
});
const rejected = (code) => (error) => error.code === code;

test("bootstrap persists a changed password, salts hashes, never exposes passwords, and rotates sessions", async (t) => {
  const { env, store } = setup(t);
  const first = await store.login(" ADMIN ", "admin"),
    second = await store.login("admin", "admin");
  assert.equal(first.user.username, "admin");
  assert.equal(first.user.role, "admin");
  assert.equal("password_hash" in first.user, false);
  const session = store.authenticate(request(first.token));
  await assert.rejects(
    store.changePassword(session, "wrong", "new-admin-password"),
    rejected("invalid_password"),
  );
  const changed = await store.changePassword(
    session,
    "admin",
    "new-admin-password",
  );
  assert.notEqual(changed.token, first.token);
  assert.equal(store.authenticate(request(first.token)), null);
  assert.equal(store.authenticate(request(second.token)), null);
  assert.equal(
    store.authenticate(request(changed.token)).user.id,
    first.user.id,
  );
  const reopened = createAuthStore(env);
  t.after(() => reopened.close());
  await assert.rejects(
    reopened.login("admin", "admin"),
    rejected("invalid_credentials"),
  );
  const admin = await reopened.login("admin", "new-admin-password");
  const alice = await reopened.createUser(admin.user, options());
  const bob = await reopened.createUser(
    admin.user,
    options({ username: "bob" }),
  );
  const db = new DatabaseSync(env.UI_AUTH_DB_PATH);
  const rows = db
    .prepare("SELECT password_hash FROM users WHERE id IN (?,?)")
    .all(alice.id, bob.id);
  assert.equal(
    rows.every((row) => row.password_hash.startsWith("scrypt$")),
    true,
  );
  assert.notEqual(rows[0].password_hash, rows[1].password_hash);
  assert.equal(
    db.prepare("SELECT token_hash FROM sessions LIMIT 1").get().token_hash
      .length,
    64,
  );
  db.close();
  assert.equal(
    JSON.stringify(reopened.listUsers(admin.user)).includes("initial-password"),
    false,
  );
  assert.equal(readFileSync(env.UI_AUTH_KEY_PATH).length, 32);
  assert.match(sessionCookie(changed.token), /HttpOnly; SameSite=Strict/);
  assert.match(sessionCookie(changed.token, true), /; Secure$/);
});

test("accounts enforce privileges, status, office settings, reset revocation and last-admin protection", async (t) => {
  const { store } = setup(t),
    admin = (await store.login("admin", "admin")).user;
  await assert.rejects(
    store.createUser(admin, options({ username: "bad name" })),
    rejected("invalid_input"),
  );
  await assert.rejects(
    store.createUser(admin, options({ password: "short" })),
    rejected("invalid_input"),
  );
  const alice = await store.createUser(admin, options());
  await assert.rejects(
    store.createUser(admin, options({ username: "ALICE" })),
    rejected("conflict"),
  );
  const login = await store.login("alice", "initial-password");
  assert.throws(() => store.listUsers(alice), rejected("forbidden"));
  await assert.rejects(
    store.createUser(alice, options({ username: "intruder" })),
    rejected("forbidden"),
  );
  assert.throws(
    () => store.updateUser(admin, admin.id, { ...options(), role: "reader" }),
    rejected("invalid_input"),
  );
  assert.throws(
    () =>
      store.updateUser(admin, admin.id, {
        role: "reader",
        offices: ["dhaka"],
        readRestricted: false,
        active: true,
      }),
    rejected("conflict"),
  );
  const changed = store.updateUser(admin, alice.id, {
    role: "uploader",
    offices: ["frankfurt"],
    readRestricted: true,
    active: true,
  });
  assert.deepEqual(changed.offices, ["frankfurt"]);
  assert.equal(store.authenticate(request(login.token)), null);
  const newLogin = await store.login("alice", "initial-password");
  await store.resetPassword(admin, alice.id, "reset-password");
  assert.equal(store.authenticate(request(newLogin.token)), null);
  await assert.rejects(
    store.login("alice", "initial-password"),
    rejected("invalid_credentials"),
  );
  const resetLogin = await store.login("alice", "reset-password");
  store.updateUser(admin, alice.id, {
    role: "reader",
    offices: ["dhaka"],
    readRestricted: false,
    active: false,
  });
  assert.equal(store.authenticate(request(resetLogin.token)), null);
  await assert.rejects(
    store.login("alice", "reset-password"),
    rejected("invalid_credentials"),
  );
  const other = await store.createUser(
    admin,
    options({ username: "admin2", role: "admin", readRestricted: false }),
  );
  assert.deepEqual(other.offices, ["dhaka", "frankfurt"]);
  assert.equal(other.readRestricted, true);
  store.updateUser(admin, other.id, {
    role: "admin",
    offices: ["dhaka"],
    readRestricted: false,
    active: false,
  });
  assert.throws(
    () =>
      store.updateUser(admin, admin.id, {
        role: "admin",
        offices: ["dhaka"],
        readRestricted: true,
        active: false,
      }),
    rejected("conflict"),
  );
});

test("sessions expire by idle and absolute limits; logout revokes", async (t) => {
  const { store, advance } = setup(t);
  let login = await store.login("admin", "admin");
  advance(1800);
  assert.equal(store.authenticate(request(login.token)), null);
  login = await store.login("admin", "admin");
  for (let i = 0; i < 24; i++) {
    advance(1799);
    assert.ok(store.authenticate(request(login.token)));
  }
  advance(24);
  assert.equal(store.authenticate(request(login.token)), null);
  login = await store.login("admin", "admin");
  store.logout(store.authenticate(request(login.token)));
  assert.equal(store.authenticate(request(login.token)), null);
});

test("parallel failed logins reserve attempts before password work", async (t) => {
  const { store, advance } = setup(t);
  const results = await Promise.allSettled(
    Array.from({ length: 10 }, () => store.login("missing", "wrong")),
  );
  assert.equal(
    results.filter((result) => result.reason?.code === "invalid_credentials")
      .length,
    8,
  );
  assert.equal(
    results.filter((result) => result.reason?.code === "rate_limited").length,
    2,
  );
  advance(901);
  await assert.rejects(
    store.login("missing", "wrong"),
    rejected("invalid_credentials"),
  );
});

test("HTTP login gates every data route; role headers cannot elevate; credentials stay server-side", async (t) => {
  const { store, env } = setup(t),
    calls = [];
  const server = createServer(
    createApiHandler({
      env,
      authStore: store,
      fetchImpl: async (url, init) => {
        calls.push({ url, init });
        return Response.json({ ok: true });
      },
    }),
  );
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(
    () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(resolve);
      }),
  );
  const base = `http://127.0.0.1:${server.address().port}`;
  const send = (path, method = "GET", body, token = "", headers = {}) =>
    fetch(`${base}/api/${path}`, {
      method,
      headers: {
        "X-Meridian-UI": "1",
        "Content-Type": "application/json",
        ...(token ? { Cookie: `meridian_session=${token}` } : {}),
        ...headers,
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  for (const path of [
    "session",
    "auth/users",
    "dhaka/sources",
    "frankfurt/jobs",
    "gateway/queries/gw_20260101T123456123456",
  ]) {
    assert.equal(
      (
        await send(path, "GET", undefined, "", {
          Authorization: "Bearer ignored",
          "X-Role": "admin",
        })
      ).status,
      401,
    );
  }
  assert.equal(calls.length, 0);
  assert.equal(
    (
      await send(
        "auth/login",
        "POST",
        { username: "admin", password: "admin" },
        "",
        { Origin: "https://attacker.example" },
      )
    ).status,
    403,
  );
  assert.equal(
    (await send("auth/login", "POST", { username: "admin", password: "wrong" }))
      .status,
    401,
  );
  const response = await send("auth/login", "POST", {
    username: "admin",
    password: "admin",
  });
  assert.equal(response.status, 200);
  const cookie = response.headers.get("set-cookie");
  assert.match(cookie, /HttpOnly/);
  const token = cookie.split(";")[0].split("=")[1];
  const session = await response.json();
  assert.equal(session.canManageUsers, true);
  assert.equal(JSON.stringify(session).includes(token), false);
  assert.equal(
    (await send("dhaka/sources", "GET", undefined, token)).status,
    200,
  );
  assert.match(calls.at(-1).init.headers.Authorization, /^Bearer ui1\./);
  const delegation = JSON.parse(
    Buffer.from(
      calls.at(-1).init.headers.Authorization.split(".")[1],
      "base64url",
    ),
  );
  assert.equal(delegation.username, "admin");
  assert.equal(delegation.office, "DHAKA");
  const withdrawal = "dhaka/sources/source_1/withdrawal";
  assert.equal((await send(withdrawal, "GET", undefined, token)).status, 200);
  assert.equal(
    (
      await send(
        withdrawal,
        "POST",
        {
          scope: "version",
          reason: "Retired",
          expected_snapshot: "a".repeat(64),
        },
        token,
      )
    ).status,
    200,
  );
  assert.equal(
    (
      await send(withdrawal, "POST", {}, token, {
        Origin: "https://other.example",
      })
    ).status,
    403,
  );
  assert.equal(
    (await send(withdrawal, "DELETE", undefined, token)).status,
    404,
  );
  for (const role of ["reader", "uploader", "reviewer"]) {
    const created = await send(
      "auth/users",
      "POST",
      options({ username: role, role }),
      token,
    );
    assert.equal(created.status, 201);
    const auth = await store.login(role, "initial-password");
    assert.equal(
      (await send(withdrawal, "GET", undefined, auth.token)).status,
      403,
    );
    assert.equal((await send(withdrawal, "POST", {}, auth.token)).status, 403);
    assert.equal(
      (await send("auth/users", "GET", undefined, auth.token)).status,
      403,
    );
    assert.equal(
      (await send("frankfurt/sources", "GET", undefined, auth.token)).status,
      403,
    );
    assert.equal(
      (await send("dhaka/sources", "GET", undefined, auth.token)).status,
      200,
    );
    assert.equal(
      (await send("dhaka/findings/f_1/reviews", "POST", {}, auth.token)).status,
      role === "reviewer" ? 200 : 403,
    );
    assert.equal(
      (await send("dhaka/activity", "GET", undefined, auth.token)).status,
      role === "reviewer" ? 200 : 403,
    );
    assert.equal(
      (await send("gateway/queries", "POST", { question: "test" }, auth.token))
        .status,
      403,
    );
    const info = await (
      await send("session", "GET", undefined, auth.token)
    ).json();
    assert.equal(info.uploads.dhaka.enabled, role !== "reader");
    assert.equal(info.uploads.frankfurt.enabled, false);
  }
  // The gateway uses privileged internal office connections. A reviewer who
  // cannot read restricted sources must not obtain a richer saved rule result.
  const limited = await store.createUser(
    session.user,
    options({
      username: "limited-reviewer",
      role: "reviewer",
      offices: ["dhaka", "frankfurt"],
    }),
  );
  const limitedLogin = await store.login(limited.username, "initial-password");
  const query = {
    question: "Check approval rules",
    target: { subject: "loan_approval" },
  };
  assert.equal(
    (await send("gateway/queries", "POST", query, limitedLogin.token)).status,
    403,
  );
  assert.equal(
    (await (await send("session", "GET", undefined, limitedLogin.token)).json())
      .comparisons.rules,
    false,
  );
  store.updateUser(session.user, limited.id, {
    role: "reviewer",
    offices: ["dhaka", "frankfurt"],
    readRestricted: true,
    active: true,
  });
  const allowed = await store.login(limited.username, "initial-password");
  assert.equal(
    (await send("gateway/queries", "POST", query, allowed.token)).status,
    200,
  );
  assert.equal(
    (
      await send(
        "gateway/queries/gw_20260101T123456123456",
        "GET",
        undefined,
        limitedLogin.token,
      )
    ).status,
    401,
  );
  assert.equal((await send("auth/logout", "POST", {}, token)).status, 200);
  assert.equal((await send("session", "GET", undefined, token)).status, 401);
});
