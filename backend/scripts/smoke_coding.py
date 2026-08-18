"""算法环节 API 冒烟：走完整 HTTP 链路验证 coding 题插入与提交判题。

真实 DeepSeek 调用（约 10 次），验证：
1. full 会话计划里自动插入算法题
2. 走到算法题后 code/run 示例自测
3. code/submit 完整判题 + AI 评审 + 引擎推进
"""
import json
import random
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8001"
PWD = Path(__file__).resolve().parents[1] / "data" / "test_resume.pdf"


def req(method: str, path: str, body=None, token: str | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[HTTP {e.code}] {e.read().decode('utf-8')[:300]}")
        raise


def main() -> int:
    name = f"smoke_coding_{random.randint(1000, 9999)}"
    req("POST", "/api/auth/register", {"username": name, "password": "test123456"})
    token = req("POST", "/api/auth/login", {"username": name, "password": "test123456"})["access_token"]

    # 上传简历
    boundary = "----smoketest"
    with open(PWD, "rb") as f:
        pdf = f.read()
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test_resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + pdf + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = urllib.request.Request(
        BASE + "/api/resume/upload",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(r, timeout=60) as resp:
        resume = json.loads(resp.read().decode("utf-8"))
    resume_id = resume["id"]
    print("简历上传:", resume_id)

    # 创建 full 会话
    s = req("POST", "/api/interview/session",
            {"resume_id": resume_id, "interview_mode": "full", "interview_type": "full", "question_count": 8}, token)
    sid = s["session_id"]
    print("会话创建:", sid, "|", s["message"][:40])
    info0 = req("GET", f"/api/interview/session/{sid}", None, token)
    print("计划话题:", info0.get("topics"))

    # 自我介绍
    req("POST", f"/api/interview/session/{sid}/answer", {"text": "我叫张三，有两年后端开发经验，做过工单系统。"}, token)

    # 答主问题直到遇到算法题（回答要充实，避免被追问消耗轮次）
    coding = None
    for i in range(12):
        info = req("GET", f"/api/interview/session/{sid}", None, token)
        if info["current_coding"]:
            coding = info["current_coding"]
            print(f"第 {i + 2} 轮进入算法环节:", coding["title"], coding["difficulty"])
            break
        ans = req("POST", f"/api/interview/session/{sid}/answer", {
            "text": "我的项目是校园二手交易平台，我用 Spring Boot 做后端，MySQL 存数据，Redis 缓存热点商品。"
                    "技术难点是库存超卖问题，我通过 Redis 预扣库存加 Lua 脚本保证原子性解决了，压测 QPS 从 500 提升到 3000。"
                    "数据库层面我做了索引优化，慢查询从 200ms 降到 20ms。"
        }, token)
        print(f"  第 {i + 2} 轮已答:", ans["message"][:36])
    if coding is None:
        print("!! 未遇到算法题")
        return 1

    # 运行示例（用正确解）
    optimal = {
        "two-sum": "class Solution:\n    def twoSum(self, nums, target):\n        m = {}\n        for i, v in enumerate(nums):\n            if target - v in m:\n                return [m[target - v], i]\n            m[v] = i\n        return []",
        "maximum-subarray": "class Solution:\n    def maxSubArray(self, nums):\n        best = cur = nums[0]\n        for v in nums[1:]:\n            cur = max(v, cur + v)\n            best = max(best, cur)\n        return best",
        "best-time-to-buy-and-sell-stock": "class Solution:\n    def maxProfit(self, prices):\n        best, low = 0, prices[0]\n        for p in prices[1:]:\n            best = max(best, p - low)\n            low = min(low, p)\n        return best",
        "subarray-sum-equals-k": "class Solution:\n    def subarraySum(self, nums, k):\n        from collections import defaultdict\n        d = defaultdict(int); d[0] = 1\n        s = cnt = 0\n        for v in nums:\n            s += v\n            cnt += d[s - k]\n            d[s] += 1\n        return cnt",
        "product-of-array-except-self": "class Solution:\n    def productExceptSelf(self, nums):\n        n = len(nums)\n        res = [1] * n\n        for i in range(1, n): res[i] = res[i-1] * nums[i-1]\n        r = 1\n        for i in range(n-1, -1, -1):\n            res[i] *= r; r *= nums[i]\n        return res",
        "merge-intervals": "class Solution:\n    def merge(self, intervals):\n        if not intervals: return []\n        intervals.sort()\n        res = [list(intervals[0])]\n        for l, r in intervals[1:]:\n            if l <= res[-1][1]: res[-1][1] = max(res[-1][1], r)\n            else: res.append([l, r])\n        return res",
        "move-zeroes": "class Solution:\n    def moveZeroes(self, nums):\n        j = 0\n        for i, v in enumerate(nums):\n            if v != 0:\n                nums[j] = v; j += 1\n        for i in range(j, len(nums)): nums[i] = 0",
        "container-with-most-water": "class Solution:\n    def maxArea(self, height):\n        i, j = 0, len(height)-1\n        best = 0\n        while i < j:\n            best = max(best, min(height[i], height[j]) * (j - i))\n            if height[i] < height[j]: i += 1\n            else: j -= 1\n        return best",
        "3sum": "class Solution:\n    def threeSum(self, nums):\n        nums.sort()\n        res = []\n        n = len(nums)\n        for i in range(n):\n            if i > 0 and nums[i] == nums[i-1]: continue\n            l, r = i + 1, n - 1\n            while l < r:\n                s = nums[i] + nums[l] + nums[r]\n                if s == 0:\n                    res.append([nums[i], nums[l], nums[r]])\n                    while l < r and nums[l] == nums[l+1]: l += 1\n                    while l < r and nums[r] == nums[r-1]: r -= 1\n                    l += 1; r -= 1\n                elif s < 0: l += 1\n                else: r -= 1\n        return res",
        "trapping-rain-water": "class Solution:\n    def trap(self, height):\n        n = len(height)\n        left = [0]*n; right = [0]*n\n        m = 0\n        for i in range(n): m = max(m, height[i]); left[i] = m\n        m = 0\n        for i in range(n-1, -1, -1): m = max(m, height[i]); right[i] = m\n        return sum(min(left[i], right[i]) - height[i] for i in range(n))",
        "sort-colors": "class Solution:\n    def sortColors(self, nums):\n        cnt = [0, 0, 0]\n        for v in nums: cnt[v] += 1\n        i = 0\n        for color, c in enumerate(cnt):\n            for _ in range(c):\n                nums[i] = color; i += 1",
        "longest-substring-without-repeating-characters": "class Solution:\n    def lengthOfLongestSubstring(self, s):\n        seen = set()\n        l = best = 0\n        for r, ch in enumerate(s):\n            while ch in seen:\n                seen.remove(s[l]); l += 1\n            seen.add(ch)\n            best = max(best, r - l + 1)\n        return best",
        "find-all-anagrams-in-a-string": "class Solution:\n    def findAnagrams(self, s, p):\n        from collections import Counter\n        res = []\n        n, m = len(s), len(p)\n        if n < m: return []\n        pc = Counter(p)\n        wc = Counter(s[:m])\n        if wc == pc: res.append(0)\n        for i in range(1, n - m + 1):\n            wc[s[i-1]] -= 1\n            if wc[s[i-1]] == 0: del wc[s[i-1]]\n            wc[s[i+m-1]] += 1\n            if wc == pc: res.append(i)\n        return res",
        "valid-parentheses": "class Solution:\n    def isValid(self, s):\n        stack = []\n        pairs = {')': '(', ']': '[', '}': '{'}\n        for ch in s:\n            if ch in pairs:\n                if not stack or stack[-1] != pairs[ch]: return False\n                stack.pop()\n            else: stack.append(ch)\n        return not stack",
        "search-in-rotated-sorted-array": "class Solution:\n    def search(self, nums, target):\n        return nums.index(target) if target in nums else -1",
        "find-first-and-last-position-of-element-in-sorted-array": "class Solution:\n    def searchRange(self, nums, target):\n        idx = [i for i, v in enumerate(nums) if v == target]\n        return [idx[0], idx[-1]] if idx else [-1, -1]",
    }
    code = optimal.get(coding["slug"], coding["template"])

    run = req("POST", f"/api/interview/session/{sid}/code/run", {"slug": coding["slug"], "code": code}, token)
    print(f"运行示例: verdict={run['verdict']} {run['passed']}/{run['total']}")

    sub = req("POST", f"/api/interview/session/{sid}/code/submit", {"slug": coding["slug"], "code": code}, token)
    j = sub["judge"]
    print(f"提交判题: final={j['final']} 示例 {j['passed']}/{j['total']} 对拍 {j['hidden'].get('passed')}/{j['hidden'].get('total')} 性能 {j['performance'].get('verdict')}")
    rv = sub["review"]
    print(f"AI 评审: score={rv['score']} 复杂度={str(rv.get('complexity'))[:50]}")
    print(f"推进消息: {sub['message'][:60]} stage={sub['stage']}")

    info = req("GET", f"/api/interview/session/{sid}", None, token)
    print(f"推进后 stage={info['stage']} 轮次 {info['rounds_used']}/{info['total_rounds']} history={len(info['history'])}")
    print(f"下一题话题: {info['topics'][1] if len(info['topics']) > 1 else info['topics'][0] if info['topics'] else '-'}")
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
