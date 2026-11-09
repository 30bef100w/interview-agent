"use client";

import Link, { useLinkStatus } from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { AdminIcon, type IconName } from "@/components/admin/AdminUI";
import { ToastProvider } from "@/components/Toast";
import { ApiError, api, clearToken, getToken } from "@/lib/api";
import { startLocalAdminPreview } from "@/lib/admin-preview";
import s from "./admin.module.css";

const NAV: { href: string; label: string; icon: IconName; group: string }[] = [
  { href: "/admin", label: "运营概览", icon: "overview", group: "工作空间" },
  { href: "/admin/users", label: "用户管理", icon: "users", group: "工作空间" },
  { href: "/admin/sessions", label: "面试会话", icon: "sessions", group: "工作空间" },
  { href: "/admin/usage", label: "用量与成本", icon: "usage", group: "工作空间" },
  { href: "/admin/observability", label: "运行监控", icon: "activity", group: "质量与监控" },
  { href: "/admin/logs", label: "系统日志", icon: "logs", group: "质量与监控" },
  { href: "/admin/tag-mismatches", label: "题库审核", icon: "review", group: "质量与监控" },
];

function NavigationProgress() {
  const { pending } = useLinkStatus();
  return <span className={s.navigationProgress} role="status" aria-live="polite">{pending ? "加载中…" : ""}</span>;
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [ready, setReady] = useState(false);
  const [preview, setPreview] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const current = NAV.find(item => item.href === pathname) || NAV.find(item => item.href !== "/admin" && pathname.startsWith(item.href)) || NAV[0];

  useEffect(() => {
    let active = true;
    setError("");
    setReady(false);
    async function connect() {
      try {
        await startLocalAdminPreview();
        if (!active) return;
        if (!getToken()) {
          if (active) router.replace("/login");
          return;
        }
        let me;
        try {
          me = await api<{ username: string; is_admin?: boolean }>("/api/auth/me");
        } catch (err) {
          if (!(err instanceof ApiError) || ![401, 403].includes(err.status)) throw err;
          clearToken();
          if (!await startLocalAdminPreview()) {
            if (active) router.replace("/login");
            return;
          }
          me = await api<{ username: string; is_admin?: boolean }>("/api/auth/me");
        }
        if (!active) return;
        if (!me.is_admin) { router.replace("/dashboard"); return; }
        setUsername(me.username);
        setPreview(sessionStorage.getItem("deepask-local-preview") === "1");
        setReady(true);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "后台连接暂时失败");
      }
    }
    void connect();
    return () => { active = false; };
  }, [router, retry]);

  if (!ready) return <div className={s.connecting}><div className={s.brandMark}>问</div><strong>{error || "正在打开深问运营平台…"}</strong>{error ? <button className={s.button} onClick={() => setRetry(n => n + 1)}>重新连接</button> : <p>连接工作空间</p>}</div>;

  return <ToastProvider><div className={s.shell}>
    <aside className={s.sidebar}>
      <Link href="/admin" className={s.brand}><span className={s.brandMark}>问</span><span><strong>深问<span className={s.brandEnglish}>DeepAsk</span></strong><small>运营工作空间</small></span></Link>
      <div className={s.workspace}><span className={s.workspaceAvatar}>D</span><span><strong>深问运营平台</strong><small>{preview ? "本地预览环境" : "管理工作空间"}</small></span></div>
      <nav aria-label="运营导航" className={s.nav}>
        {["工作空间", "质量与监控"].map(group => <div className={s.navGroup} key={group}><div className={s.navLabel}>{group}</div>{NAV.filter(item => item.group === group).map(item => <Link key={item.href} href={item.href} aria-current={current.href === item.href ? "page" : undefined} className={`${s.navItem} ${current.href === item.href ? s.navActive : ""}`}><AdminIcon name={item.icon} /><span>{item.label}</span><NavigationProgress />{current.href === item.href && <span className={s.activeDot} />}</Link>)}</div>)}
      </nav>
      <div className={s.sidebarBottom}><Link href="/dashboard" className={s.returnLink}><AdminIcon name="external" /><span>打开用户端</span><span>↗</span></Link><div className={s.profile}><span className={s.avatar}>{username.slice(0, 1).toUpperCase()}</span><span><strong>{preview ? "本地预览" : username}</strong><small>{preview ? "自动连接 · 无需手动登录" : "管理员"}</small></span><span className={s.onlineDot} /></div></div>
    </aside>
    <div className={s.main}>
      <header className={s.topbar}><div className={s.breadcrumb}><span>工作空间</span><span>/</span><strong>{current.label}</strong></div><div className={s.topbarRight}><span className={s.environment}><i />{preview ? "本地预览" : "管理后台"}</span><span className={s.headerDivider} /><span className={s.headerAvatar}>{username.slice(0, 1).toUpperCase()}</span></div></header>
      <main className={s.content}>{children}</main>
      <footer className={s.footer}><span>深问 DeepAsk · 让每次面试练习更进一步</span><span>运营工作空间</span></footer>
    </div>
  </div></ToastProvider>;
}
