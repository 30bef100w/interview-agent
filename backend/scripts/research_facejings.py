"""GitHub 面经数据源调研：搜索面经类仓库，评估规模/分类/更新情况。

只用 GitHub API（不 clone），输出结构化调研结果。
"""
import json
import time
import urllib.request

GITHUB_API = "https://api.github.com"

QUERIES = [
    "面经",
    "面试经验",
    "interview-experience",
    "校招面经",
    "interview-questions 面经",
    "面经合集",
    "interviews 面经",
    "面经 topic:interview",
]


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


def search(q: str, per_page: int = 15) -> list[dict]:
    import urllib.parse
    qs = urllib.parse.quote(q)
    data = gh(f"/search/repositories?q={qs}&sort=stars&order=desc&per_page={per_page}")
    if isinstance(data, dict):
        return data.get("items", [])
    return []


def tree(repo: str, limit: int = 200) -> list[str]:
    data = gh(f"/repos/{repo}/git/trees/HEAD?recursive=1")
    if not isinstance(data, dict):
        return []
    paths = []
    for item in data.get("tree", []):
        p = item.get("path", "")
        if p.count("/") <= 2:  # 只看顶层两层目录
            paths.append(p)
        if len(paths) >= limit:
            break
    return paths


def main() -> None:
    seen: dict[str, dict] = {}
    for q in QUERIES:
        print(f"== 搜索: {q} ==")
        items = search(q)
        for it in items:
            full = it["full_name"]
            if full in seen:
                continue
            seen[full] = {
                "stars": it["stargazers_count"],
                "desc": (it.get("description") or "")[:100],
                "pushed": it["pushed_at"][:10],
                "license": (it.get("license") or {}).get("spdx_id"),
                "size_kb": it.get("size"),
            }
        time.sleep(1)

    # 按 star 排序输出候选池
    print("\n===== 候选仓库池（按 star 降序）=====")
    ranked = sorted(seen.items(), key=lambda kv: kv[1]["stars"], reverse=True)
    for name, info in ranked:
        print(f"{info['stars']:>6}⭐ {name}  {info['desc'][:60]}  push:{info['pushed']}")

    # top 15 看目录结构（判断是否按企业/岗位分类）
    print("\n===== Top 仓库目录结构 =====")
    for name, info in ranked[:15]:
        print(f"\n--- {name} ({info['stars']}⭐) ---")
        paths = tree(name)
        dirs = sorted({p.split("/")[0] for p in paths})
        print("  顶层目录:", "、".join(dirs[:25]) if dirs else "(空/失败)")
        # 找可能的企业/岗位关键词目录
        keywords = [p for p in paths[:150] if any(k in p.lower() for k in (
            "baidu", "tencent", "alibaba", "bytedance", "meituan", "jingdong", "xiaomi",
            "蚂蚁", "腾讯", "阿里", "字节", "美团", "百度",
            "java", "python", "前端", "后端", "算法",
        ))]
        if keywords:
            print("  命中关键词路径:", "、".join(keywords[:15]))
        time.sleep(0.5)


if __name__ == "__main__":
    main()
