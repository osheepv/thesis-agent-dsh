"""版本化论文产物与审批底座。"""

from .models import (
    ApprovalDecision,
    Artifact,
    ArtifactKind,
    ArtifactStatus,
    ContextManifest,
)
from .registry import ArtifactRegistry, ArtifactRegistryError
from .projector import ArtifactOutboxProjector

__all__ = [
    "ApprovalDecision",
    "Artifact",
    "ArtifactKind",
    "ArtifactRegistry",
    "ArtifactRegistryError",
    "ArtifactOutboxProjector",
    "ArtifactStatus",
    "ContextManifest",
]
