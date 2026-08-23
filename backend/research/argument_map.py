"""论证图结构与确定性完整性校验。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from evidence import ClaimType


class ArgumentRole(str, Enum):
    THESIS = "THESIS"
    CLAIM = "CLAIM"
    COUNTERCLAIM = "COUNTERCLAIM"
    LIMITATION = "LIMITATION"


@dataclass(frozen=True)
class ArgumentClaimSpec:
    claim_key: str
    text: str
    section_id: str
    claim_type: ClaimType
    role: ArgumentRole
    parent_keys: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim_key.strip():
            raise ValueError("claim_key 不能为空")
        if not self.text.strip():
            raise ValueError("论断 text 不能为空")
        if not self.section_id.strip():
            raise ValueError("论断 section_id 不能为空")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["claim_type"] = self.claim_type.value
        value["role"] = self.role.value
        return value


@dataclass(frozen=True)
class ArgumentMap:
    title: str
    research_questions: tuple[str, ...]
    claims: tuple[ArgumentClaimSpec, ...]

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("论证图 title 不能为空")
        if not self.research_questions:
            raise ValueError("论证图 research_questions 不能为空")
        if not self.claims:
            raise ValueError("论证图 claims 不能为空")
        keys = [claim.claim_key for claim in self.claims]
        if len(keys) != len(set(keys)):
            raise ValueError("论证图 claim_key 必须唯一")
        known = set(keys)
        if not any(claim.role == ArgumentRole.THESIS for claim in self.claims):
            raise ValueError("论证图至少需要一个 THESIS 核心论断")
        parents = {claim.claim_key: claim.parent_keys for claim in self.claims}
        for claim in self.claims:
            if claim.claim_key in claim.parent_keys:
                raise ValueError(f"论断 {claim.claim_key} 不能依赖自身")
            unknown = set(claim.parent_keys) - known
            if unknown:
                raise ValueError(
                    f"论断 {claim.claim_key} 引用了不存在的父论断: {sorted(unknown)}"
                )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("论证图不能包含循环依赖")
            if key in visited:
                return
            visiting.add(key)
            for parent in parents[key]:
                visit(parent)
            visiting.remove(key)
            visited.add(key)

        for key in keys:
            visit(key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "research_questions": list(self.research_questions),
            "claims": [claim.to_dict() for claim in self.claims],
        }
