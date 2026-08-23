"""跨学科研究实施的最小可信数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ResearchMethod(str, Enum):
    QUANTITATIVE = "QUANTITATIVE"
    QUALITATIVE = "QUALITATIVE"
    MIXED = "MIXED"
    THEORETICAL = "THEORETICAL"
    SYSTEM_BUILD = "SYSTEM_BUILD"
    LITERATURE_REVIEW = "LITERATURE_REVIEW"


class ExperimentStatus(str, Enum):
    PLANNED = "PLANNED"
    MATERIALS_READY = "MATERIALS_READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def _require_nonempty(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} 不能为空")


@dataclass(frozen=True)
class ResearchProtocol:
    """经用户批准后才能用于研究实施的项目手册。"""

    title: str
    method: ResearchMethod
    research_questions: tuple[str, ...]
    procedure_steps: tuple[str, ...]
    analysis_plan: tuple[str, ...]
    required_outputs: tuple[str, ...]
    hypotheses: tuple[str, ...] = ()
    variables: dict[str, str] = field(default_factory=dict)
    materials: tuple[str, ...] = ()
    ethics_requirements: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty("title", self.title)
        if not self.research_questions:
            raise ValueError("research_questions 不能为空")
        if not self.procedure_steps:
            raise ValueError("procedure_steps 不能为空")
        if not self.analysis_plan:
            raise ValueError("analysis_plan 不能为空")
        if not self.required_outputs:
            raise ValueError("required_outputs 不能为空")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["method"] = self.method.value
        return value


@dataclass(frozen=True)
class ExperimentRun:
    """一次真实研究/实验执行及用户提交材料的血缘记录。"""

    run_id: str
    protocol_artifact_id: str
    status: ExperimentStatus
    material_file_ids: tuple[str, ...] = ()
    raw_data_file_ids: tuple[str, ...] = ()
    code_file_ids: tuple[str, ...] = ()
    log_file_ids: tuple[str, ...] = ()
    notes: str = ""
    user_attested: bool = False

    def __post_init__(self) -> None:
        _require_nonempty("run_id", self.run_id)
        _require_nonempty("protocol_artifact_id", self.protocol_artifact_id)
        if self.status == ExperimentStatus.COMPLETED and not self.user_attested:
            raise ValueError("完成的实验必须由用户确认材料真实")
        if self.status == ExperimentStatus.COMPLETED and not (
            self.raw_data_file_ids or self.log_file_ids
        ):
            raise ValueError("完成的实验必须登记原始数据或运行日志")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(frozen=True)
class ResultRecord:
    """可被正文数字或结果主张引用的最小结果记录。"""

    result_id: str
    run_id: str
    metric: str
    value: str
    source_file_id: str
    computation: str
    unit: str = ""
    table_or_figure_id: str = ""
    verified_by_user: bool = False

    def __post_init__(self) -> None:
        for name in ("result_id", "run_id", "metric", "value", "source_file_id", "computation"):
            _require_nonempty(name, str(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
