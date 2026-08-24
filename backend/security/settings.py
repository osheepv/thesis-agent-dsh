"""安全配置；生产启用时使用 fail-closed 默认。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class SecuritySettings:
    enabled: bool
    db_path: str
    bootstrap_token: str
    cookie_name: str
    cookie_secure: bool
    session_hours: int
    idle_minutes: int

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        return cls(
            enabled=_bool("THESIS_AUTH_ENABLED", False),
            db_path=os.getenv("THESIS_SECURITY_DB", "security.db"),
            bootstrap_token=os.getenv("THESIS_AUTH_BOOTSTRAP_TOKEN", ""),
            cookie_name=os.getenv("THESIS_AUTH_COOKIE_NAME", "thesis_session"),
            cookie_secure=_bool("THESIS_AUTH_COOKIE_SECURE", True),
            session_hours=max(1, int(os.getenv("THESIS_AUTH_SESSION_HOURS", "8"))),
            idle_minutes=max(5, int(os.getenv("THESIS_AUTH_IDLE_MINUTES", "30"))),
        )
