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
    """只描述UI工作位置，不参与FSM和产物验收。

    revision 是服务端可验证的单调版本：
    - 旧数据缺失时按 0 读取；
    - 客户端每次真实位置变化产生严格递增 revision；
    - 服务端只接受比当前更大的 revision，旧请求不能倒退覆盖新状态。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    last_task_id: str = Field(default="", max_length=80)
    active_tab: WorkspaceTab = "refs"
    expanded_items: list[WorkspaceItem] = Field(default_factory=list, max_length=30)
    editor_anchor: str = Field(default="", max_length=200)
    revision: int = Field(default=0, ge=0)
    updated_at: str = ""


class WorkspaceRevisionConflict(ValueError):
    """工作区 revision 冲突：旧快照或同版本不同内容不得覆盖已保存状态。"""

    def __init__(self, current_revision: int, incoming_revision: int, reason: str) -> None:
        self.current_revision = current_revision
        self.incoming_revision = incoming_revision
        self.reason = reason
        super().__init__(
            f"工作区位置已在其他页面更新（服务端revision {current_revision}，"
            f"请求revision {incoming_revision}：{reason}），已拒绝写入"
        )


def workspace_content(value: dict) -> dict:
    """去掉版本与时间戳后的可比较内容，用于幂等重放判定。"""
    return {
        key: item for key, item in dict(value or {}).items()
        if key not in {"revision", "updated_at"}
    }


def read_revision(value: dict) -> int:
    """宽松读取历史 payload 的 revision，缺失或非法时按 0 处理。"""
    raw = dict(value or {}).get("revision", 0)
    try:
        revision = int(raw)
    except (TypeError, ValueError):
        return 0
    return revision if revision > 0 else 0


def validate_workspace_state(value: dict) -> WorkspaceState:
    try:
        return WorkspaceState.model_validate(value)
    except ValidationError as exc:
        issues = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors(include_input=False)[:6]
        )
        raise ValueError(f"工作区状态校验失败: {issues}") from exc
