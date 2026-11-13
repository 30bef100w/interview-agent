import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Stateful hook renderer plus fake browser devices: tests need no real mic or online STT service.
function harness(entry, invoke, globals = {}) {
  const slots = [], cache = new Map(), timers = new Map();
  let cursor = 0, dirty = false, timerId = 0, pending = [], output, props;
  const memo = (create, deps) => {
    const index = cursor++;
    const previous = slots[index];
    if (!previous || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
      slots[index] = { value: create(), deps };
    }
    return slots[index].value;
  };
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: initial };
      return [slots[index].value, value => {
        const next = typeof value === "function" ? value(slots[index].value) : value;
        if (!Object.is(next, slots[index].value)) { slots[index].value = next; dirty = true; }
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback: (fn, deps) => memo(() => fn, deps),
    useEffect(fn, deps) {
      const index = cursor++;
      const previous = slots[index];
      if (!previous || !deps || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
        slots[index] = { deps, cleanup: previous?.cleanup };
        pending.push(() => { slots[index].cleanup?.(); slots[index].cleanup = fn(); });
      }
    },
    forwardRef: fn => props => fn(props, null),
    useImperativeHandle() {},
  };
  const window = { isSecureContext: true };
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const source = readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
    const compiled = ts.transpileModule(source, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText;
    const context = {
      exports: {}, window, navigator: { mediaDevices: { getUserMedia: async () => { throw new Error("Unexpected mic request"); } } },
      process: { env: {} }, localStorage: { getItem: () => "test-token" },
      DOMException, Error, Blob, FormData, AbortController, Response,
      setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
      clearTimeout: id => timers.delete(id), ...globals,
      require: id => {
        if (id === "react") return react;
        if (id === "react/jsx-runtime") return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
        if (id === "@/components/ui") return { IconSend: () => null };
        if (id.startsWith("@/")) return load(id.slice(2) + ".ts");
        throw new Error(`Unexpected import ${id}`);
      },
    };
    vm.runInNewContext(compiled, context);
    cache.set(name, context.exports);
    return context.exports;
  }
  const exports = load(entry);
  return {
    render(next = props) {
      props = next;
      let count = 0;
      do {
        assert.ok(++count < 30, "render must stabilize");
        dirty = false;
        cursor = 0;
        output = invoke(exports, props);
        const effects = pending;
        pending = [];
        effects.forEach(effect => effect());
      } while (dirty);
      return output;
    },
    load,
    timers,
    fire(delay) {
      const found = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(found, `timer ${delay} must exist`);
      timers.delete(found[0]);
      found[1].fn();
    },
    cleanup() { slots.forEach(slot => slot.cleanup?.()); },
  };
}

function speechGlobals(extra = {}) {
  const instances = [];
  class Recognition {
    starts = 0;
    stops = 0;
    aborts = 0;
    constructor() { instances.push(this); }
    start() { this.starts++; if (extra.startError) throw extra.startError; }
    stop() { this.stops++; }
    abort() { this.aborts++; }
    result(...pieces) {
      this.onresult?.({ resultIndex: 0, results: pieces.map(([transcript, isFinal]) => ({ 0: { transcript }, isFinal })) });
    }
    end() { this.onend?.(); }
    fail(error) { this.onerror?.({ error }); }
  }
  return { instances, globals: { window: { isSecureContext: true, SpeechRecognition: Recognition } } };
}

function speech(extra = {}) {
  const device = speechGlobals(extra), live = [], finals = [];
  const h = harness("hooks/useSpeechToText.ts", (m, p) => m.useSpeechToText(p), device.globals);
  h.render({ onInterim: text => live.push(text), onFinal: text => finals.push(text) });
  return { ...h, ...device, live, finals };
}

