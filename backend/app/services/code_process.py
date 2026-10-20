"""Bounded child processes. Resource isolation is provided by code_sandbox."""
from __future__ import annotations

import os
import signal
import subprocess
import threading

MAX_OUTPUT_BYTES = 1024 * 1024


def run_process(args, *, input=None, capture_output=True, timeout=5, cwd=None, env=None,
                extra_env_keys=()):
    # Never pass API keys, database credentials, or the web server's environment
    # to a submitted program or compiler. Keep toolchain/locale settings only.
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "JAVA_HOME", "LANG", "LC_ALL",
        "PYTHONIOENCODING", "PYTHONUTF8", "GO111MODULE", "JAVA_TOOL_OPTIONS", "GOMAXPROCS",
    }
    allowed.update(extra_env_keys)
    clean_env = {k: v for k, v in (env or os.environ).items() if k.upper() in allowed}
    clean_env.update(HOME=str(cwd or "/tmp"), GOCACHE="/tmp/go-cache", GOPATH="/tmp/go")
    proc = subprocess.Popen(
        args, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=clean_env,
        start_new_session=os.name != "nt",
    )
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    lock = threading.Lock()
    total = 0

    def stop():
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def read(stream, target):
        nonlocal total
        try:
            while chunk := stream.read1(8192):
                with lock:
                    remaining = max(0, MAX_OUTPUT_BYTES - total)
                    target.extend(chunk[:remaining])
                    total += len(chunk)
                    exceeded = total > MAX_OUTPUT_BYTES
                if exceeded:
                    overflow.set()
                    stop()
                    break
        finally:
            stream.close()

    def write():
        try:
            proc.stdin.write(input)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    readers = [threading.Thread(target=read, args=(s, b), daemon=True)
               for s, b in zip((proc.stdout, proc.stderr), buffers)]
    for thread in readers:
        thread.start()
    if input is not None:
        threading.Thread(target=write, daemon=True).start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop()
        proc.wait()
        raise
    finally:
        # Kill remaining children too, including children holding output pipes.
        stop()
        for thread in readers:
            thread.join(timeout=2)
    if overflow.is_set():
        return subprocess.CompletedProcess(args, 1, b"", "输出超过 1 MiB 限制".encode())
    return subprocess.CompletedProcess(args, proc.returncode, bytes(buffers[0]), bytes(buffers[1]))
