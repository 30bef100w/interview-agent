"use client";

import Editor, { loader } from "@monaco-editor/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";

// 国内镜像加载 Monaco（默认 jsdelivr 在国内不稳定）
loader.config({
  paths: {
    vs: "https://registry.npmmirror.com/monaco-editor/0.52.2/files/min/vs",
  },
});

export type LangOption = {
  id: string;
  label: string;
  monaco: string;
  filename: string;
  filename_scratch?: string;
  available: boolean;
};

export type CodingMode = "function" | "scratch";

export type CodingProblem = {
  slug: string;
  title: string;
  difficulty: string;
  tags: string[];
  description: string;
  description_html?: string;
  method: string;
  params: string[];
  template: string;
  templates?: Record<string, string>;
  templates_by_mode?: {
    function?: Record<string, string>;
    scratch?: Record<string, string>;
  };
  io_hint?: string;
  languages?: LangOption[];
  examples: { args: unknown[]; expected: unknown }[];
};

type JudgeResult = {
  final: string;
  verdict: string;
  passed: number;
  total: number;
  message?: string;
  results?: { case: number; ok: boolean; args: unknown[]; expected: unknown; actual: unknown }[];
  hidden?: { verdict: string; passed?: number; total?: number; message?: string; detail?: unknown };
  performance?: { verdict: string; message?: string; elapsed_ms?: number };
};

type Review = {
  score: number;
  highlight: string;
  issues: string[];
  complexity: string;
  optimization: string;
  explanation: string;
};

type Props = {
  sessionId: string;
  problem: CodingProblem;
  onSubmitted: (judge: JudgeResult, review: Review, message: string) => void;
};

const DIFF_COLOR: Record<string, string> = {
  Easy: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400",
  Medium: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  Hard: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
};

const FALLBACK_LANGS: LangOption[] = [
  {
    id: "python",
    label: "Python 3",
    monaco: "python",
    filename: "solution.py",
    filename_scratch: "main.py",
    available: true,
  },
  {
    id: "java",
    label: "Java",
    monaco: "java",
    filename: "Solution.java",
    filename_scratch: "Main.java",
    available: true,
  },
  {
    id: "cpp",
    label: "C++",
    monaco: "cpp",
    filename: "solution.cpp",
    filename_scratch: "main.cpp",
    available: true,
  },
  {
    id: "go",
    label: "Go",
    monaco: "go",
    filename: "solution.go",
    filename_scratch: "main.go",
    available: true,
  },
];

/** 后端未返回 templates_by_mode 时的手撕兜底模板（保证「手撕」可点） */
const FALLBACK_SCRATCH: Record<string, string> = {
  python: `import sys
import json
import math
import heapq
import bisect
import itertools
import functools
from collections import defaultdict, Counter, deque, OrderedDict
from typing import List, Optional, Tuple, Dict, Set, Any

# 判题：stdin 第一行 = 参数 JSON 数组；stdout 打印一行结果 JSON

def main() -> None:
    # 请自行完成输入输出与求解
    pass


if __name__ == "__main__":
    main()
`,
  java: `import java.io.*;
import java.util.*;
import java.math.*;

// 判题：stdin 第一行 = 参数 JSON 数组；stdout 打印一行结果 JSON

public class Main {
    public static void main(String[] args) throws Exception {
        // 请自行完成输入输出与求解
    }
}
`,
  cpp: `#include <bits/stdc++.h>
using namespace std;

// 判题：stdin 第一行 = 参数 JSON 数组；stdout 打印一行结果 JSON

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    // 请自行完成输入输出与求解
    return 0;
}
`,
  go: `package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
)

// 判题：stdin 第一行 = 参数 JSON 数组；stdout 打印一行结果 JSON

func main() {
	_ = bufio.NewReader
	_ = json.Marshal
	_ = fmt.Println
	_ = math.MaxInt
	_ = os.Stdin
	_ = sort.Ints
	// 请自行完成输入输出与求解
}
`,
};

