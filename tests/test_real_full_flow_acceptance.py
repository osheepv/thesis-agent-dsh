"""真实十环验收脚本默认必须保持零费用预检。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_full_flow_acceptance_defaults_to_safe_preflight():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_full_flow_acceptance.py",
            "--degree",
            "MASTER",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout.strip())

    assert payload["mode"] == "preflight"
    assert payload["will_call_model"] is False
    assert payload["degree"] == "MASTER"
    assert payload["runtime"]["provider"] == "deepseek"
    assert "api_key" not in payload["runtime"]
    assert payload["token_budgets"]["6"] == 160_000
    assert payload["max_total_token_budget"] == sum(
        payload["token_budgets"].values()
    )
