import json
import os
import re

TRANSCRIPT = "C:/Users/21236/.claude/projects/d--student-project-work-project-face-agent/14e8fc37-8de8-47af-bdea-4d19ab336d87.jsonl"
README = "C:/Users/21236/AppData/Local/Temp/AI-Meeting/README.md"

urls = set()
with open(TRANSCRIPT, encoding="utf-8") as f:
    for line in f:
        low = line.lower()
        if "ai-meeting" not in low and "ai_meeting" not in low:
            continue
        for m in re.finditer(r"https?://[^\s\"'\\,)]+", line):
            u = m.group(0).rstrip(".")
            if "github" in u.lower():
                urls.add(u)

print("== transcript github urls ==")
for u in sorted(urls):
    print(u)

print("== README urls ==")
if os.path.exists(README):
    txt = open(README, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"https?://[^\s)\"<>']+", txt):
        print(m.group(0).rstrip(".,"))
else:
    print("README not found")
