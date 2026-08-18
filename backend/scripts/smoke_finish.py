"""M7 收尾冒烟：全程走 SSE 流式接口直到面试结束，验证报告与历史。"""
import json
import random
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8001"
PWD = Path(__file__).resolve().parents[1] / "data" / "test_resume.pdf"
ANSWER = (
    "我在校园二手交易平台项目里负责后端，用 Spring Boot 加 MySQL 实现，Redis 缓存热点商品并做库存预扣。"
    "遇到超卖问题，我用 Lua 脚本保证预扣的原子性，压测 QPS 从 500 提升到 3000。"
    "数据库慢查询通过加联合索引优化，从 200ms 降到 20ms。"
    "实习时做过工单系统，用 Redis 缓存工单列表，接口耗时降低一半。"
    "和团队协作时我习惯先写接口文档再开发，code review 会重点关注边界条件。"
)


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


def stream_answer(sid: int, text: str, token: str) -> dict:
    raw = req("POST", f"/api/interview/session/{sid}/answer/stream", {"text": text}, token, raw=True)
    events = [e for e in raw.decode("utf-8").split("\n\n") if e.strip()]
    done = json.loads(events[-1].split("data: ", 1)[1])
    n_tokens = sum(1 for e in events if e.startswith("event: token"))
    return done, n_tokens


def main() -> int:
    name = f"smoke_fin_{random.randint(1000, 9999)}"
    req("POST", "/api/auth/register", {"username": name, "password": "test123456"})
    token = req("POST", "/api/auth/login", {"username": name, "password": "test123456"})["access_token"]

    boundary = "----smoke"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test_resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + PWD.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = urllib.request.Request(
        BASE + "/api/resume/upload",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(r, timeout=60) as resp:
        resume_id = json.loads(resp.read().decode("utf-8"))["id"]

    s = req("POST", "/api/interview/session",
            {"resume_id": resume_id, "interview_mode": "specialized", "interview_type": "project", "question_count": 4}, token)
    sid = s["session_id"]
    print("会话:", sid)

    done, n = stream_answer(sid, "我叫张三，后端开发，做过校园二手交易平台和工单系统。", token)
    print(f"自我介绍 → stage={done['stage']}（流式 {n} token）")

    for i in range(10):
        info = req("GET", f"/api/interview/session/{sid}", token=token)
        if info["stage"] == "ASK_BACK":
            print(f"第 {i + 1} 轮后进入反问环节")
            break
        done, n = stream_answer(sid, ANSWER, token)
        print(f"  第 {i + 2} 轮: stage={done['stage']}（流式 {n} token）")

    done, n = stream_answer(sid, "我想了解团队的技术栈和新人培养机制。", token)
    print(f"反问回答 → stage={done['stage']} finished={done['finished']} report={'有' if done.get('report') else '无'}（流式 {n} token）")
    assert done["finished"] and done.get("report"), "结束事件应带报告"

    history = req("GET", "/api/interview/history", token=token)
    item = next(h for h in history if h["session_id"] == sid)
    print(f"历史: status={item['status']} has_report={item['has_report']} rounds={item['rounds_used']}")
    assert item["has_report"], "历史应标记有报告"
    print("SMOKE_FIN OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
