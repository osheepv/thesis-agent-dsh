"""引用可信度分档的单调性与作者复核测试。"""

import pytest

from common.trust import (
    TrustCheckStatus,
    build_citation_trust_assessment,
    with_author_review,
)


def test_trust_tier_is_monotonic_and_author_review_is_separate():
    assessment = build_citation_trust_assessment(
        structure=TrustCheckStatus.PASSED,
        metadata=TrustCheckStatus.PASSED,
        evidence=TrustCheckStatus.NOT_ASSESSED,
    )

    assert assessment["highest_tier"] == "METADATA"
    assert assessment["author_review"]["status"] == "PENDING"
    assert assessment["warning"]

    reviewed = with_author_review(assessment, approved=True)
    assert reviewed["highest_tier"] == "METADATA"
    assert reviewed["author_review"]["status"] == "APPROVED"
    assert assessment["author_review"]["status"] == "PENDING"


def test_evidence_pass_requires_structure_and_metadata_pass():
    with pytest.raises(ValueError, match="证据通过"):
        build_citation_trust_assessment(
            structure=TrustCheckStatus.PASSED,
            metadata=TrustCheckStatus.PARTIAL,
            evidence=TrustCheckStatus.PASSED,
        )

    with pytest.raises(ValueError, match="元数据通过"):
        build_citation_trust_assessment(
            structure=TrustCheckStatus.FAILED,
            metadata=TrustCheckStatus.PASSED,
            evidence=TrustCheckStatus.NOT_ASSESSED,
        )
