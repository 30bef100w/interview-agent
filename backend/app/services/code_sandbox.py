"""One disposable, resource-limited container per judging request; no fallback."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import threading
import uuid

from app.config import settings
from app.services.code_process import run_process

_SLOTS = threading.BoundedSemaphore(2)


def runner_backend() -> str:
    backend = settings.code_runner_backend.strip().lower()
    if backend == "auto":
        return "docker" if settings.is_production else "local"
    # A misconfigured production deployment must never execute on the API host.
    if backend == "local" and settings.is_production:
        return "disabled"
    return backend if backend in {"docker", "local", "disabled"} else "disabled"


def run_isolated(payload: dict, timeout_seconds: float) -> dict:
    def error(msg, timed_out=False, unavailable=False):
        return {"results": [], "error": msg, "timed_out": timed_out, "unavailable": unavailable}
    docker = shutil.which("docker")
    if not docker:
        return error("隔离判题环境不可用，请联系管理员配置代码执行容器", unavailable=True)
    if not _SLOTS.acquire(blocking=False):
        return error("判题服务繁忙，请稍后重试", unavailable=True)
    name = "deepask-judge-" + uuid.uuid4().hex
    # Budget includes compilation and scratch-mode per-case processes.
    timeout_seconds = max(0.1, min(float(timeout_seconds), 10.0))
    cases = len(payload.get("cases", [])) if payload.get("coding_mode") == "scratch" else 1
    wall_timeout = min(180, 45 + max(1, cases) * timeout_seconds)
    command = [
        docker, "run", "--rm", "--pull=never", "--name", name, "--interactive",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--user=10001:10001",
        "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=64",
        "--ulimit=nofile=128:128", "--ulimit=fsize=16777216:16777216",
        "--ulimit=core=0:0", f"--ulimit=cpu={math.ceil(wall_timeout)}:{math.ceil(wall_timeout)}",
        "--tmpfs=/work:rw,exec,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs=/tmp:rw,exec,nosuid,nodev,size=128m,mode=1777",
        settings.code_runner_image,
    ]
    payload = {**payload, "timeout_seconds": timeout_seconds}
    try:
        proc = run_process(command, input=json.dumps(payload).encode(), timeout=wall_timeout,
                           extra_env_keys=("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"))
        if proc.returncode != 0:
            return error("隔离判题执行失败（环境不可用或资源超限）",
                         unavailable=proc.returncode not in {137, 143})
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or not isinstance(result.get("error"), str):
            return error("判题环境返回了无效结果", unavailable=True)
        return result
    except subprocess.TimeoutExpired:
        return error("判题超时，执行容器已终止", True)
    except (OSError, ValueError):
        return error("隔离判题环境不可用或返回了无效结果", unavailable=True)
    finally:
        # Killing the Docker client alone does not stop a container.
        try:
            subprocess.run([docker, "rm", "--force", name], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        _SLOTS.release()
