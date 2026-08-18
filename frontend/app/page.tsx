"use client";

import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";

import AuthModal from "@/components/AuthModal";
import { IconCode, IconMic, IconReport, IconTarget, Logo } from "@/components/ui";

const NAV_LINKS = [
  { id: "product", label: "产品能力" },
  { id: "highlights", label: "能力亮点" },
  { id: "steps", label: "使用流程" },
];

const DEMOS = [
  {
    title: "多轮追问面试",
    desc: "读懂简历，针对项目与技术栈深挖，像真一面一样推进。",
    image: "/chat-preview.png?v=4",
    url: "interview.app / session",
  },
  {
    title: "能力复盘报告",
    desc: "逐题打分、雷达图与参考答案，练完立刻知道差在哪。",
    image: "/report-preview.png?v=4",
    url: "interview.app / report",
  },
  {
    title: "从简历到开练",
    desc: "上传简历、选环节、设轮次，一分钟进入模拟面试。",
    image: "/dashboard-preview.png?v=4",
    url: "interview.app / dashboard",
  },
];

const HERO_FEATURES = [
  { icon: <IconMic className="h-4 w-4" />, title: "多轮追问面试" },
  { icon: <IconCode className="h-4 w-4" />, title: "手撕算法判题" },
  { icon: <IconReport className="h-4 w-4" />, title: "量化评分报告" },
  { icon: <IconTarget className="h-4 w-4" />, title: "项目 / 八股 / HR" },
];

const HIGHLIGHTS = [
  {
    icon: <IconMic className="h-5 w-5" />,
    title: "可控的技术面节奏",
    desc: "自我介绍 → 项目 / 八股 / 手撕 / HR → 反问 → 终评，不是闲聊套壳。",
  },
  {
    icon: <IconCode className="h-5 w-5" />,
    title: "手撕 + 判题",
    desc: "在线编辑器支持函数模式与手撕模式，运行示例、对拍与 AI 点评。",
  },
  {
    icon: <IconReport className="h-5 w-5" />,
    title: "可解释的评分",
    desc: "逐题依据作答打分，空答不高分，报告可导出 Word / PDF。",
  },
];

const STEPS = [
  { n: "01", t: "上传简历", d: "解析技术栈与项目画像" },
  { n: "02", t: "选择环节", d: "全流程或专项突击" },
  { n: "03", t: "模拟面试", d: "文字 / 语音作答，智能追问" },
  { n: "04", t: "查看报告", d: "维度评分与逐题复盘" },
];

/** 标题逐字悬浮上浮变色 */
function InteractiveChars({ text, className = "" }: { text: string; className?: string }) {
  return (
    <span className={className} aria-label={text}>
      {Array.from(text).map((ch, i) =>
        ch === " " ? (
          <span key={i}>{"\u00A0"}</span>
        ) : (
          <span key={i} className="hero-char" style={{ transitionDelay: `${i * 12}ms` }}>
            {ch}
          </span>
        )
      )}
    </span>
  );
}

