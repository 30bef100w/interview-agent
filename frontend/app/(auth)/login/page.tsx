"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import AuthModal from "@/components/AuthModal";
import { getToken } from "@/lib/api";

/** 独立路由仍可用：浅色底 + 弹窗，与首页一致。 */
export default function LoginPage() {
  const router = useRouter();
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (getToken()) router.replace("/dashboard");
  }, [router]);

  return (
    <div className="relative flex min-h-[100svh] flex-1 items-center justify-center overflow-hidden bg-gradient-to-br from-sky-50 via-white to-sky-50">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute left-[-8%] top-[-10%] h-[380px] w-[380px] rounded-full bg-sky-200/35 blur-3xl" />
        <div className="absolute bottom-[-12%] right-[-6%] h-[340px] w-[340px] rounded-full bg-sky-200/30 blur-3xl" />
      </div>
      <AuthModal
        open={open}
        mode="login"
        onClose={() => {
          setOpen(false);
          router.push("/");
        }}
      />
    </div>
  );
}