test("speech draft append preserves existing text, whitespace and interim replacements", () => {
  const h = speech();
  const { appendSpeechDraft: append } = h.load("lib/speech-draft.ts");
  assert.equal(append(" 原草稿\n", "你好"), " 原草稿\n你好");
  assert.equal(append("原草稿", "你好"), "原草稿 你好");
  assert.equal(append(" 原草稿 ", "  "), " 原草稿 ");
  assert.equal(append("", "你好"), "你好");
});

test("repeated snapshots replace interim text without duplicating final results", () => {
  const h = speech();
  assert.equal(h.render().supported, true);
  assert.equal(h.render().start(), true);
  assert.equal(h.render().start(), false);
  const rec = h.instances[0];
  assert.equal(rec.lang, "zh-CN");
  assert.equal(rec.interimResults, true);
  rec.result(["缓存", false]);
  rec.result(["缓存", true], ["使用", false]);
  rec.result(["缓存", true], ["使用 Redis", true]);
  rec.result(["缓存", true], ["使用 Redis", true]);
  assert.deepEqual(h.live, ["缓存", "缓存使用", "缓存使用 Redis", "缓存使用 Redis"]);
  assert.deepEqual(h.finals, []);
  h.render().stop();
  assert.equal(h.render().stopping, true);
  rec.end();
  assert.deepEqual(h.finals, ["缓存使用 Redis"]);
  assert.equal(h.render().listening, false);
  assert.equal(h.timers.size, 0);
});

test("stop accepts trailing final text and ignores callbacks after session completion", () => {
  const h = speech();
  h.render().start();
  const rec = h.instances[0];
  const stale = rec.onresult;
  rec.result(["最后", false]);
  h.render().stop();
  rec.result(["最后一句。", true]);
  rec.end();
  stale({ results: [{ 0: { transcript: "过期" }, isFinal: true }] });
  assert.equal(h.live.at(-1), "最后一句。");
  assert.deepEqual(h.finals, ["最后一句。"]);
});

test("stop timeout preserves last interim hypothesis and releases microphone", () => {
  const h = speech();
  h.render().start();
  h.instances[0].result(["未定稿", false]);
  h.render().stop();
  h.fire(2000);
  assert.deepEqual(h.finals, ["未定稿"]);
  assert.equal(h.instances[0].aborts, 1);
  assert.equal(h.timers.size, 0);
});

test("browser restarts keep cumulative text with fresh result indexes", () => {
  const h = speech();
  h.render().start();
  h.instances[0].result(["第一句。", true]);
  h.instances[0].end();
  h.fire(250);
  h.instances[1].result(["第二句。", false]);
  assert.equal(h.live.at(-1), "第一句。第二句。");
  h.render().stop();
  h.instances[1].end();
  assert.deepEqual(h.finals, ["第一句。第二句。"]);
  assert.equal(h.timers.size, 0);
});

test("stop between browser restarts commits text and prevents reopening the mic", () => {
  const h = speech();
  h.render().start();
  h.instances[0].result(["保留这句", true]);
  h.instances[0].end();
  h.render().stop();
  assert.deepEqual(h.finals, ["保留这句"]);
  assert.equal(h.instances.length, 1);
  assert.equal(h.timers.size, 0);
});

test("silence retries are bounded and network/permission failures never restart", () => {
  const silent = speech();
  silent.render().start();
  for (let i = 0; i < 5; i++) {
    silent.instances[i].fail("no-speech");
    silent.instances[i].end();
    if (i < 4) silent.fire(250);
  }
  assert.equal(silent.render().error, "no-speech");
  assert.equal(silent.timers.size, 0);
  for (const error of ["network", "not-allowed", "audio-capture", "service-not-allowed"]) {
    const h = speech();
    h.render().start();
    const oldEnd = h.instances[0].onend;
    h.instances[0].fail(error);
    oldEnd();
    assert.equal(h.render().error, error);
    assert.equal(h.render().listening, false);
    assert.equal(h.timers.size, 0);
  }
});

