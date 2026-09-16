"""把题干候选打出来给人读：只输出 question 字段，不跑检索。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.knowledge_retrieval import load_questions  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "logs" / "handmade_candidates"
NEEDLES = {
    "langgraph": ["langgraph"],
    "function_calling": ["function calling", "functioncalling", "工具调用"],
    "mcp": [" mcp", "mcp ", "mcp是", "mcp的", "mcp vs", "mcp/"],
    "react": ["react"],
    "plan_execute": ["plan-and-execute", "plan and execute", "plan-and-solve"],
    "injection": ["prompt injection", "jailbreak", "越狱", "注入"],
    "seckill": ["秒杀", "超卖", "扣库存"],
    "cache_ppp": ["缓存击穿", "缓存穿透", "缓存雪崩", "布隆"],
    "spring": ["循环依赖", "三级缓存"],
    "hashmap": ["hashmap", "concurrenthashmap"],
    "mysql_index": ["最左前缀", "覆盖索引", "回表", "联合索引"],
    "vllm": ["vllm", "pagedattention", "kv cache", "kvcache"],
    "transformer": ["self-attention", "自注意力", "位置编码", "positional"],
}


def main() -> None:
    qs = load_questions()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, needles in NEEDLES.items():
        seen: set[str] = set()
        rows: list[str] = []
        for q in qs:
            t = (q.get("question") or "").strip()
            if not t or t in seen:
                continue
            low = t.lower()
            if not any(n in low for n in needles):
                continue
            seen.add(t)
            rows.append(t)
        path = OUT / f"{name}.txt"
        path.write_text("\n".join(f"{i+1:4d}  {t}" for i, t in enumerate(rows)), encoding="utf-8")
        print(name, len(rows), "->", path)


if __name__ == "__main__":
    main()
