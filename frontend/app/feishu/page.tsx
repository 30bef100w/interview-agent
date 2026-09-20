"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, IconChat, btnCls } from "@/components/ui";
import { api } from "@/lib/api";

type Me = {
  feishu_bound?: boolean;
  feishu_name?: string;
};

export default function FeishuInterviewPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [feishuOn, setFeishuOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadMe = useCallback(async () => {
    const row = await api<Me>("/api/auth/me");
    setMe(row);
  }, []);

  useEffect(() => {
    api<{ enabled: boolean }>("/api/auth/feishu/config")
      .then((d) => setFeishuOn(Boolean(d.enabled)))
      .catch(() => setFeishuOn(false));
    loadMe().catch(() => setError("加载账号信息失败"));
    const q = new URLSearchParams(window.location.search);
    if (q.get("feishu") === "1") {
      setNotice("绑定成功");
    }
    const err = (q.get("feishu_error") || "").trim();
    if (err) setError(err);
    if (q.get("feishu") === "1" || err) {
      window.history.replaceState({}, "", "/feishu");
    }
  }, [loadMe]);

  async function bindFeishu() {
    setNotice("");
    setError("");
    setBusy(true);
    try {
      const res = await api<{ authorize_url: string }>("/api/auth/feishu/start?mode=bind");
      window.location.href = res.authorize_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法开始飞书绑定");
      setBusy(false);
    }
  }

  async function unbindFeishu() {
    if (!window.confirm("确认解除飞书绑定？")) return;
    setBusy(true);
    setError("");
    try {
      const row = await api<Me>("/api/auth/feishu/unbind", { method: "POST" });
      setMe(row);
      setNotice("已解除绑定");
    } catch (e) {
      setError(e instanceof Error ? e.message : "解除绑定失败");
    } finally {
      setBusy(false);
    }
  }

  const bound = Boolean(me?.feishu_bound);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          飞书面试
        </h1>
      </div>

      {notice ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-400">
          {notice}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-400">
          {error}
        </div>
      ) : null}

      <Card className="flex flex-col gap-4 p-6">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
            <IconChat className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
              {bound ? "已绑定飞书" : "绑定飞书账号"}
            </div>
            <p className="mt-1 text-sm leading-6 text-zinc-500 dark:text-zinc-400">
              {bound
                ? `已绑定${me?.feishu_name ? `（${me.feishu_name}）` : ""}。可在飞书中进行模拟面试，记录将同步至本账号。`
                : "绑定后可在飞书中进行模拟面试。"}
            </p>
          </div>
        </div>

        {feishuOn === false && !bound ? null : (
          <div className="flex justify-end gap-2">
            {bound ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void unbindFeishu()}
                className={btnCls("secondary")}
              >
                {busy ? "处理中…" : "解除绑定"}
              </button>
            ) : (
              <button
                type="button"
                disabled={busy || feishuOn !== true}
                onClick={() => void bindFeishu()}
                className={btnCls("primary")}
              >
                {busy ? "跳转中…" : "绑定飞书"}
              </button>
            )}
          </div>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">使用方式</h2>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
          <li>绑定飞书账号</li>
          <li>在飞书中打开深问</li>
          <li>开始面试</li>
        </ol>
      </Card>
    </div>
  );
}
