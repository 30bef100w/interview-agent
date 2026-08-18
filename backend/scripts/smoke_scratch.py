from app.services.code_judger import get_problem, run_examples

cfg = get_problem("find-first-and-last-position-of-element-in-sorted-array")
code = r"""
import sys, json

def searchRange(nums, target):
    def find(first):
        l, r, ans = 0, len(nums) - 1, -1
        while l <= r:
            m = (l + r) // 2
            if nums[m] == target:
                ans = m
                if first:
                    r = m - 1
                else:
                    l = m + 1
            elif nums[m] < target:
                l = m + 1
            else:
                r = m - 1
        return ans
    left = find(True)
    if left == -1:
        return [-1, -1]
    return [left, find(False)]

def main():
    args = json.loads(sys.stdin.readline())
    print(json.dumps(searchRange(args[0], args[1])))

if __name__ == "__main__":
    main()
"""
print(run_examples(code, cfg, language="python", coding_mode="scratch"))
