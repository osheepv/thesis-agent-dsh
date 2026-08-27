"""可版本化、可审批的论文级项目记忆结构。"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


QuestionText = Annotated[str, Field(min_length=1, max_length=1000)]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
ConstraintText = Annotated[str, Field(min_length=1, max_length=500)]


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


class ProjectMemory(BaseModel):
    """只有审批后的版本才能进入Agent上下文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_questions: list[QuestionText] = Field(default_factory=list, max_length=20)
    decisions: list[MemoryDecision] = Field(default_factory=list, max_length=50)
    supervisor_feedback: list[SupervisorFeedback] = Field(default_factory=list, max_length=50)
    terminology: list[TerminologyEntry] = Field(default_factory=list, max_length=100)
    writing_style: WritingStyle | None = None
    version_note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_memory(self) -> "ProjectMemory":
        self.research_questions = [
            value.strip() for value in self.research_questions if value.strip()
        ]
        normalized_questions = [value.casefold() for value in self.research_questions]
        if len(normalized_questions) != len(set(normalized_questions)):
            raise ValueError("研究问题不得重复")
        terms = [entry.term.casefold() for entry in self.terminology]
        if len(terms) != len(set(terms)):
            raise ValueError("术语条目不得重复")
        if not any((
            self.research_questions,
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
    serialized = json.dumps(memory.model_dump(), ensure_ascii=False)
    if len(serialized) > max_chars:
        serialized = serialized[: max(0, max_chars - 20)] + "……[已按长度上限截断]"
    return "【已批准项目记忆】\n" + serialized
