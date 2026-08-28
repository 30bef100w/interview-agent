"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { api, getToken } from "@/lib/api";

/** 用户侧 trace 已迁至运维后台，此页仅做重定向 */
export default function ReportTraceRedirectPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<{ is_admin?: boolean }>("/api/auth/me")
      .then((me) => {
        if (me.is_admin) {
          router.replace(`/admin/observability/sessions/${sessionId}`);
        } else {
          router.replace(`/report/${sessionId}`);
        }
      })
      .catch(() => router.replace(`/report/${sessionId}`));
  }, [router, sessionId]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-slate-500">
      跳转中…
    </div>
  );
}
