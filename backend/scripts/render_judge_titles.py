"""把 pooling 题干打成便于逐题标注的 txt。"""
from pathlib import Path
import json

d = json.loads(Path("logs/eval_recall_pools.json").read_text(encoding="utf-8"))
out = Path("logs/judge_titles")
out.mkdir(exist_ok=True)
for q in d["queries"]:
    lines = [q["id"] + " | " + q["query_text"], "INTENT " + q["intent"], ""]
    for i, p in enumerate(q["pool"], 1):
        src = ("T" if p.get("in_tag") else "-") + ("S" if p.get("in_semantic") else "-")
        qid = p["id"][:48]
        lines.append(f"{i:02d} [{src}] {qid}\t{p['question']}")
    path = out / f"{q['id']}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(q["id"], len(q["pool"]), "->", path)
