"use client";

import { useEffect, useState } from "react";

import { Card, IconSliders, btnCls } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type Provider = {
  id: string;
  name: string;
  base_url: string;
  models: { id: string; name: string; input_price_per_m: number; output_price_per_m: number }[];
};

type LlmSetting = {
  provider: string;
  model: string;
  use_default: boolean;
  providers: Provider[];
};

const INPUT_CLS =
  "h-11 w-full rounded-xl border border-zinc-200 bg-white px-3.5 text-sm text-zinc-900 placeholder-zinc-400 outline-none transition-all focus:border-teal-400 focus:ring-2 focus:ring-teal-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:focus:border-teal-500";

export default function SettingsPage() {
  const [data, setData] = useState<LlmSetting | null>(null);
  const [provider, setProvider] = useState("deepseek");
  const [model, setModel] = useState("deepseek-chat");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [platformQuota, setPlatformQuota] = useState<number | null>(null);

  useEffect(() => {
    api<{ platform_quota: number }>("/api/auth/me")
      .then((me) => setPlatformQuota(me.platform_quota))
      .catch(() => {});
    api<LlmSetting>("/api/settings/llm")
      .then((d) => {
        setData(d);
        setProvider(d.provider);
        setModel(d.model);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          window.location.assign("/login");
        } else {
          setError(e instanceof Error ? e.message : "加载失败");
        }
      });
  }, []);

  const providers = data?.providers ?? [];
  const current = providers.find((p) => p.id === provider);
  const currentModel = current?.models.find((m) => m.id === model);

  async function save() {
    setError("");
    setOk("");
    setSaving(true);
    try {
      const res = await api<LlmSetting>("/api/settings/llm", {
        method: "PUT",
        body: JSON.stringify({ provider, model, api_key: apiKey }),
      });
      setData(res);
      setApiKey("");
      setOk(res.use_default ? "已切换为系统默认模型" : "已保存，后续面试将使用你的模型");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    }
    setSaving(false);
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 px-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          模型设置
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          使用自己的 API Key 面试，用量实时统计，不经过他人账户
        </p>
      </div>

      {platformQuota != null && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            platformQuota > 0
              ? "border-sky-200 bg-sky-50 text-sky-800"
              : "border-amber-200 bg-amber-50 text-amber-800"
          }`}
        >
          {platformQuota > 0 ? (
            <>
              平台试用剩余 <strong>{platformQuota}</strong> 场（使用系统默认 Key
              时每创建一场扣 1 次；填写自己的 Key 不扣次）
            </>
          ) : (
            <>
              平台试用已用完。请在下方填写自己的 API Key，或联系管理员发放额度后继续使用系统默认模型。
            </>
          )}
        </div>
      )}

      {error && (
        <div className="animate-fade-in rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-400">
          {error}
        </div>
      )}
      {ok && (
        <div className="animate-fade-in rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-400">
          {ok}
        </div>
      )}

      {!data ? (
        <div className="flex flex-1 items-center justify-center text-zinc-500">加载中…</div>
      ) : (
        <Card className="flex flex-col gap-5 p-6">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-teal-50 text-teal-600 dark:bg-teal-950/60 dark:text-teal-400">
              <IconSliders className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                当前状态
              </div>
              <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {data.use_default
                  ? "使用系统默认模型（DeepSeek），可配置你自己的 Key 后按需切换"
                  : `使用你的 Key（${data.provider} / ${data.model}）`}
              </div>
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              模型服务商
            </label>
            <select
              value={provider}
              onChange={(e) => {
                const p = providers.find((x) => x.id === e.target.value);
                setProvider(e.target.value);
                if (p) setModel(p.models[0]?.id ?? "");
              }}
              className={INPUT_CLS}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              模型
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className={INPUT_CLS}
            >
              {current?.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}（输入 ¥{m.input_price_per_m}/百万 · 输出 ¥{m.output_price_per_m}/百万）
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              API Key
              <span className="ml-2 text-xs font-normal text-zinc-400 dark:text-zinc-500">
                留空并保存 = 使用系统默认模型
              </span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={data.use_default ? "sk-…" : "已配置（输入新 Key 可覆盖）"}
              className={INPUT_CLS}
              autoComplete="off"
            />
            {current && currentModel && (currentModel.input_price_per_m > 0 || currentModel.output_price_per_m > 0) && (
              <p className="mt-1.5 text-xs text-zinc-400 dark:text-zinc-500">
                当前选择：{current.name} · {currentModel.name}
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <button onClick={save} disabled={saving} className={btnCls("primary")}>
              {saving ? "保存中…" : "保存配置"}
            </button>
          </div>
        </Card>
      )}
    </div>
  );
}
