# -*- coding: utf-8 -*-
"""学术质量评测运行器（H4-003）。

离线、确定性规则评测；不访问网络，不需要API Key。
规则结果不冒充真实模型质量结论；真实模型评测需显式执行并单独计费。

用法（项目根目录）：
    python evals/run_academic_eval.py
    python evals/run_academic_eval.py --suite literature_relevance
    python evals/run_academic_eval.py --suite all --verbose
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


@dataclass
class CaseResult:
    case_id: str
    suite: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class SuiteReport:
    suite: str
    total: int
    passed: int
    failed: int
    results: list[CaseResult] = field(default_factory=list)


def load_fixtures(name: str) -> list[dict[str, Any]]:
    path = ROOT / "evals" / "fixtures" / f"{name}.jsonl"
    if not path.exists():
        return []
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


# ---------------------------------------------------------------------------
# 文献相关度评测（复用环3的词法排序逻辑）
# ---------------------------------------------------------------------------

GENERIC_TERMS = {
    "研究", "方法", "系统", "模型", "算法", "优化", "分析", "设计", "实现",
    "基于", "面向", "场景", "检测", "本科", "毕业", "论文", "应用", "机制",
    "study", "research", "method", "system", "model", "algorithm", "optimization",
    "detection", "based", "approach", "analysis", "design",
}


def _lexical_terms(text: str) -> set[str]:
    """提取中英文检索词；中文使用2~4字n-gram。"""
    normalized = (text or "").lower()
    terms = {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{2,}", normalized)
        if token not in GENERIC_TERMS
    }
    for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        for width in (2, 3, 4):
            terms.update(
                sequence[index:index + width]
                for index in range(max(0, len(sequence) - width + 1))
            )
    return {term for term in terms if term not in GENERIC_TERMS}


def evaluate_literature_relevance(case: dict[str, Any]) -> CaseResult:
    case_id = case.get("case_id", "unknown")
    reasons: list[str] = []

    try:
        from executor.ring3 import LiteratureItem, _rank_by_relevance
    except ImportError as exc:
        return CaseResult(case_id, "literature_relevance", False, [f"导入失败: {exc}"])

    theme = case.get("theme", "")
    subject_field = case.get("subject_field", "")
    if not theme:
        return CaseResult(case_id, "literature_relevance", False, ["选题为空"])

    item = LiteratureItem(
        title=case.get("title", ""),
        abstract=case.get("abstract", ""),
        item_type=case.get("item_type", "article"),
        reliability=case.get("reliability", "uncertain"),
        citation_count=case.get("citation_count", 0),
    )
    ranked = _rank_by_relevance([item], theme, subject_field)
    score = ranked[0].relevance_score

    expected_relevant = case.get("expected_relevant", False)
    min_score = case.get("expected_min_score")
    max_score = case.get("expected_max_score")

    is_relevant = score >= 0.12
    if is_relevant != expected_relevant:
        reasons.append(
            f"相关度判定不匹配：score={score}，期望{'相关' if expected_relevant else '不相关'}"
        )
    if min_score is not None and is_relevant and score < min_score:
        reasons.append(f"相关度分数不足：score={score} < min={min_score}")
    if max_score is not None and not is_relevant and score > max_score:
        reasons.append(f"相关度分数过高：score={score} > max={max_score}")

    return CaseResult(case_id, "literature_relevance", not reasons, reasons)


# ---------------------------------------------------------------------------
# 论断-证据评测
# ---------------------------------------------------------------------------


def evaluate_claim_evidence(case: dict[str, Any]) -> CaseResult:
    case_id = case.get("case_id", "unknown")
    reasons: list[str] = []

    claim_text = case.get("claim_text", "")
    excerpt_text = case.get("excerpt_text", "")
    relation = case.get("relation", "")
    excerpt_status = case.get("excerpt_status", "")
    expected_supported = case.get("expected_supported", False)

    claim_terms = _lexical_terms(claim_text)
    excerpt_terms = _lexical_terms(excerpt_text)
    overlap = claim_terms & excerpt_terms
    jaccard = len(overlap) / len(claim_terms | excerpt_terms) if (claim_terms | excerpt_terms) else 0.0

    # 规则判定：
    # 1) 摘录状态必须是APPROVED才能支撑。
    # 2) 关系必须是SUPPORTS或METHOD。
    # 3) 词汇重叠度需要达到阈值（排除完全无关的摘录）。
    can_support = (
        excerpt_status == "APPROVED"
        and relation in ("SUPPORTS", "METHOD")
        and jaccard >= 0.05
    )

    if can_support != expected_supported:
        reasons.append(
            f"支撑判定不匹配：can_support={can_support}，"
            f"jaccard={jaccard:.4f}，期望{'支撑' if expected_supported else '不支撑'}"
        )

    return CaseResult(case_id, "claim_evidence", not reasons, reasons)


# ---------------------------------------------------------------------------
# 引用完整性评测（复用trust.py的分层模型）
# ---------------------------------------------------------------------------


def evaluate_citation_integrity(case: dict[str, Any]) -> CaseResult:
    case_id = case.get("case_id", "unknown")
    reasons: list[str] = []

    try:
        from common.trust import CitationTrustTier, TrustCheckStatus, build_citation_trust_assessment

        structure = TrustCheckStatus(case.get("structure_status", "NOT_ASSESSED"))
        metadata = TrustCheckStatus(case.get("metadata_status", "NOT_ASSESSED"))
        evidence = TrustCheckStatus(case.get("evidence_status", "NOT_ASSESSED"))
    except (ImportError, ValueError) as exc:
        return CaseResult(case_id, "citation_integrity", False, [f"构建失败: {exc}"])

    expected_error = case.get("expected_error", False)
    expected_tier = case.get("expected_tier", "")
    expected_warning = case.get("expected_warning", False)

    summaries = case.get("summaries")
    try:
        result = build_citation_trust_assessment(
            structure=structure, metadata=metadata, evidence=evidence,
            summaries=summaries,
        )
    except ValueError as exc:
        if expected_error:
            return CaseResult(case_id, "citation_integrity", True)
        reasons.append(f"意外报错: {exc}")
        return CaseResult(case_id, "citation_integrity", False, reasons)

    if expected_error:
        reasons.append("期望报错但未报错")
        return CaseResult(case_id, "citation_integrity", False, reasons)

    actual_tier = result.get("highest_tier", "")
    if actual_tier != expected_tier:
        reasons.append(f"层级不匹配：actual={actual_tier}，expected={expected_tier}")

    has_warning = bool(result.get("warning", ""))
    if has_warning != expected_warning:
        reasons.append(f"警告不匹配：actual={has_warning}，expected={expected_warning}")

    if "expected_author_status" in case:
        approved = case.get("author_approved", False)
        from common.trust import with_author_review
        reviewed = with_author_review(result, approved=approved)
        actual_status = reviewed.get("author_review", {}).get("status", "")
        expected_status = case["expected_author_status"]
        if actual_status != expected_status:
            reasons.append(
                f"作者审批状态不匹配：actual={actual_status}，expected={expected_status}"
            )

    return CaseResult(case_id, "citation_integrity", not reasons, reasons)


# ---------------------------------------------------------------------------
# 运行器
# ---------------------------------------------------------------------------

SUITES = {
    "literature_relevance": (load_fixtures, evaluate_literature_relevance),
    "claim_evidence": (load_fixtures, evaluate_claim_evidence),
    "citation_integrity": (load_fixtures, evaluate_citation_integrity),
}


def run_suite(suite_name: str) -> SuiteReport:
    loader, evaluator = SUITES[suite_name]
    cases = loader(suite_name)
    results = [evaluator(case) for case in cases]
    passed = sum(1 for r in results if r.passed)
    return SuiteReport(
        suite=suite_name,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )


def format_report(report: SuiteReport, verbose: bool = False) -> str:
    lines = [
        f"\n=== {report.suite} ===",
        f"  总计: {report.total}  通过: {report.passed}  失败: {report.failed}",
    ]
    for result in report.results:
        icon = "PASS" if result.passed else "FAIL"
        if verbose or not result.passed:
            detail = ""
            if result.reasons:
                detail = " | " + "; ".join(result.reasons)
            lines.append(f"  [{icon}] {result.case_id}{detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="学术质量评测运行器")
    parser.add_argument("--suite", default="all", choices=["all"] + list(SUITES.keys()))
    parser.add_argument("--verbose", action="store_true", help="输出全部case（含通过）")
    args = parser.parse_args()

    suite_names = list(SUITES.keys()) if args.suite == "all" else [args.suite]
    exit_code = 0
    for name in suite_names:
        report = run_suite(name)
        print(format_report(report, verbose=args.verbose))
        if report.failed > 0:
            exit_code = 1

    total = sum(run_suite(n).total for n in suite_names)
    total_pass = sum(run_suite(n).passed for n in suite_names)
    total_fail = total - total_pass
    print(f"\n{'='*40}")
    print(f"学术质量评测总结: {total_pass}/{total} 通过, {total_fail} 失败")
    print("注意：规则评测结果不冒充真实模型质量结论。")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
