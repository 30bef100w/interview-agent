"""沙箱执行器：在 subprocess 里跑用户提交的代码（Python / Java / C++ / Go）。

- 用例 + 用户代码 → 逐个用例调用并返回结果（异常也作为结果返回）
- 资源限制：超时（调用方控制）；Python 另有模块白名单
- 对错判断不在本模块：只负责执行，对比由判题器做
- 参考解 / 生成器始终走 Python；仅用户代码支持多语言
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.services.code_lang import (
    SUPPORTED_LANGS,
    build_cpp_harness,
    build_go_harness,
    build_java_harness,
)
from app.services.scratch_io import (
    encode_scratch_stdin,
    parse_scratch_stdout,
    scratch_return_type,
)

RUNNER_TEMPLATE = '''\
import json, sys, traceback

sys.path.insert(0, {code_dir!r})
import solution

with open({cases_path!r}, encoding="utf-8") as f:
    cases = json.load(f)

method = {method!r}
out = []
for c in cases:
    try:
        args = c.get("args", [])
        fn = getattr(solution.Solution(), method)
        result = fn(*args)
        # 原地修改题（如 moveZeroes）不返回值：对比第一个可变参数
        if result is None and args:
            result = args[0]
        out.append({{"ok": True, "result": result}})
    except Exception:
        out.append({{"ok": False, "error": traceback.format_exc(limit=3)}})
print(json.dumps(out, ensure_ascii=False, default=str))
'''


def _decode_bytes(data: bytes | None) -> str:
    """解码编译器/进程输出。Windows 上 javac 诊断常是 GBK，不能用 UTF-8 replace。"""
    if not data:
        return ""
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _javac_cmd(javac_bin: str, *src: str) -> list[str]:
    # -encoding 管源文件；-J-D* 尽量让诊断走 UTF-8（JDK 17/18+）
    return [
        javac_bin,
        "-J-Dfile.encoding=UTF-8",
        "-J-Dsun.stderr.encoding=UTF-8",
        "-J-Dstderr.encoding=UTF-8",
        "-encoding",
        "UTF-8",
        *src,
    ]


def _java_cmd(java_bin: str, main: str) -> list[str]:
    return [
        java_bin,
        "-Dfile.encoding=UTF-8",
        "-Dsun.stderr.encoding=UTF-8",
        "-Dstderr.encoding=UTF-8",
        main,
    ]


def _clean_path(p: str | None) -> str | None:
    if not p:
        return None
    return p.strip().strip('"').strip("'")


def _java_tools() -> tuple[str, str] | None:
    """返回 (java, javac) 可执行文件路径；避开 Windows Oracle javapath 坏 shim。"""
    candidates: list[Path] = []
    home = _clean_path(os.environ.get("JAVA_HOME"))
    if home:
        candidates.append(Path(home) / "bin")
    # 常见安装位置（含本机开发环境）
    for p in (
        Path(r"D:\student_app\environment\java\JDK17\bin"),
        Path(r"C:\Program Files\Java\jdk-17\bin"),
        Path(r"C:\Program Files\Eclipse Adoptium\jdk-17\bin"),
    ):
        if p not in candidates:
            candidates.append(p)

    exe = ".exe" if os.name == "nt" else ""
    for bindir in candidates:
        java, javac = bindir / f"java{exe}", bindir / f"javac{exe}"
        if java.exists() and javac.exists():
            return str(java), str(javac)

    # 最后才用 PATH；并用 -version 探测是否能跑（shim 常直接崩）
    java_w, javac_w = shutil.which("java"), shutil.which("javac")
    if java_w and javac_w:
        try:
            probe = subprocess.run([javac_w, "-version"], capture_output=True, timeout=10)
            # Windows 崩溃码 0xC0000409 = 3221226505
            if probe.returncode == 0 or probe.stderr or probe.stdout:
                if probe.returncode not in (3221226505, -1073740791):
                    return java_w, javac_w
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def available_languages() -> list[str]:
    """当前机器可实际编译/运行的语言（python 始终可用）。"""
    langs = ["python"]
    if _java_tools():
        langs.append("java")
    if shutil.which("g++") or shutil.which("clang++"):
        langs.append("cpp")
    if shutil.which("go"):
        langs.append("go")
    return langs


def run_code(
    code: str,
    cases: list[dict],
    method: str = "solve",
    timeout_seconds: float = 5.0,
    language: str = "python",
    problem_cfg: dict | None = None,
    coding_mode: str = "function",
) -> dict:
    """在沙箱里跑用户代码，返回 {results: [...], timed_out: bool, error: str}。

    coding_mode:
      - function：调用 Solution.method / 等价 harness（力扣函数模式）
      - scratch：编译运行完整程序，stdin/stdout 对拍（手撕模式）
    """
    lang = (language or "python").lower()
    mode = (coding_mode or "function").lower()
    if lang not in SUPPORTED_LANGS:
        return {"results": [], "timed_out": False, "error": f"不支持的语言: {language}"}
    if mode == "scratch":
        return _run_scratch(code, cases, lang, timeout_seconds, problem_cfg)
    if lang == "python":
        return _run_python(code, cases, method, timeout_seconds)
    if problem_cfg is None:
        return {"results": [], "timed_out": False, "error": "多语言执行缺少题目配置"}
    if lang == "java":
        return _run_java(code, cases, problem_cfg, timeout_seconds)
    if lang == "cpp":
        return _run_cpp(code, cases, problem_cfg, timeout_seconds)
    if lang == "go":
        return _run_go(code, cases, problem_cfg, timeout_seconds)
    return {"results": [], "timed_out": False, "error": f"未实现: {lang}"}


def _run_scratch(
    code: str,
    cases: list[dict],
    language: str,
    timeout_seconds: float,
    problem_cfg: dict | None = None,
) -> dict:
    """手撕模式：每组用例单独启动进程，stdin 喂 ACM 数字，解析 stdout（数字或 JSON）。"""
    start = time.monotonic()
    ret_type = scratch_return_type(problem_cfg)
    results: list[dict] = []
    for c in cases:
        stdin = encode_scratch_stdin(c.get("args") or [])
        one = _exec_program(code, language, stdin, timeout_seconds)
        if one.get("timed_out"):
            return {
                "results": results,
                "timed_out": True,
                "error": one.get("error") or "运行超时",
                "elapsed_ms": int((time.monotonic() - start) * 1000),
            }
        if one.get("error") and not (one.get("stdout") or "").strip():
            err = one["error"]
            if err.startswith("编译错误"):
                return {
                    "results": [],
                    "timed_out": False,
                    "error": err,
                    "elapsed_ms": int((time.monotonic() - start) * 1000),
                }
            results.append({"ok": False, "error": err})
            continue
        stdout = (one.get("stdout") or "").strip()
        if not stdout:
            results.append({"ok": False, "error": one.get("error") or "标准输出为空"})
            continue
        try:
            results.append({"ok": True, "result": parse_scratch_stdout(stdout, ret_type)})
        except (ValueError, json.JSONDecodeError) as e:
            results.append(
                {
                    "ok": False,
                    "error": f"无法解析输出（请打印空格分隔的数字，例如 0 1）：\n{stdout[:500]}\n{e}",
                }
            )
    return {
        "results": results,
        "timed_out": False,
        "error": "",
        "elapsed_ms": int((time.monotonic() - start) * 1000),
    }


def _exec_program(code: str, language: str, stdin_text: str, timeout_seconds: float) -> dict:
    """编译并运行完整程序，返回 {stdout, stderr, error, timed_out}。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        try:
            if language == "python":
                path = tmp / "main.py"
                path.write_text(code, encoding="utf-8")
                (tmp / "guard.py").write_text(GUARD_SOURCE.replace("solution.py", "main.py"), encoding="utf-8")
                env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        f"import sys; sys.path.insert(0, {str(tmp)!r});"
                        "import guard; guard.check();"
                        f"import runpy; runpy.run_path({str(path)!r}, run_name='__main__')",
                    ],
                    input=stdin_text.encode("utf-8"),
                    capture_output=True,
                    env=env,
                    timeout=timeout_seconds,
                )
            elif language == "java":
                tools = _java_tools()
                if not tools:
                    return {"stdout": "", "error": "服务器未安装可用 JDK", "timed_out": False}
                java_bin, javac_bin = tools
                (tmp / "Main.java").write_text(code, encoding="utf-8")
                compile_proc = subprocess.run(
                    _javac_cmd(javac_bin, "Main.java"),
                    cwd=tmp,
                    capture_output=True,
                    timeout=30,
                )
                if compile_proc.returncode != 0:
                    err = (_decode_bytes(compile_proc.stderr) or _decode_bytes(compile_proc.stdout)).strip()
                    return {"stdout": "", "error": f"编译错误:\n{err}", "timed_out": False}
                proc = subprocess.run(
                    _java_cmd(java_bin, "Main"),
                    cwd=tmp,
                    input=stdin_text.encode("utf-8"),
                    capture_output=True,
                    timeout=timeout_seconds,
                )
            elif language == "cpp":
                cxx = _cxx_compiler()
                if not cxx:
                    return {
                        "stdout": "",
                        "error": "服务器未安装 C++ 编译器（需要 g++ 或 clang++）",
                        "timed_out": False,
                    }
                src = tmp / "main.cpp"
                src.write_text(code, encoding="utf-8")
                exe = tmp / ("main.exe" if os.name == "nt" else "main")
                compile_proc = subprocess.run(
                    [cxx, "-O2", "-std=c++17", "-o", str(exe), str(src)],
                    capture_output=True,
                    timeout=30,
                )
                if compile_proc.returncode != 0:
                    err = _decode_bytes(compile_proc.stderr or compile_proc.stdout).strip()
                    return {"stdout": "", "error": f"编译错误:\n{err}", "timed_out": False}
                proc = subprocess.run(
                    [str(exe)],
                    input=stdin_text.encode("utf-8"),
                    capture_output=True,
                    timeout=timeout_seconds,
                )
            elif language == "go":
                if not shutil.which("go"):
                    return {"stdout": "", "error": "服务器未安装 Go", "timed_out": False}
                (tmp / "main.go").write_text(code, encoding="utf-8")
                env = dict(os.environ, GO111MODULE="off")
                proc = subprocess.run(
                    ["go", "run", "main.go"],
                    cwd=tmp,
                    input=stdin_text.encode("utf-8"),
                    capture_output=True,
                    timeout=max(timeout_seconds + 45, 60),
                    env=env,
                )
            else:
                return {"stdout": "", "error": f"未实现: {language}", "timed_out": False}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "error": f"运行超时（>{timeout_seconds:.1f}s）", "timed_out": True}

    stdout = _decode_bytes(proc.stdout)
    stderr = _decode_bytes(proc.stderr)
    if proc.returncode != 0 and not stdout.strip():
        return {"stdout": stdout, "error": stderr.strip() or f"退出码 {proc.returncode}", "timed_out": False}
    return {"stdout": stdout, "error": stderr.strip(), "timed_out": False}