function fallbackFunctionTemplate(lang: string, method: string, params: string[]): string {
  const args = params.length ? params.join(", ") : "nums, target";
  if (lang === "python") {
    return `class Solution:\n    def ${method}(self, ${args}):\n        pass\n`;
  }
  if (lang === "java") {
    return `class Solution {\n    public int[] ${method}(int[] nums, int target) {\n        \n    }\n}\n`;
  }
  if (lang === "cpp") {
    return `class Solution {\npublic:\n    vector<int> ${method}(vector<int>& nums, int target) {\n        \n    }\n};\n`;
  }
  if (lang === "go") {
    return `func ${method}(nums []int, target int) []int {\n    \n}\n`;
  }
  return "";
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 旧后端会把 <code> 转成 ``` 换行，这里还原成可读 HTML（行内代码两侧换行压成空格） */
function legacyDescriptionToHtml(text: string): string {
  const chunks: string[] = [];
  const re = /\n*```\n*([\s\S]*?)\n*```\n*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    chunks.push(escapeHtml(text.slice(last, m.index)).replace(/[ \t]*\n[ \t]*/g, " "));
    const t = m[1].replace(/^\n+|\n+$/g, "").trim();
    if (t && !t.includes("\n") && t.length <= 80) {
      chunks.push(`<code>${escapeHtml(t)}</code>`);
    } else if (t) {
      chunks.push(`<pre><code>${escapeHtml(t)}</code></pre>`);
    }
    last = m.index + m[0].length;
  }
  chunks.push(escapeHtml(text.slice(last)).replace(/[ \t]*\n[ \t]*/g, " "));
  const flat = chunks.join("").replace(/[ \t]{2,}/g, " ").trim();
  return flat
    ? flat
        .split(/\n{2,}/)
        .map((p) => `<p>${p.trim()}</p>`)
        .join("")
    : "";
}

export default function CodeEditor({ sessionId, problem, onSubmitted }: Props) {
  const languages = useMemo(() => {
    return FALLBACK_LANGS.map((fb) => {
      const fromServer = problem.languages?.find((l) => l.id === fb.id);
      if (!fromServer) return fb;
      return {
        ...fb,
        ...fromServer,
        filename_scratch: fromServer.filename_scratch || fb.filename_scratch,
        // 服务端未标 available 时默认可用（仅 cpp 可能因缺编译器为 false）
        available: fromServer.available !== false,
      };
    });
  }, [problem.languages]);

  const templateMap = useMemo(() => {
    const byMode = problem.templates_by_mode;
    const method = problem.method || "solve";
    const params = problem.params || [];
    const fn: Record<string, string> = { ...(byMode?.function || problem.templates || {}) };
    const sc: Record<string, string> = { ...FALLBACK_SCRATCH, ...(byMode?.scratch || {}) };
    if (!fn.python) fn.python = problem.template;
    for (const id of ["python", "java", "cpp", "go"]) {
      if (!fn[id]) fn[id] = fallbackFunctionTemplate(id, method, params);
      if (!sc[id]) sc[id] = FALLBACK_SCRATCH[id];
    }
    return { function: fn, scratch: sc } as Record<CodingMode, Record<string, string>>;
  }, [problem.templates_by_mode, problem.templates, problem.template, problem.method, problem.params]);

  const defaultLang =
    languages.find((l) => l.id === "python" && l.available)?.id ||
    languages.find((l) => l.available)?.id ||
    "python";

  const cacheKey = (m: CodingMode, l: string) => `${m}:${l}`;

  const [mode, setMode] = useState<CodingMode>("scratch");
  const [lang, setLang] = useState(defaultLang);
  const [code, setCode] = useState(() => templateMap.scratch[defaultLang] || templateMap.function[defaultLang]);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [runOut, setRunOut] = useState<JudgeResult | null>(null);
  const [done, setDone] = useState<{ judge: JudgeResult; review: Review; message: string } | null>(null);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const codeCache = useRef<Record<string, string>>({});

  const currentMeta = languages.find((l) => l.id === lang) || FALLBACK_LANGS[0];
  const filename =
    mode === "scratch"
      ? currentMeta.filename_scratch || currentMeta.filename
      : currentMeta.filename;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [runOut, done]);

  // 题目数据更新（例如刷新出会话带上 templates_by_mode）时，补齐未编辑过的缓存
  useEffect(() => {
    for (const m of ["function", "scratch"] as CodingMode[]) {
      for (const l of Object.keys(templateMap[m])) {
        const key = cacheKey(m, l);
        if (codeCache.current[key] == null && templateMap[m][l]) {
          codeCache.current[key] = templateMap[m][l];
        }
      }
    }
  }, [templateMap]);

  function loadCode(nextMode: CodingMode, nextLang: string): string {
    const key = cacheKey(nextMode, nextLang);
    if (codeCache.current[key] != null) return codeCache.current[key];
    return (
      templateMap[nextMode][nextLang] ||
      templateMap.function[nextLang] ||
      FALLBACK_SCRATCH[nextLang] ||
      ""
    );
  }

  function switchMode(next: CodingMode) {
    if (next === mode || done) return;
    codeCache.current[cacheKey(mode, lang)] = code;
    setMode(next);
    setCode(loadCode(next, lang));
    setRunOut(null);
    setError("");
  }

  function switchLang(next: string) {
    if (next === lang || done) return;
    const meta = languages.find((l) => l.id === next);
    if (meta && !meta.available) {
      alert(`${meta.label} 当前服务器未安装运行环境，暂不可用（可先用 Python / Java / Go）`);
      return;
    }
    codeCache.current[cacheKey(mode, lang)] = code;
    setLang(next);
    setCode(loadCode(mode, next));
    setRunOut(null);
    setError("");
  }

  async function run() {
    setRunning(true);
    setError("");
    setRunOut(null);
    try {
      const res = await api<JudgeResult>(`/api/interview/session/${sessionId}/code/run`, {
        method: "POST",
        body: JSON.stringify({ slug: problem.slug, code, language: lang, coding_mode: mode }),
      });
      if (res.verdict === "runtime_error" && res.message) {
        setError(res.message);
      }
      setRunOut(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "运行失败");
    }
    setRunning(false);
  }

  async function submit() {
    setSubmitting(true);
    setError("");
    try {
      const res = await api<{ judge: JudgeResult; review: Review; message: string }>(
        `/api/interview/session/${sessionId}/code/submit`,
        { method: "POST", body: JSON.stringify({ slug: problem.slug, code, language: lang, coding_mode: mode }) }
      );
      setDone({ judge: res.judge, review: res.review, message: res.message });
      onSubmitted(res.judge, res.review, res.message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    }
    setSubmitting(false);
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-3 p-4">
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-4">
        {/* 左：题面 */}
        <div className="flex min-h-0 flex-col overflow-y-auto rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold">{problem.title}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${DIFF_COLOR[problem.difficulty] ?? "bg-zinc-100 text-zinc-600"}`}
            >
              {problem.difficulty}
            </span>
            {problem.tags.slice(0, 3).map((t) => (
              <span key={t} className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                {t}
              </span>
            ))}
          </div>
          <div
            className="problem-html text-sm leading-relaxed text-zinc-800 dark:text-zinc-200"
            dangerouslySetInnerHTML={{
              __html:
                problem.description_html ||
                legacyDescriptionToHtml(problem.description || ""),
            }}
          />
          <div className="mt-4 space-y-2 rounded-lg border border-dashed border-zinc-300 p-3 text-xs text-zinc-500 dark:border-zinc-700">
            {mode === "function" ? (
              <p>
                <span className="font-medium text-zinc-700 dark:text-zinc-300">函数模式：</span>
                请实现 <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">{problem.method}</code>
                ，无需编写 main / 输入输出。
              </p>
            ) : (
              <pre className="whitespace-pre-wrap font-sans leading-relaxed">
                {problem.io_hint ||
                  "手撕模式：请自行编写完整程序（含输入输出）。stdin 第一行为参数 JSON 数组，stdout 打印一行结果 JSON。"}
              </pre>
            )}
          </div>
        </div>

        {/* 右：编辑器 + 结果 */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center justify-between gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <div className="flex rounded-md border border-zinc-300 p-0.5 text-xs dark:border-zinc-700">
                <button
                  type="button"
                  disabled={!!done}
                  onClick={() => switchMode("scratch")}
                  className={`rounded px-2 py-0.5 ${
                    mode === "scratch"
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-black"
                      : "text-zinc-600 dark:text-zinc-300"
                  }`}
                >
                  手撕
                </button>
                <button
                  type="button"
                  disabled={!!done}
                  onClick={() => switchMode("function")}
                  className={`rounded px-2 py-0.5 ${
                    mode === "function"
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-black"
                      : "text-zinc-600 dark:text-zinc-300"
                  }`}
                >
                  函数
                </button>
              </div>
              <select
                value={lang}
                disabled={!!done}
                onChange={(e) => switchLang(e.target.value)}
                className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
              >
                {languages.map((l) => (
                  <option key={l.id} value={l.id} disabled={!l.available}>
                    {l.label}
                    {!l.available ? "（未安装）" : ""}
                  </option>
                ))}
              </select>
              <span className="truncate text-xs text-zinc-500">{filename}</span>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                onClick={run}
                disabled={running || submitting || !!done || !currentMeta.available}
                className="rounded-md border border-zinc-300 bg-white px-4 py-1 text-sm font-medium disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-800"
              >
                {running ? "运行中…" : "▶ 运行"}
              </button>
              <button
                onClick={submit}
                disabled={submitting || running || !!done || !currentMeta.available}
                className="rounded-md bg-emerald-600 px-4 py-1 text-sm font-medium text-white disabled:opacity-40"
              >
                {submitting ? "判题中…" : "提交"}
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">
            <Editor
              height="100%"
              language={currentMeta.monaco}
              theme="vs-dark"
              value={code}
              onChange={(v) => setCode(v ?? "")}
              options={{
                fontSize: 13,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 4,
                readOnly: !!done,
              }}
            />
          </div>

          <div ref={bottomRef} className="max-h-[45%] overflow-y-auto border-t border-zinc-200 dark:border-zinc-800">
            {error && (
              <div className="whitespace-pre-wrap p-3 text-sm text-red-600 dark:text-red-400">{error}</div>
            )}
            {runOut && !done && runOut.verdict !== "runtime_error" && <RunPanel out={runOut} />}
            {done && <DonePanel judge={done.judge} review={done.review} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function RunPanel({ out }: { out: JudgeResult }) {
  const allPass = out.verdict === "passed";
  return (
    <div className="p-3 text-sm">
      <div className={`mb-2 font-medium ${allPass ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
        {allPass ? `示例用例全部通过（${out.passed}/${out.total}）` : `示例用例未全过（${out.passed}/${out.total}）`}
      </div>
      {out.results?.map((r) => (
        <div key={r.case} className="flex gap-2 py-1 text-xs">
          <span className={r.ok ? "text-emerald-500" : "text-red-500"}>{r.ok ? "✓" : "✗"}</span>
          <span className="text-zinc-500">用例 {r.case}：</span>
          {r.ok ? (
            <span>输出 {JSON.stringify(r.actual)}</span>
          ) : (
            <span className="text-red-500">期望 {JSON.stringify(r.expected)}，实际 {JSON.stringify(r.actual)}</span>
          )}
        </div>
      ))}
      <div className="mt-2 text-xs text-zinc-500">运行自测通过后再点「提交」进行完整判题（随机对拍 + 性能测试）。</div>
    </div>
  );
}

function DonePanel({ judge, review }: { judge: JudgeResult; review: Review }) {
  const final = judge.final;
  const finalInfo: Record<string, { text: string; cls: string }> = {
    accepted: { text: "通过", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400" },
    wrong_answer: { text: "答案错误", cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400" },
    timeout: { text: "超时（性能不达标）", cls: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" },
    runtime_error: { text: "运行错误", cls: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400" },
  };
  const f = finalInfo[final] ?? { text: final, cls: "bg-zinc-100 text-zinc-700" };
  return (
    <div className="p-4 text-sm">
      <div className="flex items-center gap-3">
        <span className={`rounded-full px-3 py-1 text-sm font-semibold ${f.cls}`}>判定：{f.text}</span>
        <span className="text-xs text-zinc-500">
          示例 {judge.passed}/{judge.total} · 对拍 {judge.hidden?.passed ?? "-"}/{judge.hidden?.total ?? "-"} · 性能{" "}
          {judge.performance?.verdict === "passed"
            ? `${judge.performance.elapsed_ms}ms`
            : judge.performance?.verdict === "timeout"
              ? "TLE"
              : "—"}
        </span>
      </div>
      {judge.hidden?.message && <div className="mt-2 text-xs text-zinc-500">{judge.hidden.message}</div>}
      <div className="mt-3 rounded-lg bg-zinc-50 p-3 dark:bg-zinc-800/60">
        <div className="mb-1 font-medium">AI 评审 · 得分 {review.score}/10</div>
        {review.highlight && review.highlight !== "无" && (
          <div className="mb-1"><span className="font-medium text-emerald-600 dark:text-emerald-400">亮点：</span>{review.highlight}</div>
        )}
        {review.issues.length > 0 && (
          <div className="mb-1">
            <span className="font-medium text-red-600 dark:text-red-400">问题：</span>
            <ul className="ml-4 list-disc">
              {review.issues.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </div>
        )}
        <div className="mb-1"><span className="font-medium">复杂度：</span>{review.complexity}</div>
        <div className="mb-1"><span className="font-medium">优化建议：</span>{review.optimization}</div>
        <div><span className="font-medium">思路讲解：</span>{review.explanation}</div>
      </div>
    </div>
  );
}
