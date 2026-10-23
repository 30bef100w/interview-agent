import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function storage() {
  const data = new Map();
  return { data, getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
}

function modules(extra = {}) {
  const localStorage = storage();
  const sessionStorage = storage();
  const cache = new Map();
  const globals = { window: { location: { protocol: "http:", host: "localhost" } }, process: { env: {} }, localStorage, sessionStorage,
    atob, TextDecoder, TextEncoder, AbortSignal, FormData, ...extra };
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const source = readFileSync(new URL(`../${name}.ts`, import.meta.url), "utf8");
    const compiled = ts.transpileModule(source, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    } }).outputText;
    const context = { ...globals, exports: {}, require: id => {
      if (id.startsWith("@/")) return load(id.slice(2));
      if (id === "react") return extra.react;
      throw new Error(`Unexpected import ${id}`);
    } };
    vm.runInNewContext(compiled, context);
    cache.set(name, context.exports);
    return context.exports;
  }
  return { load, localStorage, sessionStorage };
}

const tokenFor = id => `header.${Buffer.from(JSON.stringify({ sub: String(id) })).toString("base64url")}.signature`;

test("submission IDs also work without secure-context randomUUID", () => {
  const { load } = modules({ crypto: { getRandomValues: array => { array.fill(42); return array; } } });
  assert.match(load("lib/api").newSubmissionId(), /^[A-Za-z0-9_-]{1,64}$/);
});

test("422 errors display field messages, not object coercion", async () => {
  const { load } = modules({ fetch: async () => new Response(JSON.stringify({
    detail: [{ loc: ["body", "text"], msg: "Too long" }],
  }), { status: 422 }) });
  await assert.rejects(load("lib/api").api("/test"), error => error.status === 422 && error.message === "text：Too long");
});

test("drafts survive refresh, isolate users and expire", () => {
  const { load, localStorage, sessionStorage } = modules();
  const drafts = load("lib/drafts");
  localStorage.setItem("token", tokenFor(1));
  drafts.saveDraft("code:1:q:python", "my solution");
  assert.equal(drafts.loadDraft("code:1:q:python"), "my solution");
  localStorage.setItem("token", tokenFor(2));
  assert.equal(drafts.loadDraft("code:1:q:python"), null);
  localStorage.setItem("token", tokenFor(1));
  const key = load("lib/api").userStorageKey("fa_draft:code:1:q:python");
  sessionStorage.setItem(key, JSON.stringify({ at: Date.now() - 8 * 86400000, value: "old" }));
  assert.equal(drafts.loadDraft("code:1:q:python"), null);
  assert.equal(sessionStorage.getItem(key), null);
});

function sseHarness(chunks) {
  const events = [];
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
    cancel() { cancelled = true; },
  });
  const { load } = modules({ fetch: async () => new Response(stream, { status: 200 }) });
  return { run: () => load("lib/sse").streamPost("/test", {}, {
    onToken: t => events.push(["token", t]), onDone: d => events.push(["done", d]),
    onError: e => events.push(["error", e]),
  }), events, cancelled: () => cancelled };
}

test("SSE handles chunked CRLF and returns only after a terminal event", async () => {
  const h = sseHarness(['event: token\r', '\ndata: "你"\r\n\r', '\nevent: done\r\ndata: {"message":"ok"}\r\n\r\n']);
  await h.run();
  assert.deepEqual(JSON.parse(JSON.stringify(h.events)), [["token", "你"], ["done", { message: "ok" }]]);
});

test("SSE EOF without done is a visible incomplete outcome", async () => {
  const h = sseHarness(['event: token\ndata: "partial"\n\n']);
  await h.run();
  assert.equal(h.events[0][0], "token");
  assert.equal(h.events[1][0], "error");
  assert.match(h.events[1][1], /尚未确认/);
  assert.equal(h.events.length, 2);
});

test("SSE terminal error stops subsequent events", async () => {
  const h = sseHarness(['event: error\ndata: "failed"\n\nevent: token\ndata: "must not show"\n\n']);
  await h.run();
  assert.deepEqual(h.events, [["error", "failed"]]);
});

test("malformed SSE JSON is not silently swallowed", async () => {
  const h = sseHarness(['event: token\ndata: invalid-json\n\n']);
  await assert.rejects(h.run(), /JSON|Unexpected/);
});

function websocketHarness() {
  const effects = [], sockets = [], timers = new Map(), intervals = new Map();
  let timerId = 0;
  class FakeSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    readyState = 0;
    sent = [];
    constructor() { sockets.push(this); }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { this.drop(1000); }
    open() { this.readyState = 1; this.onopen?.(); }
    drop(code) { this.readyState = 3; this.onclose?.({ code }); }
  }
  const react = { useRef: value => ({ current: value }), useCallback: fn => fn,
    useEffect: fn => effects.push(fn) };
  const h = modules({ react, WebSocket: FakeSocket,
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    setInterval: fn => { const id = ++timerId; intervals.set(id, fn); return id; },
    clearInterval: id => intervals.delete(id),
  });
  const events = [];
  const api = h.load("hooks/useInterviewWebSocket").useInterviewWebSocket("1", {
    onError: message => events.push(message),
  }, true);
  const cleanup = effects.map(fn => fn());
  return { api, sockets, timers, intervals, events, cleanup: () => cleanup.forEach(fn => fn?.()) };
}

test("WebSocket reconnects after sending disconnect, without replaying an answer", () => {
  const h = websocketHarness();
  h.sockets[0].open();
  assert.equal(h.api.sendAnswer("answer", "stable-id", 1), true);
  assert.equal(h.sockets[0].sent[0].submission_id, "stable-id");
  h.sockets[0].drop(1006);
  assert.equal(h.events.length, 1);
  assert.equal(h.timers.size, 1);
  const [id, timer] = [...h.timers][0];
  assert.equal(timer.delay, 1000);
  h.timers.delete(id);
  timer.fn();
  assert.equal(h.sockets.length, 2);
  h.sockets[1].open();
  assert.equal(h.sockets[1].sent.length, 0);
  h.cleanup();
  assert.equal(h.timers.size, 0);
  assert.equal(h.intervals.size, 0);
});

test("WebSocket auth rejection does not cause a reconnect loop", () => {
  const h = websocketHarness();
  h.sockets[0].open();
  h.sockets[0].drop(4403);
  assert.equal(h.timers.size, 0);
  h.cleanup();
});

test("unmount cancels a scheduled WebSocket reconnect", () => {
  const h = websocketHarness();
  h.sockets[0].open();
  h.sockets[0].drop(1006);
  assert.equal(h.timers.size, 1);
  h.cleanup();
  assert.equal(h.timers.size, 0);
});
