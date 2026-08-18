"""验证新报告 schema + Word 导出接口。"""
import json
import sqlite3
import sys
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
    with urllib.request.urlopen(r, timeout=60) as resp:
        content = resp.read()
    return content if raw else json.loads(content.decode("utf-8"))


def main() -> int:
    con = sqlite3.connect("data/face_agent.db")
    username, sid = con.execute(
        "SELECT u.username, s.id FROM interview_sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.status='finished' ORDER BY s.id DESC LIMIT 1"
    ).fetchone()
    print("用最新完成的会话验证:", username, "session", sid)
    token = req("POST", "/api/auth/login", {"username": username, "password": "test123456"})["access_token"]

    rep = req("GET", f"/api/interview/session/{sid}/report", token=token)
    r = rep["report"]
    print("报告字段:", sorted(r.keys()))
    pq = r.get("per_question")
    assert pq, "per_question 缺失"
    print(f"逐题详情 {len(pq)} 题")
    for q in pq:
        keys = sorted(q.keys())
        assert "reference_answer" in q and "feedback" in q and "my_answers" in q, f"字段不全: {keys}"
        print(f"  - {q['topic'][:20]} score={q['score']} 作答{len(q['my_answers'])}条 点评{len(q['feedback'])}字 参考{len(q['reference_answer'])}字")
    assert "per_question_calibrated" not in r or not r.get("per_question_calibrated"), "不应输出校准字段"

    raw = req("GET", f"/api/interview/session/{sid}/report/export", token=token, raw=True)
    print(f"Word 导出: {len(raw)} 字节, 头两字节={raw[:2]}")
    assert raw[:2] == b"PK", "docx 应为 zip(PK) 格式"
    with open("data/test_report_export.docx", "wb") as f:
        f.write(raw)
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
