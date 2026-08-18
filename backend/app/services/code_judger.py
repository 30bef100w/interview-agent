"""对拍判题器：示例用例跑分 + 随机对拍 + 性能测试。

- 示例用例：跑用户代码，逐条对比（即时反馈给"运行"按钮）
- 对拍：随机生成 N 组小规模输入，同时跑用户代码与暴力参考解，输出不一致即 WA
- 性能：一组大数据用例，超时判 TLE
- 对错全由确定性执行决定，LLM 不参与

题目配置在 data/coding_problems.json（参考解 + 生成器按题手工维护）。
"""
import json
import random
from pathlib import Path

from app.services.code_runner import run_code

PROBLEMS_PATH = Path(__file__).resolve().parents[2] / "data" / "coding_problems.json"

MAX_CASES = 100
PERF_TIMEOUT = 5.0


def _load_problems() -> dict:
    if not PROBLEMS_PATH.exists():
        return {}
    return json.loads(PROBLEMS_PATH.read_text("utf-8"))


def get_problem(slug: str) -> dict | None:
    return _load_problems().get(slug)


def _normalize(value, mode: str):
    if mode == "sort":
        return sorted(value)
    if mode == "sort_nested":
        return sorted(sorted(x) if isinstance(x, list) else x for x in value)
    return value


def _to_str(value):
    """输出转字符串对比；set/frozenset 稳定化。"""
    if isinstance(value, (set, frozenset)):
        return json.dumps(sorted(value), ensure_ascii=False, default=str)
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def run_examples(code: str, problem: dict, language: str = "python", coding_mode: str = "function") -> dict:
    """跑示例用例，返回 {results, passed, total}。"""
    out = run_code(
        code,
        problem["examples"],
        method=problem["method"],
        language=language,
        problem_cfg=problem,
        coding_mode=coding_mode,
    )
    if out["error"]:
        return {"verdict": "runtime_error", "message": out["error"], "results": [], "passed": 0, "total": 0}
    passed = 0
    results = []
    total = len(problem["examples"])
    for i, (r, ex) in enumerate(zip(out["results"], problem["examples"])):
        ok = r["ok"] and _to_str(_normalize(r["result"], problem.get("normalize", "none"))) == _to_str(
            _normalize(ex["expected"], problem.get("normalize", "none"))
        )
        passed += ok
        results.append(
            {
                "case": i + 1,
                "ok": ok,
                "args": ex["args"],
                "expected": ex["expected"],
                "actual": r["result"] if r["ok"] else r["error"],
            }
        )
    return {"verdict": "passed" if passed == total else "wrong_answer",
            "passed": passed, "total": total, "results": results}


def run_hidden(code: str, problem: dict, language: str = "python", coding_mode: str = "function") -> dict:
    """随机对拍：生成 N 组输入，用户代码 vs 参考解（参考解始终 Python 函数模式）。"""
    cfg = problem
    gen_code = cfg["generator"]
    ref_code = cfg["reference"]

    # 生成器在子进程里跑（不可信代码不进主进程）
    gen_runner = (
        "import json\n"
        + gen_code
        + "\nimport random\n"
        + f"cases = gen(random.Random(42), {MAX_CASES})\n"
        "print(json.dumps(cases, ensure_ascii=False))\n"
    )
    gen_dir = _run_gen(gen_runner)
    if gen_dir.get("error"):
        return {"verdict": "internal_error", "message": f"用例生成失败: {gen_dir['error']}", "passed": 0, "total": 0}

    cases = gen_dir["cases"]
    if not cases:
        return {"verdict": "internal_error", "message": "生成器没有产出用例", "passed": 0, "total": 0}

    # 手撕模式对拍用例较多时限流，避免每例起进程过慢
    if coding_mode == "scratch" and len(cases) > 20:
        cases = cases[:20]

    user = run_code(
        code, cases, method=cfg["method"], language=language, problem_cfg=cfg, coding_mode=coding_mode
    )
    ref = run_code(
        ref_code, cases, method=cfg["method"], language="python", problem_cfg=cfg, coding_mode="function"
    )
    if user["timed_out"]:
        return {"verdict": "timeout", "message": user["error"], "passed": 0, "total": len(cases)}
    if user["error"]:
        return {"verdict": "runtime_error", "message": user["error"], "passed": 0, "total": len(cases)}
    if ref["error"] or ref["timed_out"]:
        return {"verdict": "internal_error", "message": f"参考解执行失败: {ref['error'] or ref['timed_out']}",
                "passed": 0, "total": len(cases)}

    passed = 0
    first_diff = None
    norm = cfg.get("normalize", "none")
    for i, (u, r) in enumerate(zip(user["results"], ref["results"])):
        if not u["ok"]:
            first_diff = {"case": i + 1, "reason": f"运行错误: {u['error']}", "args": cases[i]["args"]}
            break
        if _to_str(_normalize(u["result"], norm)) != _to_str(_normalize(r["result"], norm)):
            first_diff = {
                "case": i + 1,
                "reason": "输出与参考解不一致",
                "args": cases[i]["args"],
                "expected": r["result"],
                "actual": u["result"],
            }
            break
        passed += 1

    if passed == len(cases):
        return {"verdict": "passed", "passed": passed, "total": len(cases), "message": ""}
    return {"verdict": "wrong_answer", "passed": passed, "total": len(cases),
            "message": f"对拍未通过（{passed}/{len(cases)}），首个不一致见 detail", "detail": first_diff}


