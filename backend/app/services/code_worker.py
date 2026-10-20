"""Private stdin/stdout protocol used only inside disposable runner containers."""
import json
import sys
import tempfile
from pathlib import Path

from app.services.code_process import run_process
from app.services.code_runner import _run_code_local


def main():
    payload = json.load(sys.stdin)
    if payload.get("operation") == "generator":
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "generator.py"
            source.write_text(payload["source"], encoding="utf-8")
            proc = run_process([sys.executable, "-I", str(source)], cwd=tmp, timeout=10)
        if proc.returncode:
            result = {"error": "用例生成失败"}
        else:
            result = {"error": "", "cases": json.loads(proc.stdout.decode().strip().splitlines()[-1])}
    else:
        result = _run_code_local(**payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"results": [], "error": "判题工作进程执行失败", "timed_out": False}))
