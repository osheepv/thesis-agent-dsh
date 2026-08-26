# -*- coding: utf-8 -*-
"""全局配置（pydantic-settings）。

默认使用本地SQLite，可通过环境变量切换PostgreSQL。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。"""

    model_config = SettingsConfigDict(env_prefix="THESIS_", env_file=".env", extra="ignore")

    app_name: str = "thesis-agent-dsh"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ---- 数据库 ----
    db_url: str = "sqlite:///thesis.db"
    # 全文检索 / 生成列已由 DDL 承载，此处不重复配置。

    # ---- 环节超时 / 重试 覆盖 ----
    http_timeout: int = 30
    retry_max: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
