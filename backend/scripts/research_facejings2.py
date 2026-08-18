"""面经仓库二次调研：聚焦 2025-2026 时效的内容。

只调 GitHub API 查看（不下载），检查重点仓库的目录结构与内容时效。
"""
import json
import time
import urllib.parse
import urllib.request

GITHUB_API = "https://api.github.com"

# 用户点名 + 上次候选里更新时间在 2025-2026 的仓库
KEY_REPOS = [
    "shfshanyue/Daily-Question",
    "Leezj9671/Pentest_Interview",
    "WeThinkIn/AIGC-Interview-Book",
    "0voice/Campus_recruitment_interview_questions",
    "datawhalechina/daily-interview",
    "colinlet/PHP-Interview-QA",
    "huihut/interview",
    "0voice/interview_experience",
]

NEW_QUERIES = ["2025面经", "2026面经", "25届面经", "26届面经", "2025秋招", "2026秋招", "2026校招"]


def gh(path: str) -> dict | list | None:
    req = urllib.request.Request(GITHUB_API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "face-agent-research",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  [gh 失败] {path}: {e}")
        return None


def main() -> None:
    # 1) 重点仓库目录结构（前 3 层路径 + 文件名看时效）
    print("========== 重点仓库目录/文件时效检查 ==========")
    for repo in KEY_REPOS:
        print(f"\n--- {repo} ---")
        data = gh(f"/repos/{repo}/git/trees/HEAD?recursive=1")
        if not isinstance(data, dict):
            print("  (无法获取)")
            continue
        paths = [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]
        print(f"  文件总数: {len(paths)}")
        # 找出文件名带年份/时间特征的
        dated = [p for p in paths if any(y in p for y in ("2025", "2026", "25届", "26届", "25秋", "26秋"))]
        print(f"  文件名含 2025/2026 的文件: {len(dated)}")
        for p in dated[:8]:
            print("    -", p[:80])
        # 无年份文件的仓库，看顶层目录判断内容组织
        if not dated:
            dirs = sorted({p.split("/")[0] for p in paths})[:18]
            print("  顶层目录/文件:", "、".join(dirs))
        time.sleep(0.4)

    # 2) 补充搜索 2025/2026 时效的新面经仓库
    print("\n========== 补充搜索 2025/2026 面经 ==========")
    seen: dict[str, dict] = {}
    for q in NEW_QUERIES:
        qs = urllib.parse.quote(q)
        data = gh(f"/search/repositories?q={qs}&sort=updated&order=desc&per_page=8")
        if isinstance(data, dict):
            for it in data.get("items", []):
                full = it["full_name"]
                if full not in seen:
                    seen[full] = {
                        "stars": it["stargazers_count"],
                        "desc": (it.get("description") or "")[:80],
                        "pushed": it["pushed_at"][:10],
                    }
        time.sleep(0.5)
    ranked = sorted(seen.items(), key=lambda kv: kv[1]["stars"], reverse=True)
    for name, info in ranked[:20]:
        print(f"{info['stars']:>6}⭐ {name}  push:{info['pushed']}  {info['desc'][:55]}")


if __name__ == "__main__":
    main()
