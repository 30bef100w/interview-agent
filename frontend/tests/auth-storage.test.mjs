import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../lib/auth-storage.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const key = "fa_remember_login";

function storage(initial) {
  const data = new Map(initial === undefined ? [] : [[key, initial]]);
  const localStorage = {
    getItem: k => data.get(k) ?? null,
    setItem: (k, v) => data.set(k, v),
    removeItem: k => data.delete(k),
  };
  const context = { exports: {}, window: {}, localStorage };
  vm.runInNewContext(compiled, context);
  return { api: context.exports, data, localStorage };
}

test("old plaintext password is removed during migration", () => {
  const { api, data } = storage(JSON.stringify({ username: "alice", password: "old-secret" }));
  assert.equal(api.loadRememberedLogin().username, "alice");
  assert.deepEqual(JSON.parse(data.get(key)), { username: "alice" });
});

test("remembering a login saves only a username and opting out removes it", () => {
  const { api, data } = storage();
  api.saveRememberedLogin("alice", true);
  assert.deepEqual(JSON.parse(data.get(key)), { username: "alice" });
  api.saveRememberedLogin("alice", false);
  assert.equal(data.has(key), false);
});

test("invalid legacy data is removed", () => {
  for (const invalid of ["broken", "null", '{"password":"old-secret"}', '{"username":42}']) {
    const { api, data } = storage(invalid);
    assert.equal(api.loadRememberedLogin(), null);
    assert.equal(data.has(key), false);
  }
});

test("failed migration write does not leave the old password behind", () => {
  const { api, data, localStorage } = storage('{"username":"alice","password":"old-secret"}');
  localStorage.setItem = () => { throw new Error("quota exceeded"); };
  assert.equal(api.loadRememberedLogin(), null);
  assert.equal(data.has(key), false);
});

test("server rendering does not access browser storage", () => {
  const context = { exports: {} };
  vm.runInNewContext(compiled, context);
  assert.equal(context.exports.loadRememberedLogin(), null);
  context.exports.saveRememberedLogin("alice", true);
});

test("failed save cannot preserve legacy plaintext credentials", () => {
  const { api, data, localStorage } = storage('{"username":"alice","password":"old-secret"}');
  localStorage.setItem = () => { throw new Error("quota exceeded"); };
  api.saveRememberedLogin("alice", true);
  assert.equal(data.has(key), false);
});
