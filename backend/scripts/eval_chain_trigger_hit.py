"""统计已有 session 中「追问是否落在拷打链 trigger/意图」上的命中率（只读 DB）。"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "face_agent.db"


def norm(s: str) -> str:
    return re.sub(r"\W+", "", (s or "").lower())


def trigger_keywords(trigger: str) -> list[str]:
    t = re.sub(r"候选人|提到|当|如果|是否|在.*时", "", trigger or "")
    parts = re.split(r"[，,、\s/]+", t)
    return [norm(p) for p in parts if len(norm(p)) >= 2]


def match_followup(follow_q: str, chain: dict) -> str:
    fq = norm(follow_q)
    if not fq:
        return ""
    for kw in trigger_keywords(str(chain.get("trigger") or "")):
        if kw in fq:
            return "trigger_kw"
    for field in ("question", "intent"):
        blob = norm(str(chain.get(field) or ""))
        if len(blob) < 4:
            continue
        if blob[:8] in fq or fq[:8] in blob:
            return f"{field}_prefix"
        bg_f = {fq[i : i + 2] for i in range(max(0, len(fq) - 1))}
        bg_b = {blob[i : i + 2] for i in range(max(0, len(blob) - 1))}
        if len(bg_f & bg_b) >= 10:
            return f"{field}_bigram"
    return ""


def extract_project_followups(state: dict) -> list[tuple[str, str]]:
    """返回 (qid, followup_question) 仅项目题且 turn>0 或 is_followup。"""
    plan = state.get("plan") or []
    out: list[tuple[str, str]] = []
    for qid, pq in (state.get("per_question") or {}).items():
        if not qid.startswith("q"):
            continue
        idx = int(qid[1:]) - 1
        if idx < 0 or idx >= len(plan) or plan[idx].get("type") != "project":
            continue
        for i, t in enumerate(pq.get("turns") or []):
            q = str(t.get("question") or "").strip()
            if not q:
                continue
            is_fu = bool(t.get("is_followup")) or i > 0
            if is_fu:
                out.append((qid, q))
    return out


def main() -> int:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, target_role, status, state_json FROM interview_sessions "
        "WHERE state_json IS NOT NULL ORDER BY id DESC"
    ).fetchall()

    per_session: list[dict] = []
    all_rows: list[dict] = []

    for sid, role, status, raw in rows:
        state = json.loads(raw or "{}")
        chains_flat: list[dict] = []
        for pc in state.get("project_chains") or []:
            for ch in pc.get("chains") or []:
                chains_flat.append({**ch, "project": pc.get("project")})
        followups = extract_project_followups(state)
        if not chains_flat or not followups:
            continue
        hits = 0
        for qid, fq in followups:
            reason = ""
            for ch in chains_flat:
                reason = match_followup(fq, ch)
                if reason:
                    break
            row = {
                "session_id": sid,
                "role": role or "",
                "status": status,
                "qid": qid,
                "followup": fq[:80],
                "hit": bool(reason),
                "reason": reason,
            }
            all_rows.append(row)
            if reason:
                hits += 1
        per_session.append(
            {
                "session_id": sid,
                "role": role or "",
                "chains": len(chains_flat),
                "followups": len(followups),
                "hits": hits,
                "rate": round(hits / len(followups) * 100, 1) if followups else 0,
            }
        )

    total_fu = len(all_rows)
    total_hits = sum(1 for r in all_rows if r["hit"])
    overall = round(total_hits / total_fu * 100, 1) if total_fu else 0.0

    print("=" * 60)
    print(f"项目题追问 trigger/意图 语义命中率：{total_hits}/{total_fu} = {overall}%")
    print(f"有效 session 数：{len(per_session)}")
    print("=" * 60)
    for s in per_session:
        print(
            f"  session {s['session_id']} ({s['role'][:10]}): "
            f"{s['hits']}/{s['followups']} = {s['rate']}%  chains={s['chains']}"
        )
    print("-" * 60)
    print("样例（前 15 条追问）：")
    for r in all_rows[:15]:
        mark = "HIT" if r["hit"] else "MISS"
        print(f"  [{mark}] s{r['session_id']} {r['qid']} {r['reason']}: {r['followup']}")

    out = Path(__file__).resolve().parents[1] / "logs" / "eval_chain_trigger_hit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "overall_hit_rate_pct": overall,
                "total_followups": total_fu,
                "total_hits": total_hits,
                "sessions": per_session,
                "samples": all_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
