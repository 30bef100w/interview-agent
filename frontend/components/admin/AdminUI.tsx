import type { ReactNode } from "react";
import s from "@/app/admin/admin.module.css";

export type IconName = "overview" | "users" | "sessions" | "usage" | "logs" | "activity" | "review" | "arrow" | "refresh" | "external" | "check" | "clock";
const paths: Record<IconName, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /><circle cx="9" cy="7" r="4" /></>,
  sessions: <><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 2V11.5A8.5 8.5 0 0 1 9.5 3h3a8.5 8.5 0 0 1 8.5 8.5Z" /><path d="M7 9h8M7 13h5" /></>,
  usage: <><rect x="3" y="5" width="18" height="15" rx="3" /><path d="M3 9h18M7 15h4M7 5V3h10" /></>,
  logs: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h8M8 17h5" /></>,
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  review: <><path d="M9 4H5v17h14V4h-4" /><rect x="9" y="2" width="6" height="5" rx="1" /><path d="m8 14 3 3 5-6" /></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3" /></>,
  external: <><path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
};
export function AdminIcon({ name }: { name: IconName }) {
  return <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
export function PageHeading({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className={s.pageHeading}><div><h1>{title}</h1><p>{description}</p></div><div className={s.actions}>{children}</div></div>;
}
export function EmptyState({ title, description, icon = "sessions" }: { title: string; description: string; icon?: IconName }) {
  return <div className={s.empty}><div className={s.emptyIcon}><AdminIcon name={icon} /></div><strong>{title}</strong><p>{description}</p></div>;
}
export function AdminCard({ className = "", children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-xl border border-slate-200 bg-white ${className}`}>{children}</div>;
}
const statuses: Record<string, string> = { active: "进行中", finished: "已完成", failed: "失败", abandoned: "已放弃", creating: "准备中", created: "待开始" };
export function SessionStatus({ status }: { status: string }) {
  return <span className={`${s.badge} ${status === "finished" ? s.successBadge : status === "failed" ? s.dangerBadge : ""}`}>{statuses[status] || status}</span>;
}
export function formatTime(iso: string | null, short = false): string {
  if (!iso) return "—";
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", ...(short ? {} : { year: "numeric" }), month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}