test("cancellation, unmount and auto-stop clean up timers without late writes", () => {
  for (const cleanup of [h => h.render().cancel(), h => h.cleanup()]) {
    const h = speech();
    h.render().start();
    const oldResult = h.instances[0].onresult;
    cleanup(h);
    oldResult({ results: [{ 0: { transcript: "过期" }, isFinal: true }] });
    assert.deepEqual(h.live, []);
    assert.equal(h.instances[0].aborts, 1);
    assert.equal(h.timers.size, 0);
  }
  const h = speech();
  h.render().start();
  h.fire(60000);
  assert.equal(h.instances[0].stops, 1);
  h.instances[0].end();
  assert.equal(h.timers.size, 0);
});

test("unsupported browsers and synchronous start failures have actionable errors", () => {
  const h = harness("hooks/useSpeechToText.ts", (m, p) => m.useSpeechToText(p));
  h.render({});
  assert.equal(h.render().start(), false);
  assert.equal(h.render().error, "unsupported");
  const rejected = speech({ startError: new DOMException("denied", "NotAllowedError") });
  assert.equal(rejected.render().start(), false);
  assert.equal(rejected.render().error, "not-allowed");
  assert.equal(rejected.timers.size, 0);
});

function recordedGlobals(options = {}) {
  const instances = [], requests = [];
  let releases = 0;
  const stream = { getTracks: () => [{ stop: () => releases++ }] };
  class Recorder {
    static isTypeSupported(type) { return !options.noFormat && type === (options.mime || "audio/webm;codecs=opus"); }
    state = "inactive";
    constructor(_stream, { mimeType }) {
      if (options.constructorError) throw new Error("device failed");
      this.mimeType = mimeType;
      instances.push(this);
    }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; this.done = this.onstop?.(); }
    data(content = "audio") { this.ondataavailable?.({ data: new Blob([content], { type: this.mimeType }) }); }
  }
  return {
    instances, requests, stream, releases: () => releases,
    globals: {
      MediaRecorder: Recorder,
      navigator: { mediaDevices: { getUserMedia: options.getUserMedia || (async () => stream) } },
      fetch: async (url, init) => {
        requests.push({ url, ...init });
        return options.fetch ? options.fetch(url, init) : new Response(JSON.stringify({ text: "识别文字" }));
      },
    },
  };
}

function recorded(options = {}) {
  const device = recordedGlobals(options), texts = [];
  const h = harness("hooks/useRecordedTranscription.ts", (m, p) => m.useRecordedTranscription(p), { ...device.globals, ...options.globals });
  h.render(text => texts.push(text));
  return { ...h, ...device, texts };
}

test("recording fallback negotiates Safari MP4, uploads only on stop and cleans resources", async () => {
  const h = recorded({ mime: "audio/mp4" });
  await h.render().start();
  await h.render().start();
  assert.equal(h.instances.length, 1);
  assert.equal(h.render().phase, "recording");
  assert.equal(h.requests.length, 0);
  h.instances[0].data();
  h.render().stop();
  assert.equal(h.render().phase, "transcribing");
  await h.instances[0].done;
  assert.deepEqual(h.texts, ["识别文字"]);
  assert.equal(h.requests[0].body.get("file").name, "answer.m4a");
  assert.equal(h.requests[0].body.get("file").type, "audio/mp4");
  assert.equal(h.requests[0].headers.Authorization, "Bearer test-token");
  assert.equal(h.render().phase, "idle");
  assert.ok(h.releases() > 0);
  assert.equal(h.timers.size, 0);
});

test("empty, oversize and failed recordings never upload and release tracks", async () => {
  for (const options of [{}, { noFormat: true }, { constructorError: true }, { oversize: true }]) {
    const h = recorded(options);
    await h.render().start();
    if (options.oversize) h.instances[0].data(new Uint8Array(10 * 1024 * 1024 + 1));
    h.render().stop();
    await h.instances[0]?.done;
    assert.equal(h.render().phase, "idle");
    assert.equal(h.requests.length, 0);
    assert.deepEqual(h.texts, []);
    assert.ok(h.releases() > 0);
    assert.equal(h.timers.size, 0);
  }
});

