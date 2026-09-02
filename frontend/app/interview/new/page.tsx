"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import CustomSettingsModal, {
  countActiveCustom,
  type CustomSettings,
  type DedupScope,
} from "@/components/CustomSettingsModal";
import { useToast } from "@/components/Toast";
import {
  Badge,
  Card,
  IconCheck,
  IconCode,
  IconMic,
  IconSliders,
  IconTarget,
  IconUser,
} from "@/components/ui";
import { api } from "@/lib/api";

type Resume = { id: number; filename: string };
type RoleOpt = { id: string; name: string };
type Category = { name: string; roles: RoleOpt[] };
type Company = { id: string; name: string };
type Catalog = { categories: Category[]; companies: Company[] };

const DEFAULT_KEY = "fa_default_resume_id";

const MODES = [
  {
    value: "full",
    label: "全流程混合面",
    desc: "项目拷打 + 八股 + 算法 + HR，比例按简历动态分配，最接近真实面试",
    icon: <IconTarget className="h-5 w-5" />,
  },
  {
    value: "specialized",
    label: "专项专场",
    desc: "只考一个环节，深度突击薄弱项",
    icon: <IconMic className="h-5 w-5" />,
  },
] as const;

const TYPES = [
  { value: "full", label: "全流程", desc: "项目 + 八股 + 算法 + HR", icon: <IconTarget className="h-5 w-5" /> },
  { value: "project", label: "项目拷打", desc: "深挖简历项目，拷打真实性", icon: <IconCode className="h-5 w-5" /> },
  { value: "ba_gu", label: "八股专场", desc: "围绕技术栈的基础知识", icon: <IconMic className="h-5 w-5" /> },
  { value: "hr", label: "HR 行为面", desc: "沟通、抗压、职业规划", icon: <IconUser className="h-5 w-5" /> },
] as const;

