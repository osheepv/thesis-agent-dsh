# -*- coding: utf-8 -*-
"""真实供应商十环验收脚本。

前置条件：
    1. 在 ``backend`` 目录启动服务并配置真实模型；
    2. 正式验收必须设置 ``THESIS_DEEPSEEK_FALLBACK_TO_MOCK=false``；
    3. 服务保持 ``THESIS_JOB_WORKER_ENABLED=true``。

脚本严格执行：后台Job → 自动验收 → 作者决策/确认 → 下一环。它不会绕过
候选题选择、文献筛选、引用或DOCX门禁。报告只保存统计值，不保存论文正文、
API密钥或完整供应商响应。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE = os.getenv("THESIS_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TITLE = os.getenv(
    "THESIS_ACCEPTANCE_TITLE",
    "生成式人工智能辅助学术写作中的引用可信性保障机制研究",
)
DEGREE = os.getenv("THESIS_ACCEPTANCE_DEGREE", "BACHELOR")
SUBJECT_FIELD = os.getenv("THESIS_ACCEPTANCE_SUBJECT", "人工智能治理与学术信息管理")
SCOPE = os.getenv("THESIS_ACCEPTANCE_SCOPE", "all")
SESSION_ID = os.getenv(
    "THESIS_ACCEPTANCE_SESSION",
    "real-acceptance-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
)
TASK_ID_OVERRIDE = os.getenv("THESIS_ACCEPTANCE_TASK_ID", "").strip()
RUN_ID = os.getenv(
    "THESIS_ACCEPTANCE_RUN_ID",
    datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
)
REPORT_PATH = Path(
    os.getenv(
        "THESIS_ACCEPTANCE_REPORT",
        f"output/acceptance/{SESSION_ID}.json",
    )
)
JOB_TIMEOUT_SECONDS = int(os.getenv("THESIS_ACCEPTANCE_JOB_TIMEOUT", "1800"))
LITERATURE_LIMIT = max(3, int(os.getenv("THESIS_ACCEPTANCE_LITERATURE_LIMIT", "8")))

RING_LABELS = {
    1: "选题",
    2: "开题评审",
    3: "文献调研",
    4: "综述评审",
    5: "大纲",
    6: "撰写",
    7: "润色",
    8: "引用校验",
    9: "排版",
    10: "定稿",
}
TOKEN_BUDGETS = {
    1: 20_000,
    2: 15_000,
    3: 5_000,
    4: 15_000,
    5: 20_000,
    6: 80_000,
    7: 80_000,
    8: 5_000,
    9: 5_000,
    10: 5_000,
}
TERMINAL_JOB_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


class AcceptanceError(RuntimeError):
    """验收被真实业务门禁或运行错误阻断。"""


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as parse_error:
            raise AcceptanceError(f"HTTP {exc.code}: {raw[:300]}") from parse_error
    except Exception as exc:  # noqa: BLE001
        raise AcceptanceError(f"请求失败 {method} {path}: {exc}") from exc


def _get(path: str) -> dict[str, Any]:
    return _request("GET", path)


def _post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request("POST", path, payload or {})


def _require_ok(response: dict[str, Any], label: str) -> dict[str, Any]:
    if int(response.get("code", 1)) != 0:
        raise AcceptanceError(f"{label}失败: {str(response.get('msg', response))[:500]}")
    return dict(response.get("data") or {})


def _task_path(task_id: str, suffix: str) -> str:
    session = urllib.parse.quote(SESSION_ID, safe="")
    return f"/api/v1/console/tasks/{task_id}{suffix}?session_id={session}"


def _wait_job(task_id: str, job_id: str, label: str) -> dict[str, Any]:
    started = time.monotonic()
    delay = 1.0
    last_status = ""
    while time.monotonic() - started < JOB_TIMEOUT_SECONDS:
        response = _get(_task_path(task_id, f"/jobs/{job_id}"))
        job = _require_ok(response, f"查询{label}作业")
        status = str(job.get("status", ""))
        if status != last_status:
            print(
                f"   {label}: {status} | attempt={job.get('attempt', 0)} "
                f"| tokens={job.get('tokens_used', 0)}"
            )
            last_status = status
        if status in TERMINAL_JOB_STATES:
            return job
        time.sleep(delay)
        delay = min(8.0, delay * 1.5)
    raise AcceptanceError(f"{label}超过 {JOB_TIMEOUT_SECONDS} 秒仍未结束")


def _run_job(
    task_id: str,
    operation: str,
    payload: dict[str, Any],
    label: str,
    *,
    token_budget: int,
) -> dict[str, Any]:
    response = _post(
        _task_path(task_id, "/jobs"),
        {
            "operation": operation,
            "payload": payload,
            "idempotency_key": (
                f"{SESSION_ID}:{RUN_ID}:{operation}:"
                f"{json.dumps(payload, sort_keys=True)}"
            ),
            "max_attempts": 2,
            "token_budget": token_budget,
            "cost_budget": 0,
        },
    )
    queued = _require_ok(response, f"入队{label}")
    return _wait_job(task_id, str(queued["job_id"]), label)


def _result_data(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    return dict(result.get("data") or {}) if isinstance(result, dict) else {}


def _job_record(ring_no: int, job: dict[str, Any]) -> dict[str, Any]:
    data = _result_data(job)
    summary: dict[str, Any] = {}
    if ring_no == 1:
        summary = {"candidate_count": len(data.get("candidates", []) or [])}
    elif ring_no == 3:
        summary = {"candidate_literature_count": len(data.get("items", []) or [])}
    elif ring_no == 5:
        summary = {"outline_node_count": len(data.get("chapters", []) or [])}
    elif ring_no in (6, 7):
        summary = {
            "chapter_count": len(data.get("chapters", []) or []),
            "total_words": int(data.get("total_words", 0) or 0),
        }
    elif ring_no == 8:
        summary = {key: data.get(key, 0) for key in ("total", "passed", "uncertain", "failed")}
        summary["reference_entry_count"] = len(data.get("reference_entries", []) or [])
    elif ring_no == 9:
        summary = {
            "hard_issues": len(data.get("hard_issues", []) or []),
            "soft_issues": len(data.get("soft_issues", []) or []),
        }
    elif ring_no == 10:
        rings = list(data.get("rings", []) or [])
        summary = {
            "passed_rings": sum(1 for item in rings if item.get("status") == "通过"),
            "total_checked": len(rings),
            "ready": bool(data.get("compliant")) and not data.get("materials_missing"),
        }
    return {
        "ring_no": ring_no,
        "label": RING_LABELS[ring_no],
        "job_id": job.get("job_id", ""),
        "status": job.get("status", ""),
        "attempt": job.get("attempt", 0),
        "input_tokens": job.get("input_tokens", 0),
        "output_tokens": job.get("output_tokens", 0),
        "tokens_used": job.get("tokens_used", 0),
        "token_budget": job.get("token_budget", 0),
        "cost_used": job.get("cost_used", 0),
        "error": str(job.get("error", ""))[:500],
        "summary": summary,
    }


def _select_literature(items: list[dict[str, Any]]) -> list[int]:
    preferred = sorted(
        (
            index
            for index, item in enumerate(items)
            if str(item.get("doi", "")).strip()
            and str(item.get("reliability", "")).lower() in {"verified", "matched"}
            and float(item.get("relevance_score", 0) or 0) >= 0.12
        ),
        key=lambda index: -float(items[index].get("relevance_score", 0) or 0),
    )
    return preferred[: min(LITERATURE_LIMIT, len(preferred))]


def _confirm(task_id: str, ring_no: int) -> None:
    progress = _require_ok(_get(_task_path(task_id, "/progress")), f"读取环{ring_no}确认前进度")
    if progress.get("phase_state") != "WAITING_APPROVAL":
        raise AcceptanceError(
            f"环{ring_no}未进入WAITING_APPROVAL，而是{progress.get('phase_state')}"
        )
    _require_ok(
        _post(_task_path(task_id, f"/rings/{ring_no}/confirm"), {"confirmed": True}),
        f"确认环{ring_no}",
    )


def _download_docx(download_url: str) -> dict[str, Any]:
    if not download_url:
        raise AcceptanceError("DOCX作业未返回download_url")
    separator = "&" if "?" in download_url else "?"
    url = BASE + download_url + separator + urllib.parse.urlencode({"session_id": SESSION_ID})
    try:
        with urllib.request.urlopen(url, timeout=180) as response:
            content = response.read()
    except Exception as exc:  # noqa: BLE001
        raise AcceptanceError(f"下载DOCX失败: {exc}") from exc
    if content[:2] != b"PK":
        raise AcceptanceError("下载内容不是有效DOCX/ZIP")
    target = REPORT_PATH.with_suffix(".docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    try:
        from docx import Document

        document = Document(target)
        paragraphs = [p for p in document.paragraphs if p.text.strip()]
        heading_count = sum(
            1
            for paragraph in paragraphs
            if paragraph.style
            and str(paragraph.style.name or "").lower().startswith("heading")
        )
    except Exception as exc:  # noqa: BLE001
        raise AcceptanceError(f"DOCX语义结构读取失败: {exc}") from exc
    if len(paragraphs) < 15 or heading_count < 3:
        raise AcceptanceError(
            f"DOCX正文结构不足: paragraphs={len(paragraphs)}, headings={heading_count}"
        )
    return {
        "path": str(target),
        "bytes": len(content),
        "zip_signature": "PK",
        "paragraph_count": len(paragraphs),
        "heading_count": heading_count,
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    new_report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "base_url": BASE,
        "session_id": SESSION_ID,
        "title": TITLE,
        "degree": DEGREE,
        "subject_field": SUBJECT_FIELD,
        "scope": SCOPE,
        "selection_policy": "作者验收脚本显式选择模型排序第一的候选题",
        "literature_policy": f"优先纳入有DOI且已匹配题录，最多{LITERATURE_LIMIT}条",
        "rings": [],
    }
    if TASK_ID_OVERRIDE and REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        report["status"] = "RUNNING"
        report.pop("failure", None)
        report.setdefault("resumes", []).append({
            "run_id": RUN_ID,
            "resumed_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        report = new_report
    task_id = TASK_ID_OVERRIDE
    docx_job: dict[str, Any] = {}
    try:
        if task_id:
            progress = _require_ok(
                _get(_task_path(task_id, "/progress")),
                "读取恢复进度",
            )
            start_ring = int(progress.get("current_ring_no", 1) or 1)
            report["task_id"] = task_id
            print(f"任务从环{start_ring}恢复: {task_id} | {SESSION_ID}")
        else:
            created = _post(
                "/api/v1/console/tasks",
                {
                    "title": TITLE,
                    "degree": DEGREE,
                    "subject_field": SUBJECT_FIELD,
                    "session_id": SESSION_ID,
                    "scope": SCOPE,
                },
            )
            task_id = str(_require_ok(created, "创建任务")["task_id"])
            report["task_id"] = task_id
            start_ring = 1
            print(f"任务已创建: {task_id} | {SESSION_ID}")

        for ring_no in range(start_ring, 11):
            if ring_no == 9:
                docx_job = _run_job(
                    task_id,
                    "docx.generate",
                    {},
                    "生成DOCX",
                    token_budget=5_000,
                )
                if docx_job.get("status") != "SUCCEEDED":
                    raise AcceptanceError(
                        "DOCX作业失败: " + str(docx_job.get("error", ""))[:500]
                    )

            print(f"环{ring_no} {RING_LABELS[ring_no]}")
            job = _run_job(
                task_id,
                "ring.execute",
                {"ring_no": ring_no},
                f"环{ring_no}{RING_LABELS[ring_no]}",
                token_budget=TOKEN_BUDGETS[ring_no],
            )
            record = _job_record(ring_no, job)
            report["rings"].append(record)
            _write_report(report)
            if job.get("status") != "SUCCEEDED":
                raise AcceptanceError(
                    f"环{ring_no}作业失败: {str(job.get('error', ''))[:500]}"
                )
            data = _result_data(job)

            if ring_no == 1:
                candidates = list(data.get("candidates", []) or [])
                if not candidates:
                    raise AcceptanceError("环1没有候选题")
                chosen = str(candidates[0].get("title", "")).strip()
                _require_ok(
                    _post(
                        _task_path(task_id, "/rings/1/select"),
                        {"candidate_index": 0, "title": chosen},
                    ),
                    "登记作者选题",
                )
                report["chosen_title"] = chosen

            if ring_no == 3:
                items = [item for item in (data.get("items", []) or []) if isinstance(item, dict)]
                indexes = _select_literature(items)
                if len(indexes) < 3:
                    raise AcceptanceError(f"环3只有{len(indexes)}条可纳入文献，低于验收下限3")
                curated = _require_ok(
                    _post(
                        _task_path(task_id, "/rings/3/curate"),
                        {"included_indexes": indexes},
                    ),
                    "保存文献筛选",
                )
                report["literature"] = {
                    "candidate_count": len(items),
                    "included_count": curated.get("included_count", 0),
                    "excluded_count": curated.get("excluded_count", 0),
                }

            _confirm(task_id, ring_no)
            print(f"   已确认环{ring_no}")

        progress = _require_ok(_get(_task_path(task_id, "/progress")), "读取最终进度")
        report["progress"] = {
            "complete_percent": progress.get("complete_percent"),
            "phase_state": progress.get("phase_state"),
            "passed_ring_count": sum(
                1 for item in (progress.get("rings", []) or []) if item.get("state") == "PASSED"
            ),
        }
        if progress.get("complete_percent") != 100 or progress.get("phase_state") != "PASSED":
            raise AcceptanceError(f"最终进度不合格: {report['progress']}")

        generated = _result_data(docx_job)
        report["docx"] = _download_docx(str(generated.get("download_url", "")))
        report["status"] = "PASSED"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["total_tokens"] = sum(
            int(item.get("tokens_used", 0) or 0) for item in report["rings"]
        )
        observed_cost = sum(
            float(item.get("cost_used", 0) or 0) for item in report["rings"]
        )
        report["total_cost"] = observed_cost if observed_cost > 0 else None
        report["cost_observation"] = (
            "observed"
            if observed_cost > 0
            else "unavailable_pricing_not_configured"
        )
        _write_report(report)
        print(
            f"验收通过: 10/10环 | tokens={report['total_tokens']} "
            f"| report={REPORT_PATH}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        report["status"] = "FAILED"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["failure"] = str(exc)[:1000]
        if task_id:
            report["task_id"] = task_id
        _write_report(report)
        print(f"验收停止: {exc}", file=sys.stderr)
        print(f"失败报告: {REPORT_PATH}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
