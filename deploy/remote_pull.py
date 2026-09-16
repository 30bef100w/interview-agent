#!/usr/bin/env python3
"""Pull latest main on server and rebuild containers."""
from __future__ import annotations

import os
import sys

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "124.223.107.171")
USER = os.environ.get("DEPLOY_USER", "ubuntu")
PASSWORD = os.environ.get("DEPLOY_PASSWORD", "")
REMOTE_DIR = os.environ.get("DEPLOY_DIR", "/home/ubuntu/face-agent")


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 1800) -> tuple[int, str, str]:
    print(f"$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    return code, out, err


def main() -> int:
    if not PASSWORD:
        print("Set DEPLOY_PASSWORD", file=sys.stderr)
        return 1
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=30)
    try:
        code, _, _ = run(ssh, f"test -d {REMOTE_DIR} || echo MISSING")
        if "MISSING" in _:
            print(f"Remote dir missing: {REMOTE_DIR}", file=sys.stderr)
            return 1
        run(ssh, f"cd {REMOTE_DIR} && git fetch origin main && git reset --hard origin/main")
        code, _, _ = run(
            ssh,
            f"cd {REMOTE_DIR} && docker compose --profile bundled-db up -d --build",
            timeout=3600,
        )
        if code != 0:
            return code
        code, out, _ = run(ssh, "curl -sf http://localhost/api/health")
        if code != 0:
            return code
        print("health:", out.strip())
        code, out, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://localhost/api/feedback/finished-count")
        print("feedback endpoint status:", out.strip())
        return 0 if out.strip() in ("401", "403") else 1
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
