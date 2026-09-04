"""研究设计、实验执行与结果血缘模型。"""

from .models import (
    ExperimentRun,
    ExperimentStatus,
    ResearchMethod,
    ResearchProtocol,
    ResultRecord,
)
from .registry import ResearchExecutionRegistry, ResearchRegistryError
from .argument_map import ArgumentClaimSpec, ArgumentMap, ArgumentRole, EpistemicIntent

__all__ = [
    "ExperimentRun",
    "ExperimentStatus",
    "ArgumentClaimSpec",
    "ArgumentMap",
    "ArgumentRole",
    "EpistemicIntent",
    "ResearchMethod",
    "ResearchProtocol",
    "ResearchExecutionRegistry",
    "ResearchRegistryError",
    "ResultRecord",
]
