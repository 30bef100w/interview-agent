from app.services.code_judger import get_problem, run_examples

cfg = get_problem("two-sum")
code = r"""
import sys

def twoSum(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return []

def main():
    data = list(map(int, sys.stdin.read().split()))
    n = data[0]
    nums = data[1:1 + n]
    target = data[1 + n]
    print(*twoSum(nums, target))

if __name__ == "__main__":
    main()
"""
print(run_examples(code, cfg, language="python", coding_mode="scratch"))
