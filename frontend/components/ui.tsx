import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

/* ================= 按钮 ================= */

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";

export function btnCls(
  variant: BtnVariant = "primary",
  size: "sm" | "md" | "lg" = "md",
  extra = ""
): string {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition-all duration-150 disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/50";
  const sizes = {
    sm: "px-3 py-1.5 text-xs",
    md: "px-4 py-2 text-sm",
    lg: "px-6 py-3 text-sm",
  };
  const variants: Record<BtnVariant, string> = {
    primary:
      "bg-sky-600 text-white shadow-sm shadow-sky-600/25 hover:bg-sky-500 active:bg-sky-700",
    secondary:
      "border border-zinc-200 bg-white text-zinc-700 shadow-sm hover:border-sky-200 hover:bg-sky-50/50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-600 dark:hover:bg-zinc-800",
    ghost:
      "text-zinc-600 hover:bg-sky-50 hover:text-sky-800 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-zinc-50",
    danger:
      "bg-red-600 text-white shadow-sm shadow-red-600/25 hover:bg-red-500",
  };
  return `${base} ${sizes[size]} ${variants[variant]} ${extra}`;
}

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className = "",
  children,
}: {
  href: string;
  variant?: BtnVariant;
  size?: "sm" | "md" | "lg";
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={btnCls(variant, size, className)}>
      {children}
    </Link>
  );
}

/* ================= 卡片 ================= */

export function Card({
  className = "",
  style,
  children,
}: {
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <div
      className={`rounded-2xl border border-zinc-200/80 bg-white shadow-sm shadow-zinc-900/[0.03] dark:border-zinc-800 dark:bg-zinc-900 ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}

/* ================= 徽标 ================= */

type Tone = "zinc" | "green" | "amber" | "red" | "sky" | "emerald" | "indigo" | "teal";

const TONE_CLS: Record<Tone, string> = {
  zinc: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  amber: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  red: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  sky: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  indigo: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  teal: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  emerald: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
};

export function Badge({
  tone = "zinc",
  className = "",
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE_CLS[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/* ================= 品牌 Logo ================= */

export function Logo({
  size = "md",
  withText = true,
}: {
  size?: "sm" | "md" | "lg";
  withText?: boolean;
}) {
  const box =
    size === "sm"
      ? "h-7 w-7 rounded-lg"
      : size === "md"
        ? "h-9 w-9 rounded-xl"
        : "h-12 w-12 rounded-2xl";
  const title = size === "sm" ? "text-base" : size === "md" ? "text-lg" : "text-2xl";
  const glyph = size === "sm" ? "text-sm" : size === "md" ? "text-base" : "text-xl";
  const sub = size === "sm" ? "text-[9px]" : size === "md" ? "text-[10px]" : "text-xs";
  return (
    <span className="inline-flex items-center gap-2.5">
      <span
        className={`${box} relative flex items-center justify-center overflow-hidden bg-gradient-to-br from-indigo-600 via-sky-600 to-cyan-500 text-white shadow-md shadow-indigo-600/25`}
      >
        <span className={`font-brand ${glyph} font-bold`}>深</span>
        <span
          aria-hidden
          className="pointer-events-none absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-white/25 blur-[1px]"
        />
      </span>
      {withText && (
        <span className="inline-flex flex-col leading-none">
          <span className={`font-brand ${title} font-semibold tracking-tight text-slate-900 dark:text-zinc-50`}>
            深问
          </span>
          <span className={`${sub} mt-0.5 font-medium tracking-[0.14em] text-sky-600/80`}>DEEPASK</span>
        </span>
      )}
    </span>
  );
}

/* ================= 返回链接 ================= */

export function BackLink({ href, label = "返回" }: { href: string; label?: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
    >
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M10 3 5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label}
    </Link>
  );
}

/* ================= 错误条 ================= */

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-400">
      <span>加载失败：{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded-md border border-red-300 px-3 py-1 text-xs font-medium transition-colors hover:bg-red-100 dark:border-red-800 dark:hover:bg-red-900/40"
        >
          重试
        </button>
      )}
    </div>
  );
}

/* ================= 空状态 ================= */

export function EmptyState({
  icon,
  title,
  desc,
  action,
}: {
  icon?: ReactNode;
  title: string;
  desc?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-zinc-300 px-6 py-16 text-center dark:border-zinc-700">
      {icon && <div className="text-zinc-300 dark:text-zinc-600">{icon}</div>}
      <div className="text-sm font-medium text-zinc-600 dark:text-zinc-300">{title}</div>
      {desc && <div className="max-w-sm text-xs text-zinc-400 dark:text-zinc-500">{desc}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/* ================= 图标 ================= */

type IconProps = { className?: string };

export function IconMic({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
    </svg>
  );
}

export function IconUpload({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M12 16V4m0 0 4 4m-4-4L8 8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" strokeLinecap="round" />
    </svg>
  );
}

export function IconHistory({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3 4v4h4M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function IconPlay({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor">
      <path d="M8 5.5v13a1 1 0 0 0 1.53.85l10.2-6.5a1 1 0 0 0 0-1.7L9.53 4.65A1 1 0 0 0 8 5.5Z" />
    </svg>
  );
}

export function IconArrowRight({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M5 12h14m-6-6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function IconCheck({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2.2">
      <path d="m5 13 4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function IconCode({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="m8 6-6 6 6 6m8-12 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function IconSparkles({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor">
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" />
      <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z" opacity="0.7" />
    </svg>
  );
}

export function IconChat({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M21 12a8 8 0 0 1-8 8H4l2.3-2.9A8 8 0 1 1 21 12Z" strokeLinejoin="round" />
      <path d="M8.5 11h.01M12 11h.01M15.5 11h.01" strokeLinecap="round" strokeWidth="2.4" />
    </svg>
  );
}

export function IconFile({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V8l-4-5Z" strokeLinejoin="round" />
      <path d="M14 3v5h5M9.5 13h5M9.5 17h5" strokeLinecap="round" />
    </svg>
  );
}

export function IconReport({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M4 20V5a1 1 0 0 1 1-1h9l5 5v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1Z" strokeLinejoin="round" />
      <path d="M8.5 12h7M8.5 15.5h4" strokeLinecap="round" />
    </svg>
  );
}

export function IconTarget({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconChart({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M4 19V5" strokeLinecap="round" />
      <path d="M4 19h16" strokeLinecap="round" />
      <path d="M7 15l3.5-4.5 3 2.5L17 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function IconUser({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20a7 7 0 0 1 14 0" strokeLinecap="round" />
    </svg>
  );
}

export function IconSend({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor">
      <path d="M3.4 20.4 20.8 12 3.4 3.6 3.4 10l12 2-12 2v6.4Z" />
    </svg>
  );
}

export function IconSliders({ className = "h-4 w-4" }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" strokeLinecap="round" />
      <circle cx="16" cy="7" r="2.5" />
      <circle cx="8" cy="17" r="2.5" />
    </svg>
  );
}
