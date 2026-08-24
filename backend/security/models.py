"""认证主体与租户角色。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class UserRole(str, Enum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    username: str
    role: UserRole
    session_id: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["role"] = self.role.value
        return value