def _run_python(code: str, cases: list[dict], method: str, timeout_seconds: float) -> dict:
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "solution.py").write_text(code, encoding="utf-8")
        cases_path = tmp / "cases.json"
        cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        runner = tmp / "runner.py"
        runner.write_text(
            RUNNER_TEMPLATE.format(code_dir=str(tmp), cases_path=str(cases_path), method=method),
            encoding="utf-8",
        )
        (tmp / "guard.py").write_text(GUARD_SOURCE, encoding="utf-8")

        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            proc = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    f"import sys; sys.path.insert(0, {str(tmp)!r});"
                    "import guard; guard.check();"
                    f"import runpy; runpy.run_path({str(runner)!r}, run_name='__main__')",
                ],
                capture_output=True,
                env=env,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {"results": [], "timed_out": True, "error": f"运行超时（>{timeout_seconds:.1f}s）"}

    return _parse_proc(proc, start)


def _run_java(code: str, cases: list[dict], cfg: dict, timeout_seconds: float) -> dict:
    tools = _java_tools()
    if not tools:
        return {"results": [], "timed_out": False, "error": "服务器未安装可用 JDK（需要 JAVA_HOME 或 javac/java）"}
    java_bin, javac_bin = tools
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "Solution.java").write_text(code, encoding="utf-8")
        (tmp / "Harness.java").write_text(build_java_harness(cfg, cases), encoding="utf-8")
        try:
            compile_proc = subprocess.run(
                _javac_cmd(javac_bin, "Solution.java", "Harness.java"),
                cwd=tmp,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {"results": [], "timed_out": True, "error": "编译超时"}
        if compile_proc.returncode != 0:
            err = (_decode_bytes(compile_proc.stderr) or _decode_bytes(compile_proc.stdout)).strip()
            return {"results": [], "timed_out": False, "error": f"编译错误:\n{err or f'javac exit {compile_proc.returncode}'}"}
        try:
            proc = subprocess.run(
                _java_cmd(java_bin, "Harness"),
                cwd=tmp,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {"results": [], "timed_out": True, "error": f"运行超时（>{timeout_seconds:.1f}s）"}
    return _parse_proc(proc, start)


def _cxx_compiler() -> str | None:
    return shutil.which("g++") or shutil.which("clang++")


def _run_cpp(code: str, cases: list[dict], cfg: dict, timeout_seconds: float) -> dict:
    cxx = _cxx_compiler()
    if not cxx:
        return {
            "results": [],
            "timed_out": False,
            "error": "服务器未安装 C++ 编译器（需要 g++ 或 clang++）。请改用 Python / Java / Go，或在服务器安装 MinGW/g++。",
        }
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "main.cpp"
        src.write_text(build_cpp_harness(cfg, cases, code), encoding="utf-8")
        exe = tmp / ("main.exe" if os.name == "nt" else "main")
        try:
            compile_proc = subprocess.run(
                [cxx, "-O2", "-std=c++17", "-o", str(exe), str(src)],
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {"results": [], "timed_out": True, "error": "编译超时"}
        if compile_proc.returncode != 0:
            err = _decode_bytes(compile_proc.stderr or compile_proc.stdout).strip()
            return {"results": [], "timed_out": False, "error": f"编译错误:\n{err}"}
        try:
            proc = subprocess.run([str(exe)], capture_output=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return {"results": [], "timed_out": True, "error": f"运行超时（>{timeout_seconds:.1f}s）"}
    return _parse_proc(proc, start)


def _run_go(code: str, cases: list[dict], cfg: dict, timeout_seconds: float) -> dict:
    if not shutil.which("go"):
        return {"results": [], "timed_out": False, "error": "服务器未安装 Go"}
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "main.go").write_text(build_go_harness(cfg, cases, code), encoding="utf-8")
        env = dict(os.environ, GO111MODULE="off")
        try:
            proc = subprocess.run(
                ["go", "run", "main.go"],
                cwd=tmp,
                capture_output=True,
                timeout=max(timeout_seconds + 45, 60),  # go run 含编译，冷启动较慢
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"results": [], "timed_out": True, "error": f"运行超时（>{timeout_seconds:.1f}s）"}
    return _parse_proc(proc, start)


def _parse_proc(proc: subprocess.CompletedProcess, start: float) -> dict:
    out = _decode_bytes(proc.stdout).strip()
    err = _decode_bytes(proc.stderr).strip()
    if proc.returncode != 0:
        return {
            "results": [],
            "timed_out": False,
            "error": err or out or "执行出错（退出码非 0）",
        }
    try:
        results = json.loads(out.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"results": [], "timed_out": False, "error": "无法解析执行输出:\n" + (out or err)}
    # Java harness 把 result 嵌在 JSON 字符串里时已是对象；统一保证结构
    normalized = []
    for r in results:
        if not isinstance(r, dict):
            normalized.append({"ok": False, "error": "bad result item"})
            continue
        normalized.append(r)
    return {
        "results": normalized,
        "timed_out": False,
        "error": "",
        "elapsed_ms": int((time.monotonic() - start) * 1000),
    }


GUARD_SOURCE = """\
import builtins
import re
from pathlib import Path

ALLOWED_MODULES = {
    "math", "collections", "heapq", "itertools", "functools", "bisect", "typing",
    "json", "re", "string", "copy", "random", "sys", "time", "decimal",
    "fractions", "statistics", "abc", "dataclasses", "enum", "struct", "uuid",
    "operator", "array",
}

BANNED_CALLS = (
    "eval(", "exec(", "compile(", "__import__(", "open(", "input(",
    "globals()", "locals()", "getattr(builtins", "pickle.loads",
)

def check():
    src = (Path(__file__).resolve().parent / "solution.py").read_text(encoding="utf-8")
    stripped = re.sub(r"#[^\\n]*", "", src)  # 去注释，减少误报
    for hint in BANNED_CALLS:
        if hint in stripped:
            raise SystemExit(f"[危险调用被拦截] {hint}")
    for m in re.finditer(r"^\\s*(?:import|from)\\s+([a-zA-Z_][a-zA-Z0-9_.]*)", stripped, re.M):
        top = m.group(1).split(".")[0]
        if top not in ALLOWED_MODULES:
            raise SystemExit(f"[模块被拦截] import {top}")
"""
