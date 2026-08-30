"""分节生成、版本、审批和汇编能力，以及作者私有自动草稿。"""

from .draft_store import (
    AutosaveDraft,
    AutosaveDraftError,
    AutosaveDraftRevisionConflict,
    AutosaveDraftStore,
    DRAFT_OBJECT_TYPES,
    content_hash_of,
    draft_key_for,
    validate_draft_key,
)
from .generator import SectionDraftGenerator, SectionGeneration
from .models import SectionDraft, SectionDraftStatus
from .registry import SectionDraftRegistry, SectionDraftRegistryError

__all__ = [
    "AutosaveDraft",
    "AutosaveDraftError",
    "AutosaveDraftRevisionConflict",
    "AutosaveDraftStore",
    "DRAFT_OBJECT_TYPES",
    "SectionDraft",
    "SectionDraftGenerator",
    "SectionDraftRegistry",
    "SectionDraftRegistryError",
    "SectionDraftStatus",
    "SectionGeneration",
    "content_hash_of",
    "draft_key_for",
    "validate_draft_key",
]