test("cancel/unmount while mic permission is pending releases a late stream", async () => {
  for (const cleanup of [h => h.render().cancel(), h => h.cleanup()]) {
    let resolve;
    const h = recorded({ getUserMedia: () => new Promise(done => { resolve = done; }) });
    const started = h.render().start();
    assert.equal(h.render().phase, "requesting");
    cleanup(h);
    resolve(h.stream);
    await started;
    assert.equal(h.instances.length, 0);
    assert.equal(h.releases(), 1);
  }
});

test("cancel/unmount/timeout aborts upload and suppresses even an uncancellable response", async () => {
  for (const cleanup of [h => h.render().cancel(), h => h.cleanup(), h => h.fire(120000)]) {
    let resolve;
    const h = recorded({ fetch: () => new Promise(done => { resolve = done; }) });
    await h.render().start();
    h.instances[0].data();
    h.render().stop();
    cleanup(h);
    assert.equal(h.requests[0].signal.aborted, true);
    resolve(new Response(JSON.stringify({ text: "不得写入" })));
    await h.instances[0].done;
    assert.deepEqual(h.texts, []);
    assert.equal(h.timers.size, 0);
  }
});

test("recording auto-stops at 60s and backend errors preserve a visible message", async () => {
  const h = recorded({ fetch: async () => new Response(JSON.stringify({ detail: "没有识别到语音内容" }), { status: 400 }) });
  await h.render().start();
  h.instances[0].data();
  h.fire(60000);
  await h.instances[0].done;
  assert.equal(h.render().hint, "没有识别到语音内容");
  assert.equal(h.render().phase, "idle");
  assert.deepEqual(h.texts, []);
  assert.equal(h.timers.size, 0);
});

test("insecure contexts and denied permission stay idle without uploading", async () => {
  const insecure = recorded({
    globals: { window: { isSecureContext: false } },
    getUserMedia: () => { assert.fail("HTTP must not request microphone access"); },
  });
  await insecure.render().start();
  assert.match(insecure.render().hint, /HTTPS/);
  const denied = recorded({ getUserMedia: async () => { throw new DOMException("denied", "NotAllowedError"); } });
  await denied.render().start();
  assert.match(denied.render().hint, /权限被拒绝/);
  for (const h of [insecure, denied]) {
    assert.equal(h.render().phase, "idle");
    assert.equal(h.requests.length, 0);
    assert.equal(h.timers.size, 0);
  }
});

function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  const children = [tree.props?.children].flat(Infinity);
  return [...(predicate(tree) ? [tree] : []), ...children.flatMap(child => elements(child, predicate))];
}

function composer(options = {}) {
  const device = speechGlobals(), recording = recordedGlobals(options);
  const h = harness("components/interview/AnswerComposer.tsx", (m, p) => m.default(p), { ...device.globals, ...recording.globals });
  const sent = [];
  const props = { value: "原草稿", voiceEnabled: true, onChange: text => { props.value = text; }, onSend: () => sent.push(props.value) };
  const render = changes => { Object.assign(props, changes); return h.render(props); };
  const find = predicate => elements(render(), predicate)[0];
  render();
  return { ...h, props, sent, instances: device.instances, recorders: recording.instances, render,
    mic: () => find(el => el.type === "button" && el.props["aria-label"]?.includes("实时转文字")),
    textarea: () => find(el => el.type === "textarea"),
    send: () => find(el => el.type === "button" && el.props.title?.includes("发送")),
    record: () => find(el => el.type === "button" && el.props.title?.startsWith("备用方式")),
  };
}

