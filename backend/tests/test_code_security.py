import json
import os
import subprocess
import sys
import time

import pytest

from app.services import code_sandbox
from app.services.code_judger import _run_gen
from app.services.code_process import MAX_OUTPUT_BYTES, run_process
from app.services.code_runner import run_code


def test_production_cannot_select_local_runner(monkeypatch):
    monkeypatch.setattr(code_sandbox.settings, "app_env", "production")
    monkeypatch.setattr(code_sandbox.settings, "code_runner_backend", "local")
    assert code_sandbox.runner_backend() == "disabled"
    assert run_code("raise Exception('must not run')", [])["error"]
    assert _run_gen("raise Exception('must not run')")["error"]


def test_missing_docker_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(code_sandbox.settings, "app_env", "production")
    monkeypatch.setattr(code_sandbox.settings, "code_runner_backend", "auto")
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda _: None)
    result = run_code("raise Exception('must not run')", [])
    assert "隔离判题环境不可用" in result["error"]
    assert result["unavailable"]


def test_children_do_not_inherit_application_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-never-forward")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-never-forward")
    monkeypatch.setenv("DATABASE_URL", "test-db-never-forward")
    proc = run_process([sys.executable, "-I", "-c",
                        "import os,json; print(json.dumps(dict(os.environ)))"], cwd=tmp_path)
    env = json.loads(proc.stdout)
    assert not {"DEEPSEEK_API_KEY", "JWT_SECRET", "DATABASE_URL"} & env.keys()


def test_unbounded_output_is_stopped():
    proc = run_process([sys.executable, "-I", "-c", "while True: print('x'*8192)"], timeout=5)
    assert proc.returncode != 0
    assert len(proc.stdout) + len(proc.stderr) <= MAX_OUTPUT_BYTES
    assert "输出超过" in proc.stderr.decode()


def test_timeout_terminates_process():
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-I", "-c", "while True: pass"], timeout=0.2)
    assert time.monotonic() - start < 5


def test_docker_timeout_removes_container(monkeypatch):
    monkeypatch.setattr(code_sandbox.shutil, "which", lambda _: "/bin/docker")
    commands = []

    def timeout(args, **kwargs):
        commands.append(args)
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(code_sandbox, "run_process", timeout)
    monkeypatch.setattr(code_sandbox.subprocess, "run", lambda args, **kw: commands.append(args))
    result = code_sandbox.run_isolated({"code": "", "cases": []}, 1)
    assert result["timed_out"]
    name = commands[0][commands[0].index("--name") + 1]
    assert commands[-1] == ["/bin/docker", "rm", "--force", name]


def test_local_python_function_still_works(monkeypatch):
    monkeypatch.setattr(code_sandbox.settings, "app_env", "development")
    monkeypatch.setattr(code_sandbox.settings, "code_runner_backend", "local")
    out = run_code("class Solution:\n def solve(self, x): return x + 1", [{"args": [2]}])
    assert out["error"] == ""
    assert out["results"] == [{"ok": True, "result": 3}]


@pytest.mark.parametrize("payload,expected", [
    ({"code": "class Solution:\n def solve(self, x): return x + 1", "cases": [{"args": [2]}]},
     {"results": [{"ok": True, "result": 3}]}),
    ({"operation": "generator", "source": "print('[1, 2, 3]')"}, {"cases": [1, 2, 3]}),
])
def test_worker_protocol_without_web_configuration(payload, expected):
    from pathlib import Path
    backend = str(Path(__file__).resolve().parents[1])
    program = (f"import sys; sys.path.insert(0, {backend!r}); "
               "from app.services.code_worker import main; "
               "assert 'app.config' not in sys.modules; main()")
    proc = subprocess.run([sys.executable, "-I", "-c", program],
                          input=json.dumps(payload).encode(), capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert not result["error"]
    for key, value in expected.items():
        assert result[key] == value


def test_unavailable_judge_does_not_score_or_advance_session(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.api import code as api
    from app.schemas.api import CodeSubmitRequest

    monkeypatch.setattr(api, "_get_owned_session", lambda *a: SimpleNamespace(id=1))
    monkeypatch.setattr(api, "_check_coding_turn", lambda *a: None)
    monkeypatch.setattr(api, "build_problem_view", lambda *a: {"title": "test"})
    monkeypatch.setattr(api, "judge_code", lambda *a, **kw: {"verdict": "unavailable"})

    def must_not_score(*args):
        raise AssertionError("unavailable infrastructure must not affect candidate scores")

    monkeypatch.setattr(api, "_engine_for", must_not_score)
    with pytest.raises(HTTPException) as exc:
        api.submit_code(1, CodeSubmitRequest(slug="test", code="pass"), SimpleNamespace(id=1), None)
    assert exc.value.status_code == 503


@pytest.mark.skipif(os.environ.get("RUN_SANDBOX_TESTS") != "1", reason="requires built Docker runner image")
class TestDockerIsolation:
    @pytest.fixture(autouse=True)
    def docker_runner(self, monkeypatch):
        monkeypatch.setattr(code_sandbox.settings, "app_env", "production")
        monkeypatch.setattr(code_sandbox.settings, "code_runner_backend", "docker")

    @pytest.mark.parametrize("language,code", [
        ("python", "class Solution:\n def solve(self, x): return x + 1"),
        ("java", "class Solution { public int solve(int x) { return x + 1; } }"),
        ("cpp", "class Solution { public: int solve(int x) { return x + 1; } };"),
        ("go", "func solve(x int) int { return x + 1 }"),
    ])
    def test_function_languages(self, language, code):
        cfg = {"method": "solve", "params": ["x"],
               "examples": [{"args": [2], "expected": 3}]}
        out = run_code(code, cfg["examples"], language=language, problem_cfg=cfg)
        assert out["error"] == "", out
        assert out["results"][0]["result"] == 3

    def test_isolation_and_resource_limits(self, monkeypatch, tmp_path):
        sentinel = tmp_path / "host-only.txt"
        sentinel.write_text("host-private-test-data")
        monkeypatch.setenv("JWT_SECRET", "host-secret")
        result = _run_gen(
            "import os,socket,json,resource\nfrom pathlib import Path\n"
            "checks = [os.getuid() == 10001, 'JWT_SECRET' not in os.environ]\n"
            f"checks.append(not os.path.exists({str(sentinel)!r}))\n"
            "try:\n open('/escape.txt', 'w').write('x'); checks.append(False)\n"
            "except OSError:\n checks.append(True)\n"
            "try:\n socket.create_connection(('1.1.1.1', 53), timeout=1); checks.append(False)\n"
            "except OSError:\n checks.append(True)\n"
            "checks.append(int(Path('/sys/fs/cgroup/memory.max').read_text()) <= 512*1024*1024)\n"
            "checks.append(int(Path('/sys/fs/cgroup/pids.max').read_text()) <= 64)\n"
            "checks.append(resource.getrlimit(resource.RLIMIT_NOFILE)[0] <= 128)\n"
            "checks.append(resource.getrlimit(resource.RLIMIT_FSIZE)[0] <= 16*1024*1024)\n"
            "print(json.dumps(checks))\n"
        )
        assert result.get("cases") == [True] * 9, result

    def test_container_can_run_scratch(self):
        out = run_code("import sys\nprint(int(sys.stdin.read()) + 1)",
                       [{"args": [2]}], coding_mode="scratch")
        assert out["results"] == [{"ok": True, "result": 3}], out
