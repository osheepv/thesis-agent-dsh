"""真实Agent验收脚本默认必须是不调模型的安全预检。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_agent_acceptance_defaults_to_safe_preflight():
    completed = subprocess.run(
        [sys.executable, "scripts/real_agent_loop_acceptance.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout.strip())

    assert payload["mode"] == "preflight"
    assert payload["will_call_model"] is False
    assert payload["runtime"]["provider"] == "deepseek"
    assert "api_key" not in payload["runtime"]
    assert "api_key_configured" in payload["runtime"]