test("composer streams into the draft, waits for stop, never auto-sends and preserves edits", () => {
  const h = composer();
  h.mic().props.onClick();
  h.instances[0].result(["我使用 Redis", false]);
  h.render();
  assert.equal(h.props.value, "原草稿 我使用 Redis");
  assert.equal(h.send().props.disabled, true);
  h.send().props.onClick();
  const enter = { key: "Enter", nativeEvent: {}, preventDefault() {} };
  h.textarea().props.onKeyDown(enter);
  assert.deepEqual(h.sent, []);
  h.mic().props.onClick();
  assert.equal(h.send().props.disabled, true);
  h.instances[0].result(["我使用 Redis 缓存。", true]);
  h.instances[0].end();
  assert.equal(h.send().props.disabled, false);
  h.textarea().props.onKeyDown({ ...enter, nativeEvent: { isComposing: true } });
  assert.deepEqual(h.sent, []);
  h.send().props.onClick();
  assert.deepEqual(h.sent, ["原草稿 我使用 Redis 缓存。"]);

  h.mic().props.onClick();
  const staleResult = h.instances[1].onresult;
  h.instances[1].result(["追加", false]);
  h.textarea().props.onChange({ target: { value: "手动修改" } });
  staleResult({ results: [{ 0: { transcript: "迟到文字" }, isFinal: true }] });
  h.render();
  assert.equal(h.props.value, "手动修改");
  assert.equal(h.instances[1].aborts, 1);
  assert.equal(h.timers.size, 0);
});

test("composer keeps realtime and recording mutually exclusive; disabling cancels mic", async () => {
  const h = composer();
  h.mic().props.onClick();
  assert.equal(h.record().props.disabled, true);
  h.render({ disabled: true });
  assert.equal(h.instances[0].aborts, 1);
  h.render({ disabled: false });
  assert.equal(h.record().props.disabled, false);
  assert.equal(h.record().props.children, "录音转文字");
  h.record().props.onClick();
  assert.equal(h.record().props.children, "等待麦克风…");
  await new Promise(setImmediate);
  h.render();
  assert.equal(h.mic().props.disabled, true);
  assert.equal(h.send().props.disabled, true);
  assert.equal(h.recorders.length, 1);
  h.recorders[0].data();
  h.record().props.onClick();
  await h.recorders[0].done;
  h.render();
  assert.equal(h.props.value, "原草稿 识别文字");
  assert.deepEqual(h.sent, []);
  assert.equal(h.send().props.disabled, false);
});

test("editing during upload cancels it and cannot be overwritten by a late transcription", async () => {
  let resolve;
  const h = composer({ fetch: () => new Promise(done => { resolve = done; }) });
  h.record().props.onClick();
  await new Promise(setImmediate);
  h.recorders[0].data();
  h.record().props.onClick();
  h.textarea().props.onChange({ target: { value: "手动修正后的草稿" } });
  resolve(new Response(JSON.stringify({ text: "过期识别文字" })));
  await h.recorders[0].done;
  assert.equal(h.props.value, "手动修正后的草稿");
  assert.deepEqual(h.sent, []);
  assert.equal(h.timers.size, 0);
});

test("real React server and initial browser render have identical microphone markup", () => {
  const require = createRequire(import.meta.url);
  const React = require("react");
  const { renderToString } = require("react-dom/server");
  function render(window) {
    const cache = new Map();
    function load(name) {
      if (cache.has(name)) return cache.get(name);
      const source = readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
      const compiled = ts.transpileModule(source, { compilerOptions: {
        module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
      } }).outputText;
      const context = { exports: {}, window, process: { env: {} }, require: id => {
        if (id === "@/components/ui") return { IconSend: () => null };
        if (id.startsWith("@/")) return load(id.slice(2) + ".ts");
        return require(id);
      } };
      vm.runInNewContext(compiled, context);
      cache.set(name, context.exports);
      return context.exports;
    }
    const Composer = load("components/interview/AnswerComposer.tsx").default;
    return renderToString(React.createElement(Composer, {
      value: "草稿", voiceEnabled: true, onChange() {}, onSend() {},
    }));
  }
  const server = render(undefined);
  assert.match(server, /正在检查麦克风/);
  assert.equal(render({ isSecureContext: true }), server);
  assert.equal(render({ isSecureContext: false }), server);
});
