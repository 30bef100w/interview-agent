import os
import subprocess
import sys


def test_app_can_be_imported_without_model_credentials():
    env = {**os.environ, "DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "",
           "OPENAI_ADMIN_KEY": "", "APP_ENV": "development"}
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; assert app is not None"],
        env=env, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
