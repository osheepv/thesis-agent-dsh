"""跨天断点续作的用户工作区状态模型。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


WorkspaceTab = Literal[
    "refs", "memory", "evidence", "research",
    "writing", "jobs", "notes", "graph",
]
WorkspaceItem = Annotated[str, Field(min_length=1, max_length=100)]


class WorkspaceState(BaseModel):
    """只描述UI工作位置，不参与FSM和产物验收。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    last_task_id: str = Field(default="", max_length=80)
    active_tab: WorkspaceTab = "refs"
    expanded_items: list[WorkspaceItem] = Field(default_factory=list, max_length=30)
    editor_anchor: str = Field(default="", max_length=200)
    updated_at: str = ""


def validate_workspace_state(value: dict) -> WorkspaceState:
    try:
        return WorkspaceState.model_validate(value)
    except ValidationError as exc:
        issues = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors(include_input=False)[:6]
        )
        raise ValueError(f"工作区状态校验失败: {issues}") from exc
