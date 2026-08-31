# -*- coding: utf-8 -*-
"""学术质量评测框架的测试（H4-003）。

验证评测运行器自身的正确性：
1. fixtures 文件存在且可加载。
2. 每个suite的评测函数能正确判定通过/失败。
3. CLI入口能运行并返回正确的退出码。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

from run_academic_eval import (  # noqa: E402
    CaseResult,
    evaluate_citation_integrity,
    evaluate_claim_evidence,
    evaluate_literature_relevance,
    load_fixtures,
    run_suite,
)


class TestFixtureLoading:
    def test_literature_relevance_fixtures_exist(self):
        cases = load_fixtures("literature_relevance")
        assert len(cases) >= 8, "文献相关度fixture至少8条"
        assert all("case_id" in c for c in cases)
        assert all("theme" in c for c in cases)
        assert all("expected_relevant" in c for c in cases)

    def test_claim_evidence_fixtures_exist(self):
        cases = load_fixtures("claim_evidence")
        assert len(cases) >= 8, "论断-证据fixture至少8条"
        assert all("claim_text" in c for c in cases)
        assert all("excerpt_text" in c for c in cases)
        assert all("expected_supported" in c for c in cases)

    def test_citation_integrity_fixtures_exist(self):
        cases = load_fixtures("citation_integrity")
        assert len(cases) >= 8, "引用完整性fixture至少8条"
        assert all("structure_status" in c for c in cases)
        assert all("metadata_status" in c for c in cases)
        assert all("evidence_status" in c for c in cases)


class TestLiteratureRelevance:
    def test_positive_cases_pass(self):
        cases = load_fixtures("literature_relevance")
        positives = [c for c in cases if c.get("expected_relevant")]
        assert positives, "至少1条正例"
        for case in positives:
            result = evaluate_literature_relevance(case)
            assert result.passed, f"{case['case_id']}: {result.reasons}"

    def test_negative_cases_pass(self):
        cases = load_fixtures("literature_relevance")
        negatives = [c for c in cases if not c.get("expected_relevant")]
        assert negatives, "至少1条反例"
        for case in negatives:
            result = evaluate_literature_relevance(case)
            assert result.passed, f"{case['case_id']}: {result.reasons}"

    def test_empty_theme_fails(self):
        result = evaluate_literature_relevance({"case_id": "test-empty", "theme": "", "title": "some title", "abstract": "some abstract"})
        assert not result.passed
        assert any("选题为空" in r for r in result.reasons)


class TestClaimEvidence:
    def test_supported_cases_pass(self):
        cases = load_fixtures("claim_evidence")
        positives = [c for c in cases if c.get("expected_supported")]
        assert positives, "至少1条支撑例"
        for case in positives:
            result = evaluate_claim_evidence(case)
            assert result.passed, f"{case['case_id']}: {result.reasons}"

    def test_unsupported_cases_pass(self):
        cases = load_fixtures("claim_evidence")
        negatives = [c for c in cases if not c.get("expected_supported")]
        assert negatives, "至少1条不支撑例"
        for case in negatives:
            result = evaluate_claim_evidence(case)
            assert result.passed, f"{case['case_id']}: {result.reasons}"


class TestCitationIntegrity:
    def test_valid_cases_pass(self):
        cases = load_fixtures("citation_integrity")
        valid = [c for c in cases if not c.get("expected_error")]
        assert valid, "至少1条合法例"
        for case in valid:
            result = evaluate_citation_integrity(case)
            assert result.passed, f"{case['case_id']}: {result.reasons}"

    def test_error_cases_caught(self):
        cases = load_fixtures("citation_integrity")
        errors = [c for c in cases if c.get("expected_error")]
        assert errors, "至少1条错误例"
        for case in errors:
            result = evaluate_citation_integrity(case)
            assert result.passed, f"{case['case_id']}: {result.reasons}"


class TestSuiteRunner:
    def test_all_suites_run(self):
        for suite_name in ("literature_relevance", "claim_evidence", "citation_integrity"):
            report = run_suite(suite_name)
            assert report.total > 0, f"{suite_name} 无case"
            assert report.failed == 0, (
                f"{suite_name} 有 {report.failed} 条失败: "
                + "; ".join(f"{r.case_id}: {r.reasons}" for r in report.results if not r.passed)
            )

    def test_case_result_structure(self):
        result = CaseResult(case_id="test", suite="test", passed=True)
        assert result.passed
        assert result.reasons == []