/** 磁吸按钮：跟随光标轻微位移 + 光斑 */
function MagneticButton({
  children,
  className = "",
  onClick,
  variant = "primary",
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  variant?: "primary" | "dark" | "ghost" | "white";
}) {
  const ref = useRef<HTMLButtonElement>(null);

  function onMove(e: MouseEvent<HTMLButtonElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const dx = (x - rect.width / 2) / 10;
    const dy = (y - rect.height / 2) / 14;
    el.style.setProperty("--mx", `${x}px`);
    el.style.setProperty("--my", `${y}px`);
    el.style.transform = `translate(${dx}px, ${dy - 2}px) scale(1.03)`;
  }

  function onLeave() {
    const el = ref.current;
    if (!el) return;
    el.style.transform = "";
  }

  const variants = {
    primary:
      "bg-sky-600 text-white shadow-lg shadow-sky-600/25 hover:bg-sky-500 hover:shadow-xl hover:shadow-sky-600/35",
    dark: "bg-slate-900 text-white shadow-md shadow-slate-900/20 hover:bg-slate-800",
    ghost:
      "border border-slate-200 bg-white/80 text-slate-700 btn-ghost-lift hover:border-sky-300 hover:text-sky-800",
    white: "bg-white text-sky-800 shadow-md hover:bg-sky-50",
  };

  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={`btn-magnetic inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-medium ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

function BrowserFrame({ title, image }: { title: string; image: string }) {
  return (
    <div className="group overflow-hidden rounded-2xl border border-sky-100/80 bg-white shadow-[0_20px_60px_-28px_rgba(2,132,199,0.28)] transition duration-300 hover:-translate-y-1 hover:shadow-[0_28px_70px_-28px_rgba(2,132,199,0.4)]">
      <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-300" />
        <span className="ml-2 flex-1 truncate rounded-md bg-zinc-100 px-3 py-1 text-[11px] text-zinc-400">
          {title}
        </span>
      </div>
      <div className="aspect-[16/10] overflow-hidden bg-zinc-50">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={image}
          alt={title}
          className="h-full w-full object-cover object-top"
        />
      </div>
    </div>
  );
}

export default function Home() {
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("register");
  const [spot, setSpot] = useState({ x: 0, y: 0, on: false });
  const [scrolled, setScrolled] = useState(false);
  const heroRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function openAuth(mode: "login" | "register") {
    setAuthMode(mode);
    setAuthOpen(true);
  }

  function scrollToId(id: string) {
    const el = document.getElementById(id);
    if (!el) return;
    const headerH = document.querySelector("header")?.getBoundingClientRect().height ?? 68;
    const top = el.getBoundingClientRect().top + window.scrollY - headerH - 8;
    window.scrollTo({ top, behavior: "smooth" });
  }

  function onHeroMove(e: MouseEvent<HTMLElement>) {
    const rect = heroRef.current?.getBoundingClientRect();
    if (!rect) return;
    setSpot({ x: e.clientX - rect.left, y: e.clientY - rect.top, on: true });
  }

  return (
    <div className="flex flex-1 flex-col bg-white text-slate-900">
      {/* 吸顶顶栏：滚动始终可见 */}
      <header
        className={`sticky top-0 z-40 border-b transition-all duration-300 ${
          scrolled
            ? "border-sky-100/90 bg-white/90 shadow-sm shadow-sky-900/5 backdrop-blur-md"
            : "border-transparent bg-white/75 backdrop-blur-sm"
        }`}
      >
        <div className="mx-auto flex h-[68px] w-full max-w-6xl items-center justify-between gap-4 px-6">
          <button
            type="button"
            onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
            className="inline-flex shrink-0 items-center gap-2.5 rounded-xl transition hover:opacity-90"
          >
            <Logo />
          </button>

          <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-12 md:flex">
            {NAV_LINKS.map((link) => (
              <button
                key={link.id}
                type="button"
                onClick={() => scrollToId(link.id)}
                className="text-[15px] font-medium text-slate-500 transition hover:text-sky-700"
              >
                {link.label}
              </button>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-2">
            <MagneticButton variant="ghost" className="!px-4 !py-2" onClick={() => openAuth("login")}>
              登录
            </MagneticButton>
            <MagneticButton variant="dark" className="!px-5 !py-2" onClick={() => openAuth("register")}>
              开始使用
            </MagneticButton>
          </div>
        </div>
        <nav className="flex items-center justify-center gap-8 border-t border-sky-50/80 px-4 py-2.5 md:hidden">
          {NAV_LINKS.map((link) => (
            <button
              key={link.id}
              type="button"
              onClick={() => scrollToId(link.id)}
              className="text-sm font-medium text-slate-500 transition hover:text-sky-700"
            >
              {link.label}
            </button>
          ))}
        </nav>
      </header>

      <section
        ref={heroRef}
        onMouseMove={onHeroMove}
        onMouseLeave={() => setSpot((s) => ({ ...s, on: false }))}
        className="relative flex min-h-[calc(100svh-68px)] flex-col overflow-hidden bg-gradient-to-br from-sky-50 via-white to-blue-50"
      >
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute -left-24 top-10 h-72 w-72 rounded-full bg-sky-200/45 blur-3xl" />
          <div className="absolute right-0 top-1/3 h-80 w-80 rounded-full bg-blue-200/35 blur-3xl" />
          <div className="absolute bottom-0 left-1/3 h-64 w-64 rounded-full bg-indigo-100/40 blur-3xl" />
        </div>
        <div
          aria-hidden
          className="hero-spotlight"
          style={{ left: spot.x, top: spot.y, opacity: spot.on ? 1 : 0 }}
        />

        <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-6 pb-20 pt-10 lg:flex-row lg:items-center lg:gap-14">
          <div className="max-w-xl lg:max-w-2xl">
            <p className="hero-fade inline-flex cursor-default items-center gap-2 rounded-full bg-sky-100/90 px-3.5 py-1 text-xs font-medium text-sky-800 transition hover:bg-sky-200/80 hover:shadow-sm">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-500" />
              AI 驱动的技术面训练引擎
            </p>
            <h1 className="font-brand hero-fade mt-6 text-[2.5rem] font-bold leading-[1.15] tracking-tight text-slate-900 sm:text-5xl md:text-6xl lg:text-[4rem]">
              <InteractiveChars text="技术面试的" />
              <br />
              <InteractiveChars text="训练引擎" />
            </h1>
            <p
              className="hero-fade mt-6 max-w-lg text-base leading-8 text-slate-600 sm:text-lg"
              style={{ animationDelay: "0.1s" }}
            >
              不只是简单问答。用可控状态机还原真实技术面：
              <span className="hero-phrase">简历深挖</span>、
              <span className="hero-phrase">手撕判题</span>、
              <span className="hero-phrase">逐题评分</span>
              ，帮你更快拿到理想 Offer。
            </p>
            <div className="hero-fade mt-9 flex flex-wrap items-center gap-3" style={{ animationDelay: "0.18s" }}>
              <MagneticButton
                variant="primary"
                className="!px-7 !py-3.5"
                onClick={() => openAuth("register")}
              >
                立即开始模拟面试
                <span aria-hidden className="btn-arrow">
                  →
                </span>
              </MagneticButton>
              <MagneticButton variant="ghost" onClick={() => openAuth("login")}>
                已有账号
              </MagneticButton>
            </div>
            <div
              className="hero-fade mt-10 grid max-w-md grid-cols-2 gap-x-6 gap-y-4"
              style={{ animationDelay: "0.24s" }}
            >
              {HERO_FEATURES.map((f) => (
                <div
                  key={f.title}
                  className="group flex items-center gap-2.5 text-sm text-slate-600 transition hover:text-sky-700"
                >
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-sky-100 text-sky-700 transition group-hover:bg-sky-600 group-hover:text-white">
                    {f.icon}
                  </span>
                  {f.title}
                </div>
              ))}
            </div>
          </div>

          <div className="hero-fade mt-12 w-full max-w-xl lg:mt-0" style={{ animationDelay: "0.28s" }}>
            <BrowserFrame title="interview.app / session" image="/chat-preview.png?v=4" />
          </div>
        </div>

        <button
          type="button"
          onClick={() => scrollToId("product")}
          className="absolute bottom-6 left-1/2 z-10 -translate-x-1/2 cursor-pointer"
        >
          <div className="hero-scroll flex flex-col items-center gap-2 text-[11px] tracking-[0.18em] text-sky-700/50 transition hover:text-sky-700">
            <span>下滑了解更多</span>
            <span className="block h-7 w-px bg-gradient-to-b from-sky-500/50 to-transparent" />
          </div>
        </button>
      </section>

      <section id="product" className="scroll-mt-24 bg-white">
        <div className="mx-auto w-full max-w-6xl px-6 py-20 sm:py-24">
          <p className="text-xs font-medium tracking-[0.18em] text-sky-700/80">PRODUCT</p>
          <h2 className="font-brand mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            <InteractiveChars text="像真一面一样练" />
          </h2>
          <p className="mt-4 max-w-xl text-base leading-7 text-slate-500">
            <span className="hero-phrase">从开场对话到手撕算法</span>
            、再到终评报告，完整走完技术面流程。
          </p>
          <div className="mt-12 grid gap-8 lg:grid-cols-2">
            {DEMOS.slice(0, 2).map((d) => (
              <div key={d.title} className="group/card">
                <h3 className="font-brand text-xl font-semibold transition group-hover/card:text-sky-700">
                  {d.title}
                </h3>
                <p className="mt-2 mb-5 text-sm leading-7 text-slate-500">{d.desc}</p>
                <BrowserFrame title={d.url} image={d.image} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="highlights" className="scroll-mt-24 bg-gradient-to-b from-sky-50/90 via-blue-50/40 to-white">
        <div className="mx-auto grid w-full max-w-6xl gap-10 px-6 py-20 sm:grid-cols-3 sm:gap-8 sm:py-24">
          {HIGHLIGHTS.map((h) => (
            <div
              key={h.title}
              className="group rounded-2xl border border-sky-100/60 bg-white/70 p-6 transition duration-300 hover:-translate-y-1 hover:border-sky-200 hover:shadow-lg hover:shadow-sky-900/5"
            >
              <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-full bg-sky-100 text-sky-700 transition group-hover:scale-110 group-hover:bg-sky-600 group-hover:text-white">
                {h.icon}
              </div>
              <h3 className="text-base font-semibold text-slate-900 transition group-hover:text-sky-800">
                {h.title}
              </h3>
              <p className="mt-2 text-sm leading-7 text-slate-500">{h.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-gradient-to-br from-sky-50 to-white">
        <div className="mx-auto grid w-full max-w-6xl items-center gap-10 px-6 py-20 lg:grid-cols-2 lg:py-24">
          <div>
            <p className="text-xs font-medium tracking-[0.18em] text-sky-700/80">WORKSPACE</p>
            <h2 className="font-brand mt-3 text-3xl font-semibold tracking-tight">
              <InteractiveChars text={DEMOS[2].title} />
            </h2>
            <p className="mt-4 text-base leading-7 text-slate-500">{DEMOS[2].desc}</p>
          </div>
          <BrowserFrame title={DEMOS[2].url} image={DEMOS[2].image} />
        </div>
      </section>

      <section id="steps" className="scroll-mt-24 bg-[#f0f7ff]">
        <div className="mx-auto w-full max-w-6xl px-6 py-20 sm:py-24">
          <h2 className="font-brand text-center text-3xl font-semibold tracking-tight">
            <InteractiveChars text="四步开始" />
          </h2>
          <p className="mx-auto mt-3 max-w-md text-center text-sm text-slate-500">
            浏览器打开即用，无需下载。
          </p>
          <ol className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s) => (
              <li
                key={s.n}
                className="group rounded-2xl border border-white bg-white/80 p-5 shadow-sm shadow-sky-900/5 transition duration-300 hover:-translate-y-1 hover:shadow-md"
              >
                <div className="font-brand text-3xl font-semibold text-sky-600 transition group-hover:scale-105 group-hover:text-sky-500">
                  {s.n}
                </div>
                <div className="mt-3 text-sm font-semibold text-slate-900 group-hover:text-sky-800">
                  {s.t}
                </div>
                <p className="mt-1.5 text-sm leading-6 text-slate-500">{s.d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="bg-gradient-to-b from-white to-sky-50">
        <div className="mx-auto w-full max-w-6xl px-6 pb-20 pt-8">
          <div className="relative overflow-hidden rounded-[2rem] border border-sky-100 bg-gradient-to-br from-sky-600 to-blue-600 px-8 py-14 text-center text-white shadow-xl shadow-sky-600/20 sm:px-14">
            <div
              aria-hidden
              className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-white/10 blur-2xl"
            />
            <h2 className="font-brand relative text-3xl font-semibold tracking-tight sm:text-4xl">
              <InteractiveChars text="下一场面试，多一分把握" />
            </h2>
            <p className="relative mx-auto mt-4 max-w-md text-sm leading-7 text-sky-50/90">
              把简历变成一场真实技术面，练到心里有底再上场。
            </p>
            <div className="relative mt-8">
              <MagneticButton variant="white" className="!px-7 !py-3.5" onClick={() => openAuth("register")}>
                立即体验
                <span aria-hidden className="btn-arrow">
                  →
                </span>
              </MagneticButton>
            </div>
          </div>
        </div>
      </section>

      <footer className="border-t border-sky-100/80 bg-white py-8 text-center text-xs text-slate-400">
        AI 面试模拟器 · 拟真技术面，帮你更快拿到 Offer
      </footer>

      <AuthModal
        open={authOpen}
        mode={authMode}
        onClose={() => setAuthOpen(false)}
        onModeChange={setAuthMode}
      />
    </div>
  );
}