def run_performance(code: str, problem: dict, language: str = "python", coding_mode: str = "function") -> dict:
    """大数据用例跑用户代码，超时判 TLE。"""
    perf = problem.get("performance")
    if not perf:
        return {"verdict": "skipped", "message": "本题无性能用例", "elapsed_ms": 0}
    limit = perf.get("limit_s", 3.0)
    out = run_code(
        code,
        [{"args": perf["args"]}],
        method=problem["method"],
        timeout_seconds=limit,
        language=language,
        problem_cfg=problem,
        coding_mode=coding_mode,
    )
    if out["timed_out"]:
        return {"verdict": "timeout", "message": f"性能用例超时（>{limit}s），注意时间复杂度", "elapsed_ms": int(limit * 1000)}
    if out["error"]:
        return {"verdict": "runtime_error", "message": out["error"], "elapsed_ms": out.get("elapsed_ms", 0)}
    return {"verdict": "passed", "message": f"性能用例通过，耗时 {out['elapsed_ms']}ms",
            "elapsed_ms": out["elapsed_ms"]}


def judge(code: str, slug: str, language: str = "python", coding_mode: str = "function") -> dict:
    """完整判题入口：示例 → 对拍 → 性能，返回总判定。"""
    problem = get_problem(slug)
    if not problem:
        return {"verdict": "unavailable", "message": "本题暂未配置判题器，仅支持示例运行", "passed": 0, "total": 0}

    examples = run_examples(code, problem, language=language, coding_mode=coding_mode)
    if examples["verdict"] in ("runtime_error", "wrong_answer"):
        examples["hidden"] = {"verdict": "skipped", "message": "示例未全过，跳过对拍"}
        examples["performance"] = {"verdict": "skipped", "message": "示例未全过，跳过性能测试"}
        examples["final"] = examples["verdict"]
        return examples

    hidden = run_hidden(code, problem, language=language, coding_mode=coding_mode)
    perf = run_performance(code, problem, language=language, coding_mode=coding_mode)
    if hidden["verdict"] != "passed":
        final = hidden["verdict"]
    elif perf["verdict"] in ("timeout", "runtime_error"):
        final = "timeout" if perf["verdict"] == "timeout" else "wrong_answer"
    else:
        final = "accepted"
    return {
        "verdict": examples["verdict"],
        "passed": examples["passed"],
        "total": examples["total"],
        "results": examples["results"],
        "hidden": hidden,
        "performance": perf,
        "final": final,
    }


def _run_gen(source: str) -> dict:
    """在子进程跑用例生成器，返回 {"cases": [...]} 或 {"error": ...}。"""
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        gen_path = Path(tmp) / "gen.py"
        gen_path.write_text(source, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(gen_path)],
                capture_output=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return {"error": "用例生成超时"}
    if proc.returncode != 0:
        return {"error": proc.stderr.decode("utf-8", errors="replace").strip()}
    try:
        cases = json.loads(proc.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"error": "生成器输出无法解析"}
    return {"cases": cases}
