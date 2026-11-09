import s from "./admin.module.css";

export default function AdminLoading() {
  return <div className={s.page} role="status" aria-live="polite"><div className={s.analyticsLoading}>正在打开页面…</div></div>;
}
