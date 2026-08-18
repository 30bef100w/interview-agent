"""规划前置冒烟：验证创建时规划完成、自我介绍后第一问快速流式出。"""
import json
import random
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8001"


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
    name = f"smoke_plan_{random.randint(1000, 9999)}"
    req("POST", "/api/auth/register", {"username": name, "password": "test123456"})
    token = req("POST", "/api/auth/login", {"username": name, "password": "test123456"})["access_token"]

    import urllib.request as u

    boundary = "----smoke"
    pdf = open("data/test_resume.pdf", "rb").read()
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test_resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
    r = u.Request(BASE + "/api/resume/upload", data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }, method="POST")
    resume_id = json.loads(u.urlopen(r, timeout=60).read().decode())["id"]

    # 1) 创建会话（规划前置：路由+规划在创建时完成）
    t0 = time.time()
    s = req("POST", "/api/interview/session",
            {"resume_id": resume_id, "interview_mode": "full", "interview_type": "full", "question_count": 8}, token)
    t_create = time.time() - t0
    sid = s["session_id"]
    print(f"创建会话 {t_create:.1f}s（含规划）")

    # 2) 创建后计划已就绪
    info = req("GET", f"/api/interview/session/{sid}", token=token)
    print("计划话题:", info["topics"])
    assert len(info["topics"]) >= 3, "创建后计划应已生成"

    # 3) 自我介绍回答 → 第一问流式，应明显快于旧流程
    t0 = time.time()
    raw = req("POST", f"/api/interview/session/{sid}/answer/stream",
              {"text": "我叫张三，两年后端经验，做过校园二手交易平台。"}, token, raw=True)
    t_first = time.time() - t0
    events = [e for e in raw.decode("utf-8").split("\n\n") if e.strip()]
    n_tokens = sum(1 for e in events if e.startswith("event: token"))
    done = json.loads(events[-1].split("data: ", 1)[1])
    print(f"自我介绍→第一问：总耗时 {t_first:.1f}s，流式 {n_tokens} token")
    print(f"第一问开头: {done['message'][:60]}")
    assert n_tokens > 0, "第一问应流式输出"

    print("SMOKE_PLAN OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
