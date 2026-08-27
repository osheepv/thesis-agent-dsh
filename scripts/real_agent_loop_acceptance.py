# -*- coding: utf-8 -*-
"""低成本真实DeepSeek环6 Agent Loop验收。

默认只执行安全预检；必须显式传入``--execute``才会调用模型。
脚本只生成两章写作计划，不撰写论文正文。报告不保存API Key、
完整供应商响应或论文内容。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
# 本脚本只验收受控文献池工具，禁用本地向量模型以保持结果可重复。
os.environ["THESIS_RAG_ENABLED"] = "false"

from common.agent_loop import AgentLoopSettings  # noqa: E402
from common.aicoding.enums import Degree  # noqa: E402
from common.llm import get_llm_settings  # noqa: E402
from executor import ExecContext  # noqa: E402
from executor.ring6_chapter import _build_writing_plan  # noqa: E402
from jobs.registry import JobRegistry  # noqa: E402
from jobs.runtime import JobRuntime, Pricing, job_runtime_context  # noqa: E402


DEFAULT_REPORT = (
    ROOT
    / "output"
    / "acceptance"
    / f"deepseek-agent-loop-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
)


def _safe_runtime_view() -> dict[str, Any]:
    settings = get_llm_settings()
    return {
        "provider": "deepseek",
        "enabled": settings.enabled,
        "api_key_configured": bool(settings.api_key),
        "base_url": settings.base_url,
        "model": settings.model,
        "supports_tools": settings.supports_tools,
    }


def _context() -> tuple[ExecContext, list[tuple[str, str]]]:
    chapter_meta = [("第1章", "研究背景"), ("第2章", "方法与证据链")]
    ctx = ExecContext(
        subject_field="学术信息管理",
        degree=Degree.BACHELOR,
        theme="生成式人工智能辅助论文写作中的引用可追溯机制",
        session_id="deepseek-agent-loop-acceptance",
        outline=json.dumps({
            "chapters": [
                {"level": 1, "number": number, "title": title}
                for number, title in chapter_meta
            ]
        }, ensure_ascii=False),
        literature=[
            {
                "title": "ACCEPTANCE-SOURCE-1: citation traceability design",
                "abstract": "A controlled acceptance source about evidence provenance and citation verification.",
                "doi": "",
                "reliability": "acceptance_fixture",
            },
            {
                "title": "ACCEPTANCE-SOURCE-2: bounded academic writing agents",
                "abstract": "A controlled acceptance source about bounded tool use and human review gates.",
                "doi": "",
                "reliability": "acceptance_fixture",
            },
        ],
    )
    return ctx, chapter_meta


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path = path if path.is_absolute() else ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run(report_path: Path) -> dict[str, Any]:
    runtime_view = _safe_runtime_view()
    if not runtime_view["enabled"] or not runtime_view["api_key_configured"]:
        raise RuntimeError("DeepSeek未启用或未配置API Key")
    if not runtime_view["supports_tools"]:
        raise RuntimeError("当前DeepSeek模型未启用Tools能力")

    limits = AgentLoopSettings(
        enabled=True,
        max_turns=6,
        max_tool_calls=12,
        max_observation_chars=2000,
        max_output_tokens=1024,
    )
    registry = JobRegistry(":memory:")
    job = registry.create(
        task_id="AGENT-ACCEPTANCE",
        session_id="deepseek-agent-loop-acceptance",
        operation="ring6_agent_plan_acceptance",
        token_budget=18_000,
        max_attempts=1,
    )
    runtime = JobRuntime(
        registry=registry,
        job_id=job.job_id,
        worker_id="acceptance-worker",
        pricing=Pricing.from_env(),
    )
    ctx, chapter_meta = _context()
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    report: dict[str, Any] = {
        "status": "RUNNING",
        "started_at": started_at.isoformat(),
        "runtime": runtime_view,
        "limits": {
            "max_turns": limits.max_turns,
            "max_tool_calls": limits.max_tool_calls,
            "max_observation_chars": limits.max_observation_chars,
            "max_output_tokens": limits.max_output_tokens,
            "token_budget": 18_000,
        },
    }
    try:
        with job_runtime_context(runtime):
            plan = _build_writing_plan(
                ctx,
                ctx.theme,
                chapter_meta,
                limits,
            )
        usage = registry.get_by_id(job.job_id)
        suggested_refs = sorted({
            marker
            for chapter in plan.get("chapter_plans", [])
            for marker in chapter.get("suggested_refs", [])
        })
        verified_refs = list(plan.get("agent_verified_citations", []) or [])
        if not suggested_refs or not verified_refs:
            raise RuntimeError("验收计划未产生并核验任何引文")
        if not set(suggested_refs).issubset(set(verified_refs)):
            raise RuntimeError("验收计划仍包含未核验引文")
        report.update({
            "status": "PASSED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "result": {
                "chapter_plan_count": len(plan.get("chapter_plans", [])),
                "turns": int(plan.get("agent_turns", 0)),
                "tool_calls": int(plan.get("agent_tool_calls", 0)),
                "tools": [item.get("tool", "") for item in plan.get("agent_trace", [])],
                "suggested_citations": suggested_refs,
                "verified_citations": verified_refs,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
                "observed_cost": usage.cost_used if usage.cost_used > 0 else None,
            },
        })
    except Exception as exc:
        usage = registry.get_by_id(job.job_id)
        report.update({
            "status": "FAILED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "failure_type": type(exc).__name__,
            "failure": str(exc)[:500],
            "usage_at_failure": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.input_tokens + usage.output_tokens,
                "observed_cost": usage.cost_used if usage.cost_used > 0 else None,
            },
        })
        _write_report(report_path, report)
        raise
    finally:
        registry.close()
    _write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="显式允许一次有上限的真实DeepSeek调用",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="脱敏JSON报告路径",
    )
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({
            "mode": "preflight",
            "will_call_model": False,
            "runtime": _safe_runtime_view(),
        }, ensure_ascii=False))
        return 0
    report = _run(args.report)
    print(json.dumps({
        "status": report["status"],
        "report": str(args.report),
        "result": report.get("result", {}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
