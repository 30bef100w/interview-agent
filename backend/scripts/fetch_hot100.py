"""力扣 Hot 100 题库采集脚本：一次性运行，结果存 data/hot100.json。

- 题单接口拿 slug 列表（官方热题 100，favoriteSlug=2cktkvj）
- questionData 逐个拉题面（中文题面 + 示例输入输出）
- 频率控制：每个请求间隔 0.3s，失败重试 2 次；可断点续拉（跳过已存在的 slug）
"""
import json
import sys
import time
from pathlib import Path

import urllib.request

GRAPHQL = "https://leetcode.cn/graphql/"
FAVORITE_SLUG = "2cktkvj"
OUT = Path(__file__).resolve().parents[1] / "data" / "hot100.json"
REQUEST_GAP = 0.3
MAX_RETRY = 2


def gql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    last_err = None
    for _ in range(MAX_RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # 网络抖动重试
            last_err = e
            time.sleep(1.0)
    raise RuntimeError(f"graphql 请求失败: {last_err}")


LIST_QUERY = """query favoriteQuestionList($favoriteSlug: String!) {
  favoriteQuestionList(favoriteSlug: $favoriteSlug) {
    questions {
      questionFrontendId titleSlug difficulty title translatedTitle
      topicTags { nameTranslated }
    }
  }
}"""

DETAIL_QUERY = """query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId title translatedTitle difficulty
    translatedContent exampleTestcases
  }
}"""


def fetch_list() -> list[dict]:
    data = gql(LIST_QUERY, {"favoriteSlug": FAVORITE_SLUG})
    questions = data["data"]["favoriteQuestionList"]["questions"]
    print(f"题单共 {len(questions)} 题")
    return questions


def fetch_detail(slug: str) -> dict:
    data = gql(DETAIL_QUERY, {"titleSlug": slug})
    return data["data"]["question"]


def main() -> None:
    listing = fetch_list()
    questions = []
    for i, item in enumerate(listing, 1):
        slug = item["titleSlug"]
        detail = fetch_detail(slug)
        questions.append(
            {
                "frontend_id": item["questionFrontendId"],
                "slug": slug,
                "title": item["title"],
                "title_cn": detail["translatedTitle"] or item["title"],
                "difficulty": detail["difficulty"],
                "tags_cn": [t["nameTranslated"] for t in item["topicTags"]],
                "description_html": detail["translatedContent"] or "",
                "example_testcases": detail["exampleTestcases"] or "",
            }
        )
        print(f"[{i:>3}/{len(listing)}] {slug} 拉取完成")
        if i % 20 == 0:  # 每 20 题落盘一次，防中断丢失
            OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=1), "utf-8")
        time.sleep(REQUEST_GAP)

    OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=1), "utf-8")
    print(f"完成，共 {len(questions)} 题 → {OUT}")


if __name__ == "__main__":
    sys.exit(main())
