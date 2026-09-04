"""可版本化、可审批的论文级项目记忆结构。"""

from __future__ import annotations

import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


QuestionText = Annotated[str, Field(min_length=1, max_length=1000)]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
ConstraintText = Annotated[str, Field(min_length=1, max_length=500)]
FoundationText = Annotated[str, Field(min_length=1, max_length=1000)]


class MemoryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(default="", max_length=1000)
    source: Literal["AUTHOR", "SUPERVISOR", "TEAM"] = "AUTHOR"
    active: bool = True


class SupervisorFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1000)
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "RESOLVED"] = "PENDING"
    response: str = Field(default="", max_length=1000)


class TerminologyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    term: str = Field(min_length=1, max_length=120)
    preferred_form: str = Field(min_length=1, max_length=120)
    definition: str = Field(default="", max_length=600)
    forbidden_aliases: list[ShortText] = Field(default_factory=list, max_length=20)


class WritingStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    language: Literal["zh-CN", "en-US"] = "zh-CN"
    tone: str = Field(default="客观、审慎、学术", max_length=200)
    person: str = Field(default="避免不必要的第一人称", max_length=200)
    tense: str = Field(default="按学科惯例使用", max_length=200)
    citation_style: str = Field(default="GB/T 7714-2015", max_length=120)
    constraints: list[ConstraintText] = Field(default_factory=list, max_length=30)


class RevisionStoppingPolicy(BaseModel):
    """有界自动修订的可配置默认预算，不限制作者手工修订。"""

    model_config = ConfigDict(extra="forbid")

    max_revision_rounds: int = Field(default=3, ge=1, le=10)
    plateau_rounds: int = Field(default=2, ge=1, le=5)
    min_score_improvement: float = Field(default=0.5, ge=0, le=10)


class ProjectMemory(BaseModel):
    """只有审批后的版本才能进入Agent上下文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_questions: list[QuestionText] = Field(default_factory=list, max_length=20)
    scope_boundaries: list[FoundationText] = Field(default_factory=list, max_length=50)
    forbidden_claims: list[FoundationText] = Field(default_factory=list, max_length=50)
    unresolved_claims: list[FoundationText] = Field(default_factory=list, max_length=50)
    decisions: list[MemoryDecision] = Field(default_factory=list, max_length=50)
    supervisor_feedback: list[SupervisorFeedback] = Field(default_factory=list, max_length=50)
    terminology: list[TerminologyEntry] = Field(default_factory=list, max_length=100)
    writing_style: WritingStyle | None = None
    stopping_policy: RevisionStoppingPolicy = Field(
        default_factory=RevisionStoppingPolicy
    )
    version_note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_memory(self) -> "ProjectMemory":
        self.research_questions = [
            value.strip() for value in self.research_questions if value.strip()
        ]
        normalized_questions = [value.casefold() for value in self.research_questions]
        if len(normalized_questions) != len(set(normalized_questions)):
            raise ValueError("研究问题不得重复")
        for field_name, label in (
            ("scope_boundaries", "范围边界"),
            ("forbidden_claims", "禁写主张"),
            ("unresolved_claims", "待解决主张"),
        ):
            values = [value.strip() for value in getattr(self, field_name) if value.strip()]
            setattr(self, field_name, values)
            normalized = [value.casefold() for value in values]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{label}不得重复")
        terms = [entry.term.casefold() for entry in self.terminology]
        if len(terms) != len(set(terms)):
            raise ValueError("术语条目不得重复")
        if not any((
            self.research_questions,
            self.scope_boundaries,
            self.forbidden_claims,
            self.unresolved_claims,
            self.decisions,
            self.supervisor_feedback,
            self.terminology,
            self.writing_style,
        )):
            raise ValueError("项目记忆至少需要一类有效内容")
        return self


def validate_project_memory(value: dict) -> ProjectMemory:
    try:
        return ProjectMemory.model_validate(value)
    except ValidationError as exc:
        issues = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors(include_input=False)[:6]
        )
        raise ValueError(f"项目记忆校验失败: {issues}") from exc


def project_memory_prompt_block(value: dict | None, max_chars: int = 3500) -> str:
    """把已批准记忆转为有长度上限的只读提示块。"""
    if not value:
        return "【已批准项目记忆】无。"
    memory = validate_project_memory(value)
    payload = memory.model_dump()
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) > max_chars:
        # 保留完整JSON条目，禁止按字符切断后向模型注入不可解析的半截结构。
        compact: dict = {"_truncated": True}

        def _try(candidate: dict) -> bool:
            return len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) <= max_chars

        for field_name in (
            "research_questions",
            "scope_boundaries",
            "forbidden_claims",
            "unresolved_claims",
            "decisions",
            "supervisor_feedback",
            "terminology",
        ):
            selected: list = []
            for item in payload.get(field_name, []) or []:
                candidate = {**compact, field_name: [*selected, item]}
                if not _try(candidate):
                    break
                selected.append(item)
            if selected:
                compact[field_name] = selected
        for field_name in ("writing_style", "stopping_policy", "version_note"):
            field_value = payload.get(field_name)
            if field_value in (None, "", [], {}):
                continue
            candidate = {**compact, field_name: field_value}
            if _try(candidate):
                compact[field_name] = field_value
        serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    return "【已批准项目记忆】\n" + serialized


def evaluate_revision_stopping(
    policy: RevisionStoppingPolicy | dict | None,
    *,
    completed_rounds: int = 0,
    score_history: list[float] | tuple[float, ...] = (),
    evidence_gaps: list[str] | tuple[str, ...] = (),
    specialist_conflicts: list[str] | tuple[str, ...] = (),
    target_reached: bool = False,
) -> dict[str, str | bool]:
    """返回可审计停止原因；只约束自动修订，不覆盖作者决定。"""

    config = (
        policy if isinstance(policy, RevisionStoppingPolicy)
        else RevisionStoppingPolicy.model_validate(policy or {})
    )
    if completed_rounds < 0:
        raise ValueError("completed_rounds 不能为负数")
    scores = [float(value) for value in score_history]
    if any(not math.isfinite(value) for value in scores):
        raise ValueError("score_history 必须是有限数值")

    if any(str(item).strip() for item in evidence_gaps):
        return {
            "should_stop": True,
            "reason": "EVIDENCE_GAP",
            "next_action": "补充证据、删除主张或降低主张强度",
        }
    if any(str(item).strip() for item in specialist_conflicts):
        return {
            "should_stop": True,
            "reason": "SPECIALIST_CONFLICT",
            "next_action": "提交作者裁决尚未解决的专家冲突",
        }
    if target_reached:
        return {
            "should_stop": True,
            "reason": "TARGET_REACHED",
            "next_action": "结束当前迭代并提交作者评审",
        }
    if completed_rounds >= config.max_revision_rounds:
        return {
            "should_stop": True,
            "reason": "MAX_ROUNDS",
            "next_action": "停止自动修订并提交当前版本供作者评审",
        }
    window = config.plateau_rounds + 1
    if len(scores) >= window:
        recent = scores[-window:]
        improvements = [right - left for left, right in zip(recent, recent[1:])]
        if all(value < config.min_score_improvement for value in improvements):
            return {
                "should_stop": True,
                "reason": "SCORE_PLATEAU",
                "next_action": "停止低收益修订并报告剩余问题",
            }
    return {
        "should_stop": False,
        "reason": "CONTINUE",
        "next_action": "继续当前有界修订",
    }
