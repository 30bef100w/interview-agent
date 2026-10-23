import { API_BASE, ApiError, errorDetail, getToken } from "@/lib/api";

export type StreamHandlers = {
  onToken?: (text: string) => void;
  onDone?: (data: unknown) => void;
  onError?: (message: string) => void;
};

/** POST + SSE 流式读取。后端事件：token（JSON 字符串片段）/ done（最终 JSON）/ error（错误信息）。 */
export async function streamPost(
  path: string,
  body: unknown,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken() ?? ""}`,
    },
    body: JSON.stringify(body),
    signal: signal ?? AbortSignal.timeout(20 * 60 * 1000),
  });
  if (!res.ok || !res.body) {
    let detail = `请求失败 (${res.status})`;
    try {
      const j = await res.json();
      detail = errorDetail(j.detail, detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let terminal = false;
  try {
   for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      if (!terminal) {
        const message = "连接提前结束，提交结果尚未确认，请刷新进度后重试";
        if (handlers.onError) handlers.onError(message);
        else throw new Error(message);
      }
      break;
    }
    buf += decoder.decode(value, { stream: true });
    buf = buf.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      const data = dataLines.join("\n");
      if (!data) continue;
      if (event === "token") {
        handlers.onToken?.(JSON.parse(data));
      } else if (event === "done") {
        terminal = true;
        handlers.onDone?.(JSON.parse(data));
        return;
      } else if (event === "error") {
        terminal = true;
        const message = errorDetail(JSON.parse(data), "处理失败，请刷新进度后重试");
        if (handlers.onError) handlers.onError(message);
        else throw new Error(message);
        return;
      } else {
        throw new Error(`无法识别服务端事件：${event}`);
      }
    }
   }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
