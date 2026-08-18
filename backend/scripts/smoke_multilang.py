"""快速验证 Java / Go 多语言示例判题。"""
from app.services.code_judger import get_problem, run_examples
from app.services.code_runner import _run_java, _run_go, available_languages

SLUG = "find-first-and-last-position-of-element-in-sorted-array"

JAVA = """
class Solution {
    public int[] searchRange(int[] nums, int target) {
        int left = find(nums, target, true);
        if (left == -1) return new int[]{-1, -1};
        int right = find(nums, target, false);
        return new int[]{left, right};
    }
    int find(int[] nums, int target, boolean first) {
        int l = 0, r = nums.length - 1, ans = -1;
        while (l <= r) {
            int m = (l + r) / 2;
            if (nums[m] == target) { ans = m; if (first) r = m - 1; else l = m + 1; }
            else if (nums[m] < target) l = m + 1;
            else r = m - 1;
        }
        return ans;
    }
}
"""

GO = """
func searchRange(nums []int, target int) []int {
    left := find(nums, target, true)
    if left == -1 { return []int{-1, -1} }
    right := find(nums, target, false)
    return []int{left, right}
}
func find(nums []int, target int, first bool) int {
    l, r, ans := 0, len(nums)-1, -1
    for l <= r {
        m := (l + r) / 2
        if nums[m] == target {
            ans = m
            if first { r = m - 1 } else { l = m + 1 }
        } else if nums[m] < target { l = m + 1 } else { r = m - 1 }
    }
    return ans
}
"""


def main() -> None:
    print("available:", available_languages())
    cfg = get_problem(SLUG)
    assert cfg
    cases = cfg["examples"]
    print("JAVA raw:", _run_java(JAVA, cases, cfg, 10))
    print("GO raw:", _run_go(GO, cases, cfg, 60))
    print("JAVA judge:", run_examples(JAVA, cfg, language="java"))
    print("GO judge:", run_examples(GO, cfg, language="go"))


if __name__ == "__main__":
    main()
