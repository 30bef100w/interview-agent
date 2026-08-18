"""M7 冒烟：SSE 流式 answer 接口 + 历史接口。"""
import json
import random
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8001"
PWD = Path(__file__).resolve().parents[1] / "data" / "test_resume.pdf"


def req(method: str, path: str, body=None, token: str | None = None, raw: bool = False):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=180) as resp:
        content = resp.read()
    return content if raw else json.loads(content.decode("utf-8"))


def main() -> int:
    name = f"smoke_m7_{random.randint(1000, 9999)}"
    req("POST", "/api/auth/register", {"username": name, "password": "test123456"})
    token = req("POST", "/api/auth/login", {"username": name, "password": "test123456"})["access_token"]

    boundary = "----smoke"
    pdf = PWD.read_bytes()
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test_resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + pdf + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = urllib.request.Request(
        BASE + "/api/resume/upload",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(r, timeout=60) as resp:
        resume_id = json.loads(resp.read().decode("utf-8"))["id"]

    s = req("POST", "/api/interview/session",
            {"resume_id": resume_id, "interview_mode": "full", "interview_type": "full", "question_count": 8}, token)
    sid = s["session_id"]

    # SSE 流式回答自我介绍
    raw = req("POST", f"/api/interview/session/{sid}/answer/stream",
              {"text": "我叫张三，两年后端开发经验，做过校园二手交易平台和工单系统。"}, token, raw=True)
    text = raw.decode("utf-8")
    events = [e for e in text.split("\n\n") if e.strip()]
    kinds = [e.split("\n", 1)[0] for e in events]
    print("事件序列:", kinds[:6], "... 共", len(events), "个事件")
    tokens = [json.loads(e.split("data: ", 1)[1]) for e in events if e.startswith("event: token")]
    done = json.loads(events[-1].split("data: ", 1)[1])
    print(f"流式 token 数: {len(tokens)}，累计 {len(''.join(tokens))} 字符")
    print("拼接示例:", "".join(tokens)[:50])
    print("done 事件: stage={} status={} finished={} message[:40]={}".format(
        done["stage"], done["status"], done["finished"], done["message"][:40]))
    assert done["stage"] == "ASKING"
    assert "".join(tokens).strip() == done["message"], "token 拼接与最终消息不一致"

    # 历史接口
    history = req("GET", "/api/interview/history", token=token)
    print(f"历史记录数: {len(history)}")
    item = next(h for h in history if h["session_id"] == sid)
    print(f"  该会话: mode={item['mode']} status={item['status']} rounds={item['rounds_used']} has_report={item['has_report']}")

    # 再答一轮普通 JSON 接口（兼容性回归）
    ans = req("POST", f"/api/interview/session/{sid}/answer",
              {"text": "库存超卖我用 Redis 预扣加 Lua 脚本解决，压测 QPS 提升六倍。"}, token)
    print(f"普通 answer 接口: stage={ans['stage']} message[:40]={ans['message'][:40]}")
    print("SMOKE_M7 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
