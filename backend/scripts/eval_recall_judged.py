"""按题干判定 pooling 内相关题（不用 roles[]，不扫全库关键词）。

判定标准：读 question 字段，这条面试题是否在考该查询的主题。
泛泛的「Agent 框架有哪些 / SpringBoot 启动」对具体主题查询标不相关。
"""
from __future__ import annotations

import json
from pathlib import Path

POOL = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_pools.json"
QRELS = Path(__file__).resolve().parents[1] / "data" / "eval" / "judged_qrels.json"
OUT = Path(__file__).resolve().parents[1] / "logs" / "eval_recall_judged.json"


def _q(text: str) -> str:
    return (text or "").lower().replace(" ", "")


def _has(q: str, *needles: str) -> bool:
    return any(n.lower().replace(" ", "") in q for n in needles)


def judge(qid: str, question: str) -> bool:
    t = _q(question)
    if not t:
        return False

    if qid == "a01":
        if _has(t, "langgraph"):
            return True
        return _has(t, "状态图") or _has(t, "陷入死循环") or (
            _has(t, "agent状态") and _has(t, "维护")
        )
    if qid == "a02":
        return _has(
            t,
            "function calling",
            "functioncall",
            "tool calling",
            "toolcalling",
            "选错tool",
            "工具调用",
            "工具权限",
            "tool 选择",
            "选工具",
        )
    if qid == "a03":
        return _has(t, "mcp")
    if qid == "a04":
        if _has(t, "缓存击穿", "缓存穿透"):
            return False
        return _has(t, "rag") or _has(t, "切块") or _has(t, "bm25") or _has(t, "混合检索")
    if qid == "a05":
        return _has(t, "多agent", "多智能体", "multi-agent", "multiagent")
    if qid == "a07":
        if _has(t, "react组件", "react hooks", "usestate", "useeffect", "react.memo"):
            return False
        return _has(t, "react") and (
            _has(t, "thought", "action", "observation", "推理", "循环", "模式", "框架", "agent", "cot")
            or t.startswith("什么是react")
            or "react是" in t
        )
    if qid == "a08":
        if _has(t, "sql注入"):
            return False
        return _has(t, "prompt注入", "prompt injection", "jailbreak", "工具越权", "提示注入")
    if qid == "a10":
        return _has(t, "plan-and-execute", "plan and execute", "planner", "规划与执行", "规划执行")
    if qid == "a13":
        return _has(t, "lora", "sft", "微调", "灾难遗忘")
    if qid == "a14":
        return _has(t, "vllm", "kv cache", "kvcache", "pagedattention", "连续批")
    if qid == "a20":
        return _has(t, "langchain") and _has(t, "agent", "tool", "工具", "function")
    if qid == "j01":
        return _has(t, "秒杀", "超卖") or (_has(t, "lua") and _has(t, "库存"))
    if qid == "j02":
        return _has(t, "击穿") or _has(t, "穿透") or _has(t, "雪崩")
    if qid == "j03":
        return _has(t, "rocketmq") or _has(t, "事务消息") or _has(t, "半消息")
    if qid == "j05":
        return _has(t, "hashmap", "concurrenthashmap")
    if qid == "j06":
        return _has(t, "最左") or _has(t, "覆盖索引") or _has(t, "回表")
    if qid == "j08":
        return _has(t, "循环依赖") or _has(t, "三级缓存")
    if qid == "g01":
        return _has(t, "goroutine", "gmp") or (_has(t, "泄漏") and _has(t, "go"))
    if qid == "f01":
        if _has(t, "react循环", "react模式", "thought", "reactor模式"):
            return False
        return _has(t, "useeffect", "hooks", "闭包陷阱", "usestate", "usememo", "react.memo")
    if qid == "n01":
        return _has(t, "transformer", "self-attention", "自注意力", "位置编码")
    return False


def p_at(ranked: list[str], rel: set[str], k: int) -> dict:
    cut = ranked[:k]
    n = len(cut)
    hits = sum(1 for x in cut if x in rel)
    return {
        "k": k,
        "n": n,
        "hits": hits,
        "P": (hits / n) if n else 0.0,
        "Success": 1.0 if hits else 0.0,
    }


def main() -> None:
    data = json.loads(POOL.read_text(encoding="utf-8"))
    qrels: dict[str, list[str]] = {}
    per_query = []
    method_sum = {m: {"P8": 0.0, "P48": 0.0, "h8": 0.0, "h48": 0.0} for m in ("tag", "semantic", "hybrid")}
    n_q = 0
    for q in data["queries"]:
        qid = q["id"]
        rel = []
        for p in q["pool"]:
            if judge(qid, p["question"]):
                rel.append(p["id"])
        rel_set = set(rel)
        qrels[qid] = rel
        row = {"id": qid, "|Rel_pool|": len(rel_set), "methods": {}}
        for name, key in (("tag", "tag_ids"), ("semantic", "semantic_ids"), ("hybrid", "hybrid_ids")):
            ranked = q[key]
            m8 = p_at(ranked, rel_set, 8)
            m48 = p_at(ranked, rel_set, 48)
            row["methods"][name] = {"8": m8, "48": m48}
            method_sum[name]["P8"] += m8["P"]
            method_sum[name]["P48"] += m48["P"]
            method_sum[name]["h8"] += m8["hits"]
            method_sum[name]["h48"] += m48["hits"]
        per_query.append(row)
        n_q += 1
        print(
            f"{qid:4} |Rel|={len(rel_set):3d}  "
            f"tag P@8={row['methods']['tag']['8']['P']:.3f} P@48={row['methods']['tag']['48']['P']:.3f} "
            f"hits48={row['methods']['tag']['48']['hits']}  "
            f"sem P@8={row['methods']['semantic']['8']['P']:.3f} P@48={row['methods']['semantic']['48']['P']:.3f} "
            f"hits48={row['methods']['semantic']['48']['hits']}  "
            f"hyb P@8={row['methods']['hybrid']['8']['P']:.3f} P@48={row['methods']['hybrid']['48']['P']:.3f} "
            f"hits48={row['methods']['hybrid']['48']['hits']}"
        )

    summary = {
        name: {
            "P@8": method_sum[name]["P8"] / n_q,
            "P@48": method_sum[name]["P48"] / n_q,
            "hits@8": method_sum[name]["h8"] / n_q,
            "hits@48": method_sum[name]["h48"] / n_q,
        }
        for name in ("tag", "semantic", "hybrid")
    }
    print("\n宏平均 n=", n_q)
    for name, s in summary.items():
        print(
            f"  {name:9}  P@8={s['P@8']:.3f}  P@48={s['P@48']:.3f}  "
            f"hits@8={s['hits@8']:.2f}  hits@48={s['hits@48']:.2f}"
        )

    QRELS.parent.mkdir(parents=True, exist_ok=True)
    QRELS.write_text(
        json.dumps(
            {
                "protocol": "pool内按题干判定相关，不用岗位标签自动打标",
                "qrels": qrels,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    OUT.write_text(
        json.dumps({"summary": summary, "per_query": per_query, "n": n_q}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("qrels", QRELS)
    print("report", OUT)


if __name__ == "__main__":
    main()
