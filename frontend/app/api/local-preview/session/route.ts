import { NextResponse } from "next/server";

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);
const noStore = { "Cache-Control": "no-store", Vary: "Origin" };

/** Only an explicitly enabled local development launcher supplies these credentials. */
export async function POST(request: Request) {
  if (process.env.NODE_ENV !== "development" || process.env.DEEPASK_LOCAL_PREVIEW !== "1") {
    return new NextResponse(null, { status: 404, headers: noStore });
  }
  const host = request.headers.get("host");
  const backend = new URL(process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8001");
  if (!host || !LOOPBACK.has(new URL(request.url).hostname) ||
      !LOOPBACK.has(new URL(`http://${host}`).hostname) || !LOOPBACK.has(backend.hostname) ||
      backend.protocol !== "http:" || request.headers.get("origin") !== `http://${host}` ||
      request.headers.get("x-deepask-preview") !== "1") {
    return new NextResponse(null, { status: 403, headers: noStore });
  }
  const username = process.env.DEEPASK_PREVIEW_USERNAME;
  const password = process.env.DEEPASK_PREVIEW_PASSWORD;
  if (!username || !password) return new NextResponse(null, { status: 404, headers: noStore });
  try {
    const login = await fetch(new URL("/api/auth/login", backend), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }), cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    if (!login.ok) throw new Error("Preview sign-in failed");
    const session = await login.json();
    // Preserve the backend's normal authentication and administrator permission checks.
    if (!session.access_token || !session.user?.is_admin) throw new Error("Preview account unavailable");
    return NextResponse.json(session, { headers: noStore });
  } catch {
    return NextResponse.json({ detail: "本地预览服务暂时不可用，请重试" }, { status: 503, headers: noStore });
  }
}
