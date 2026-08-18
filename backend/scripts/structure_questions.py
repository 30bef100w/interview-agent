"""LLM 精结构化：物理块 → 一题一条（{question, answer}），继承原标签，不加其他字段。

输入：data/knowledge_base/knowledge.jsonl 中 type 为 question_bank/facejing 的文档
输出：data/knowledge_base/structured.jsonl（一题一条）+ structured_meta.json
"""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.llm.client import OpenAiLlm  # noqa: E402

KB = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"
# 用法：python structure_questions.py [types=question_bank,facejing|knowledge] [out=structured.jsonl]
DEFAULT_TYPES = ("question_bank", "facejing")
MAX_WORKERS = 6

SYSTEM = """你是面经整理助手。把输入的面试内容原文切分成"一题一条"。

规则：
1. 每道独立的面试题输出一条：{"question": "题目原文", "answer": "该题的答案/回答原文"}
2. answer 保留原文中对应的答案内容（最多 600 字，无答案时为空字符串）
3. 只做切分，不总结、不补充、不改写；找不到明确题目的内容不输出
4. 输出 JSON 数组，不要任何其他文字"""


def split_doc(doc_text: str) -> list[dict]:
    llm = OpenAiLlm()
    try:
        result = llm.chat_json(SYSTEM, doc_text, max_retries=1)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(result, list):
        return result
    return result.get("items") or result.get("questions") or []


def process_doc(key: str, blocks: list[dict]) -> tuple[str, list[dict]]:
    doc_text = "\n\n".join(b["content"] for b in blocks)
    if len(doc_text) > 10000:
        doc_text = doc_text[:10000]
    if len(doc_text) < 120:
        return key, []
    base = blocks[0]
    items = split_doc(doc_text)
    entries = []
    for it in items:
        q = str(it.get("question", "")).strip()
        if not q:
            continue
        entries.append({
            "question": q[:500],
            "answer": str(it.get("answer", "")).strip()[:600],
            "category": base.get("category"),
            "company": base.get("company"),
            "roles": base.get("roles"),
            "business_scene": base.get("business_scene"),
            "tech_scene": base.get("tech_scene"),
            "era": base.get("era"),
            "source_repo": base.get("source_repo"),
            "source_file": base.get("source_file"),
        })
    return key, entries


def main() -> None:
    types_arg = sys.argv[1] if len(sys.argv) > 1 else "question_bank,facejing"
    out_name = sys.argv[2] if len(sys.argv) > 2 else "structured.jsonl"
    target_types = tuple(t.strip() for t in types_arg.split(",") if t.strip())

    lines = open(KB / "knowledge.jsonl", encoding="utf-8").readlines()
    docs: dict[str, list[dict]] = {}
    for l in lines:
        e = json.loads(l)
        if e.get("type") not in target_types:
            continue
        docs.setdefault(f"{e['source_repo']}|{e['source_file']}", []).append(e)

    print(f"待处理文档: {len(docs)} 篇", flush=True)
    stats = {"docs": 0, "items": 0, "empty": 0}
    lock = threading.Lock()
    total = len(docs)
    done = 0

    def collect(key, entries):
        nonlocal done
        with lock:
            done += 1
            if entries:
                stats["docs"] += 1
                stats["items"] += len(entries)
            else:
                stats["empty"] += 1
            if done % 50 == 0:
                print(f"  进度 {done}/{total}，产出 {stats['items']} 条", flush=True)

    out_fp = KB / out_name
    with open(out_fp, "w", encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(process_doc, key, blocks): (key, blocks)
                for key, blocks in docs.items()
            }
            for fut in futures:
                key, entries = fut.result()
                for e in entries:
                    out.write(json.dumps(e, ensure_ascii=False) + "\n")
                collect(key, entries)
            out.flush()

    stats["docs_total"] = total
    (KB / "structured_meta.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
