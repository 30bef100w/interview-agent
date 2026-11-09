import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const env = { NODE_ENV: "development", DEEPASK_LOCAL_PREVIEW: "1", DEEPASK_PREVIEW_USERNAME: "test-preview", DEEPASK_PREVIEW_PASSWORD: "test-only" };
function load(path, globals) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, require, URL, Request, Response, AbortSignal, ...globals };
  vm.runInNewContext(compiled, context);
  return context.exports;
}
function request({ origin = "http://127.0.0.1:57362", host = "127.0.0.1:57362", header = "1" } = {}) {
  const headers = { host };
  if (origin !== null) headers.origin = origin;
  if (header !== null) headers["x-deepask-preview"] = header;
  return new Request(`http://${host}/api/local-preview/session`, { method: "POST", headers });
}
function server(overrides = {}, reply = { access_token: "local-token", user: { username: "test-preview", is_admin: true } }, status = 200) {
  const calls = [];
  const mod = load("../app/api/local-preview/session/route.ts", { process: { env: { ...env, ...overrides } }, fetch: async (url, options) => { calls.push({ url, options }); return Response.json(reply, { status }); } });
  return { ...mod, calls };
}

test("production and an unconfigured development server never expose preview sign-in", async () => {
  for (const overrides of [{ NODE_ENV: "production" }, { DEEPASK_LOCAL_PREVIEW: undefined }, { DEEPASK_PREVIEW_PASSWORD: undefined }]) {
    const app = server(overrides);
    assert.equal((await app.POST(request())).status, 404);
    assert.equal(app.calls.length, 0);
  }
});
test("preview rejects remote hosts, foreign or missing origins, simple cross-site requests and remote backends", async () => {
  for (const options of [{ host: "example.com", origin: "http://example.com" }, { origin: "https://example.com" }, { origin: null }, { header: null }]) {
    const app = server();
    assert.equal((await app.POST(request(options))).status, 403);
    assert.equal(app.calls.length, 0);
  }
  const app = server({ BACKEND_PROXY_URL: "https://example.com" });
  assert.equal((await app.POST(request())).status, 403);
  assert.equal(app.calls.length, 0);
});
test("enabled local preview authenticates through the existing backend and disables caching", async () => {
  const app = server();
  const response = await app.POST(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal((await response.json()).access_token, "local-token");
  assert.equal(String(app.calls[0].url), "http://127.0.0.1:8001/api/auth/login");
  assert.deepEqual(JSON.parse(app.calls[0].options.body), { username: "test-preview", password: "test-only" });
});
test("failed credentials and non-admin accounts cannot create a preview session", async () => {
  for (const app of [server({}, { detail: "invalid password" }, 401), server({}, { access_token: "ordinary-user", user: { is_admin: false } })]) {
    const response = await app.POST(request());
    assert.equal(response.status, 503);
    assert.equal("access_token" in await response.json(), false);
  }
});
test("an empty browser session is automatically signed in, with concurrent requests deduplicated", async () => {
  let token = null, count = 0;
  const local = new Map(), session = new Map();
  const storage = map => ({ setItem: (key, value) => map.set(key, value) });
  const app = load("../lib/admin-preview.ts", {
    require: id => { assert.equal(id, "@/lib/api"); return { setToken: value => { token = value; } }; },
    window: { location: { hostname: "127.0.0.1" } }, process: { env: { NODE_ENV: "development" } },
    localStorage: storage(local), sessionStorage: storage(session),
    fetch: async () => { count++; return Response.json({ access_token: "fresh-token", user: { username: "preview", is_admin: true } }); },
  });
  const [a, b] = await Promise.all([app.startLocalAdminPreview(), app.startLocalAdminPreview()]);
  assert.equal(a && b, true);
  assert.equal(count, 1);
  assert.equal(token, "fresh-token");
  assert.equal(local.get("username"), "preview");
  assert.equal(session.get("deepask-local-preview"), "1");
  assert.equal(local.has("password"), false);
});
