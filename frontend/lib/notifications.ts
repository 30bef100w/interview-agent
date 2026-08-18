"use client";

/** 本地通知中心（先不依赖后端，后续可换成 API） */

export type AppNotification = {
  id: string;
  title: string;
  body: string;
  href?: string;
  kind: "resume" | "interview" | "report" | "system";
  read: boolean;
  createdAt: string;
};

const KEY = "fa_notifications";

function readAll(): AppNotification[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as AppNotification[];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function writeAll(list: AppNotification[]) {
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, 80)));
  window.dispatchEvent(new Event("fa-notifications"));
}

export function listNotifications(): AppNotification[] {
  return readAll().sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function unreadCount(): number {
  return readAll().filter((n) => !n.read).length;
}

export function pushNotification(
  input: Omit<AppNotification, "id" | "read" | "createdAt"> & { read?: boolean }
) {
  const item: AppNotification = {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: input.title,
    body: input.body,
    href: input.href,
    kind: input.kind,
    read: input.read ?? false,
    createdAt: new Date().toISOString(),
  };
  writeAll([item, ...readAll()]);
  return item;
}

export function markNotificationRead(id: string) {
  writeAll(readAll().map((n) => (n.id === id ? { ...n, read: true } : n)));
}

export function markAllNotificationsRead() {
  writeAll(readAll().map((n) => ({ ...n, read: true })));
}

export function clearNotifications() {
  writeAll([]);
}
