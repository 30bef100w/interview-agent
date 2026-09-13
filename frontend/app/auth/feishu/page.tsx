"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { setToken } from "@/lib/api";

function FeishuAuthBody() {
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    const token = params.get("token");
    const username = params.get("username") || "";
    if (!token) {
      router.replace("/login?feishu_error=" + encodeURIComponent("飞书登录没有拿到凭证"));
      return;
    }
    setToken(token);
    if (username) localStorage.setItem("username", username);
    router.replace("/dashboard");
  }, [params, router]);

  return (
    <div className="flex min-h-[100svh] items-center justify-center bg-gradient-to-br from-sky-50 via-white to-sky-50 text-sm text-zinc-500">
      正在完成飞书登录…
    </div>
  );
}

export default function FeishuAuthLanding() {
  return (
    <Suspense>
      <FeishuAuthBody />
    </Suspense>
  );
}