function NewInterviewForm() {
  const router = useRouter();
  const search = useSearchParams();
  const toast = useToast();
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState<number | null>(null);
  const [mode, setMode] = useState<"full" | "specialized">("full");
  const [type, setType] = useState("full");
  const [targetRole, setTargetRole] = useState("");
  const [targetCompany, setTargetCompany] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [category, setCategory] = useState("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [roleSuggestions, setRoleSuggestions] = useState<RoleOpt[]>([]);
  const [fromLabel, setFromLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [planProgress, setPlanProgress] = useState(0);
  const [planLabel, setPlanLabel] = useState("准备规划");
  const [prefilled, setPrefilled] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [custom, setCustom] = useState<CustomSettings>({
    count: 8,
    practiceFocus: "",
    skipCoding: false,
    dedupScope: "all",
    reviewMode: false,
  });
  const [platformQuota, setPlatformQuota] = useState<number | null>(null);

  const rolesInCategory =
    catalog?.categories.find((c) => c.name === category)?.roles ?? [];

  useEffect(() => {
    const qMode = search.get("mode");
    const qType = search.get("type");
    const qFocus = search.get("focus") || "";
    const qFrom = search.get("from") || "";
    if (qMode === "full" || qMode === "specialized") {
      setMode(qMode);
      setPrefilled(true);
    }
    if (qType && ["full", "project", "ba_gu", "hr"].includes(qType)) {
      setType(qType);
      if (qType !== "full") setMode("specialized");
      setPrefilled(true);
    }
    if (qFocus) {
      setCustom((prev) => ({ ...prev, practiceFocus: qFocus.slice(0, 500) }));
      setPrefilled(true);
    }
    if (qFrom) setFromLabel(qFrom);
  }, [search]);

  function loadCatalog() {
    setCatalogError("");
    api<Catalog>("/api/meta/job-catalog")
      .then((c) => {
        setCatalog(c);
        if (!c.categories?.length) setCatalogError("岗位分类为空，请检查后端配置");
      })
      .catch((e) => {
        setCatalog(null);
        setCatalogError(e instanceof Error ? e.message : "岗位分类加载失败，请重启后端后重试");
      });
  }

  useEffect(() => {
    loadCatalog();
    api<{ platform_quota: number }>("/api/auth/me")
      .then((me) => setPlatformQuota(me.platform_quota))
      .catch(() => {});
    api<Resume[]>("/api/resume")
      .then((list) => {
        setResumes(list);
        if (list.length > 0) {
          const preferred =
            list.find((r) => String(r.id) === localStorage.getItem(DEFAULT_KEY)) ?? list[0];
          setResumeId(preferred.id);
        }
      })
      .catch(() => window.location.assign("/login"));
  }, []);

  useEffect(() => {
    if (!resumeId) {
      setRoleSuggestions([]);
      return;
    }
    api<{ suggestions: RoleOpt[] }>(`/api/meta/infer-role?resume_id=${resumeId}`)
      .then((res) => setRoleSuggestions(res.suggestions ?? []))
      .catch(() => setRoleSuggestions([]));
  }, [resumeId]);

  function pickSuggestedRole(opt: RoleOpt) {
    setTargetRole(opt.name);
    if (!catalog) return;
    const cat = catalog.categories.find((c) => c.roles.some((r) => r.id === opt.id));
    if (cat) setCategory(cat.name);
  }

  function onCategoryChange(name: string) {
    setCategory(name);
    const roles = catalog?.categories.find((c) => c.name === name)?.roles ?? [];
    if (roles.length === 1) setTargetRole(roles[0].name);
    else if (!roles.some((r) => r.name === targetRole)) setTargetRole("");
  }

  async function waitForPlanReady(sessionId: number) {
    // 真实简历 + 多项目拷打链常需 6～8 分钟，勿过早判超时
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const p = await api<{
        status: string;
        progress: number;
        label: string;
        step: string;
        detail?: string;
      }>(`/api/interview/session/${sessionId}/create-progress`);
      setPlanProgress(p.progress);
      setPlanLabel(p.label || "规划中");
      if (p.status === "ready") return;
      if (p.status === "failed") {
        throw new Error(p.detail?.trim() || "题单规划失败，请重试");
      }
      await new Promise((r) => setTimeout(r, 1200));
    }
    throw new Error("规划耗时较长仍未完成，请稍后在「面试记录」查看是否已生成，或重试");
  }

  async function start() {
    if (!resumeId) {
      toast.err("请先上传简历");
      return;
    }
    setCreating(true);
    setPlanProgress(3);
    setPlanLabel("准备规划");
    try {
      const session = await api<{
        session_id: number;
        status?: string;
        settings_applied?: {
          skip_coding?: boolean;
          has_coding?: boolean;
          dedup_scope?: string;
          avoid_topic_count?: number;
          review_mode?: boolean;
          used_platform_key?: boolean;
          platform_quota_remaining?: number;
        };
      }>("/api/interview/session", {
        method: "POST",
        body: JSON.stringify({
          resume_id: resumeId,
          interview_mode: mode,
          interview_type: type,
          question_count: custom.count,
          target_role: targetRole.trim(),
          target_company: targetCompany.trim(),
          job_description: jobDescription.trim(),
          practice_focus: custom.practiceFocus.trim(),
          skip_coding: mode === "full" ? custom.skipCoding : false,
          dedup_scope: custom.dedupScope,
          review_mode: custom.reviewMode,
        }),
      });
      const applied = session.settings_applied;
      if (applied) {
        const bits: string[] = [];
        if (applied.skip_coding) {
          bits.push(applied.has_coding ? "去算法未生效" : "已去掉算法");
        }
        if (applied.dedup_scope && applied.dedup_scope !== "none") {
          bits.push(`去重已加载${applied.avoid_topic_count ?? 0}条历史题`);
        }
        if (applied.review_mode) bits.push("复习模式");
        if (applied.used_platform_key && typeof applied.platform_quota_remaining === "number") {
          bits.push(`试用剩余${applied.platform_quota_remaining}场`);
          setPlatformQuota(applied.platform_quota_remaining);
        }
        if (bits.length) toast.ok(`本场设置：${bits.join(" · ")}`);
      }
      await waitForPlanReady(session.session_id);
      window.location.assign(`/interview/${session.session_id}`);
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "创建失败，请重试");
      setCreating(false);
    }
  }

  const modeLabel = MODES.find((m) => m.value === mode)?.label ?? mode;
  const typeLabel = TYPES.find((t) => t.value === type)?.label ?? type;
  const resumeName = resumes.find((r) => r.id === resumeId)?.filename;
  const customActive = countActiveCustom(custom, mode);
  const dedupLabel: Record<DedupScope, string> = {
    none: "",
    last5: "近5场去重",
    last10: "近10场去重",
    all: "永久去重",
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-8">
      <section className="animate-fade-up">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          开始一场模拟面试
        </h1>
        <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
          每场都是独立完整的模拟。可选本场焦点只影响这一场规划，不跨场记忆。
        </p>
      </section>

      {platformQuota != null && (
        <div
          className={`animate-fade-up rounded-2xl border px-4 py-3 text-sm ${
            platformQuota > 0
              ? "border-sky-100 bg-sky-50/70 text-sky-900"
              : "border-amber-200 bg-amber-50 text-amber-900"
          }`}
        >
          {platformQuota > 0 ? (
            <>
              平台试用剩余 <strong>{platformQuota}</strong> 场（使用系统默认 Key
              时每开一场扣 1 次）。也可在「模型设置」填写自己的 Key，不占试用次数。
            </>
          ) : (
            <>
              平台试用已用完。请先去「模型设置」填写自己的 API Key，或联系管理员发放额度。
            </>
          )}
        </div>
      )}

      {prefilled && (
        <div className="animate-fade-up rounded-2xl border border-sky-100 bg-sky-50/70 px-4 py-3 text-sm text-sky-900">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="sky">来自成长档案</Badge>
            {fromLabel ? <span className="font-medium">{fromLabel}</span> : null}
          </div>
          <p className="mt-1.5 text-xs leading-5 text-sky-800/80">
            已预填模式与本场焦点，可随时修改；确认后仍开启一场新的独立面试。
          </p>
        </div>
      )}

      <Card className="animate-fade-up p-5 sm:p-6" style={{ animationDelay: "0.03s" }}>
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">本场设定</h2>
        <p className="mt-1 text-xs text-zinc-400">简历与目标决定出题方向；轮次、焦点、去重等在自定义设置里。</p>

        <div className="mt-5 space-y-5">
          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              选择简历
            </label>
            {resumes.length === 0 ? (
              <button
                type="button"
                onClick={() => router.push("/resume/upload")}
                className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-zinc-300 px-6 py-7 text-center transition-colors hover:border-sky-400 dark:border-zinc-700 dark:hover:border-sky-500"
              >
                <span className="text-sm font-medium text-zinc-600 dark:text-zinc-300">
                  还没有简历，点击上传 PDF →
                </span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">
                  AI 会抽取你的画像，作为面试官的提问依据
                </span>
              </button>
            ) : (
              <select
                value={resumeId ?? ""}
                onChange={(e) => setResumeId(Number(e.target.value))}
                className="h-11 w-full rounded-xl border border-zinc-200 bg-white px-3.5 text-sm text-zinc-900 outline-none transition-all focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
              >
                {resumes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.filename}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                岗位方向 <span className="font-normal text-zinc-400">（可选）</span>
              </label>
              {catalogError ? (
                <div className="mb-2 flex items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <span>{catalogError}</span>
                  <button type="button" className="shrink-0 underline" onClick={loadCatalog}>
                    重试
                  </button>
                </div>
              ) : null}
              <select
                value={category}
                onChange={(e) => onCategoryChange(e.target.value)}
                className="mb-2 h-11 w-full rounded-xl border border-zinc-200 bg-white px-3.5 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
              >
                <option value="">不限分类</option>
                {(catalog?.categories ?? []).map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
              <select
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                disabled={!category}
                className="h-11 w-full rounded-xl border border-zinc-200 bg-white px-3.5 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950"
              >
                <option value="">{category ? "选择具体岗位" : "请先选岗位方向"}</option>
                {rolesInCategory.map((r) => (
                  <option key={r.id} value={r.name}>
                    {r.name}
                  </option>
                ))}
              </select>
              {roleSuggestions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="text-[11px] text-zinc-400">简历建议：</span>
                  {roleSuggestions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => pickSuggestedRole(s)}
                      className={`rounded-full border px-2 py-0.5 text-[11px] transition ${
                        targetRole === s.name
                          ? "border-sky-500 bg-sky-50 text-sky-700"
                          : "border-zinc-200 text-zinc-500 hover:border-sky-300 hover:text-sky-700"
                      }`}
                    >
                      {s.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                目标企业 <span className="font-normal text-zinc-400">（可选）</span>
              </label>
              <select
                value={targetCompany}
                onChange={(e) => setTargetCompany(e.target.value)}
                className="h-11 w-full rounded-xl border border-zinc-200 bg-white px-3.5 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
              >
                <option value="">不限企业</option>
                {(catalog?.companies ?? []).map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-[11px] leading-4 text-zinc-400">
                选定后会贴近该岗位/企业高频考点；仍是一场独立面试。
              </p>
            </div>
            <div className="sm:col-span-2">
              <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                岗位 JD <span className="font-normal text-zinc-400">（可选）</span>
              </label>
              <textarea
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value.slice(0, 4000))}
                rows={4}
                placeholder="粘贴招聘 JD；仅用于题库召回加权，不会整段塞进规划 Prompt"
                className="w-full rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
              />
              <p className="mt-2 text-[11px] leading-4 text-zinc-400">
                与「自定义设置」里的练习焦点走同一路径：只影响检索排序，不锁死出题范围。
              </p>
            </div>
          </div>
        </div>
      </Card>

      <Card className="animate-fade-up p-5 sm:p-6" style={{ animationDelay: "0.06s" }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">面试形式</h2>
            <p className="mt-1 text-xs text-zinc-400">选形态与类型；轮次、去重、复习等放进自定义设置。</p>
          </div>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-700 transition hover:border-sky-300 hover:bg-sky-50/60 hover:text-sky-800 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200"
          >
            <IconSliders className="h-4 w-4" />
            自定义设置
            {customActive > 0 ? (
              <span className="ml-0.5 rounded-full bg-sky-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                {customActive}
              </span>
            ) : null}
          </button>
        </div>

        <div className="mt-5 space-y-5">
          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              面试形态
            </label>
            <div className="grid grid-cols-2 gap-3">
              {MODES.map((m) => {
                const selected = mode === m.value;
                return (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => {
                      setMode(m.value);
                      if (m.value === "full") setType("full");
                    }}
                    className={`relative rounded-xl border p-3.5 text-left transition-all duration-150 ${
                      selected
                        ? "border-sky-500 bg-sky-50/60 ring-2 ring-sky-500/20 dark:border-sky-500 dark:bg-sky-950/40"
                        : "border-zinc-200 bg-zinc-50/50 hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-950/40 dark:hover:border-zinc-700"
                    }`}
                  >
                    {selected && (
                      <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-sky-600 text-white">
                        <IconCheck className="h-3 w-3" />
                      </span>
                    )}
                    <div className="flex items-start gap-3">
                      <div
                        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                          selected
                            ? "bg-sky-600 text-white"
                            : "bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400"
                        }`}
                      >
                        {m.icon}
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                          {m.label}
                        </div>
                        <div className="mt-0.5 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
                          {m.desc}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
              面试类型
              {mode === "full" ? (
                <span className="ml-1.5 font-normal text-zinc-400">（全流程已锁定）</span>
              ) : null}
            </label>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              {TYPES.map((t) => {
                const disabled = mode === "full" && t.value !== "full";
                const selected = type === t.value && !disabled;
                return (
                  <button
                    key={t.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => setType(t.value)}
                    className={`relative rounded-xl border px-3 py-3 text-left transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-35 ${
                      selected
                        ? "border-sky-500 bg-sky-50/60 ring-2 ring-sky-500/20 dark:border-sky-500 dark:bg-sky-950/40"
                        : "border-zinc-200 bg-zinc-50/50 hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-950/40 dark:hover:border-zinc-700"
                    }`}
                  >
                    {selected && (
                      <span className="absolute right-2 top-2 flex h-4 w-4 items-center justify-center rounded-full bg-sky-600 text-white">
                        <IconCheck className="h-2.5 w-2.5" />
                      </span>
                    )}
                    <div
                      className={
                        selected ? "text-sky-600 dark:text-sky-400" : "text-sky-500/70 dark:text-sky-400/60"
                      }
                    >
                      {t.icon}
                    </div>
                    <div className="mt-2 text-sm font-medium text-zinc-900 dark:text-zinc-50">
                      {t.label}
                    </div>
                    <div className="mt-0.5 text-[11px] leading-4 text-zinc-500 dark:text-zinc-400">
                      {t.desc}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      <div
        className="animate-fade-up flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
        style={{ animationDelay: "0.1s" }}
      >
        <div className="min-w-0 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
          <span className="text-zinc-700 dark:text-zinc-300">
            {resumeName ?? "未选简历"}
          </span>
          <span className="mx-1.5 text-zinc-300">·</span>
          {modeLabel}
          {mode === "specialized" ? ` · ${typeLabel}` : null}
          <span className="mx-1.5 text-zinc-300">·</span>
          {custom.count} 轮
          {targetRole ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              {targetRole}
            </>
          ) : null}
          {targetCompany ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              {targetCompany}
            </>
          ) : null}
          {jobDescription.trim() ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              有 JD
            </>
          ) : null}
          {custom.skipCoding && mode === "full" ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              无算法
            </>
          ) : null}
          {custom.reviewMode ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              复习模式
            </>
          ) : null}
          {dedupLabel[custom.dedupScope] ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              {dedupLabel[custom.dedupScope]}
            </>
          ) : null}
          {custom.practiceFocus.trim() ? (
            <>
              <span className="mx-1.5 text-zinc-300">·</span>
              有焦点
            </>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center">
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="inline-flex h-11 items-center justify-center gap-1.5 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-700 transition hover:border-sky-300 hover:bg-sky-50/60 dark:border-zinc-700 dark:bg-zinc-950"
          >
            <IconSliders className="h-4 w-4" />
            自定义设置
            {customActive > 0 ? (
              <span className="rounded-full bg-sky-600 px-1.5 py-0.5 text-[10px] text-white">
                {customActive}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            onClick={start}
            disabled={creating || !resumeId}
            className="h-11 rounded-xl bg-gradient-to-r from-sky-600 to-emerald-600 px-8 text-sm font-semibold text-white shadow-lg shadow-sky-600/25 transition-all hover:from-sky-500 hover:to-emerald-500 hover:shadow-xl hover:shadow-sky-600/30 active:from-sky-700 active:to-emerald-700 disabled:opacity-50 sm:min-w-[180px]"
          >
            {creating
              ? "规划中，约 1～3 分钟…"
              : custom.practiceFocus.trim() || custom.reviewMode
                ? "开始本场定向面试 →"
                : "开始面试 →"}
          </button>
        </div>
      </div>

      <CustomSettingsModal
        open={settingsOpen}
        value={custom}
        mode={mode}
        onChange={setCustom}
        onClose={() => setSettingsOpen(false)}
      />

      {creating ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-sky-100 bg-white p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-zinc-900">正在规划本场面试</h3>
            <p className="mt-1.5 text-sm text-zinc-500">
              检索题库、生成拷打链并拼题单，通常 1～3 分钟，请勿关闭页面
            </p>
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
                <span>{planLabel}</span>
                <span>{planProgress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-500 transition-all duration-500"
                  style={{ width: `${Math.max(3, planProgress)}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function NewInterviewPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center text-sm text-zinc-400">加载中…</div>
      }
    >
      <NewInterviewForm />
    </Suspense>
  );
}
