import { API_BASE, ApiError, getToken } from "@/lib/api";

export type StreamHandlers = {
  onToken?: (text: string) => void;
  onDone?: (data: unknown) => void;
  onError?: (message: string) => void;
};

/** POST + SSE 流式读取。后端事件：token（JSON 字符串片段）/ done（最终 JSON）/ error（错误信息）。 */
export async function streamPost(
  path: string,
  body: unknown,
  handlers: StreamHandlers
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken() ?? ""}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let detail = `请求失败 (${res.status})`;
    try {
      const j = await res.json();
      if (j.detail) detail = j.detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5);
      }
      if (!data) continue;
      if (event === "token") {
        handlers.onToken?.(JSON.parse(data));
      } else if (event === "done") {
        handlers.onDone?.(JSON.parse(data));
      } else if (event === "error") {
        handlers.onError?.(JSON.parse(data));
      } else {
        handlers.onError?.(`未知事件：${event}`);
      }
    }
  }
}
