# -*- coding: utf-8 -*-
"""LLM 接入层（DeepSeek 直调，二期决策 D1）。

设计要点：
    1. 基于 openai SDK 直调 `api.deepseek.com`（OpenAI 兼容），不引入 LangChain 等重框架。
    2. 仅请求 JSON 结构化输出（response_format=json_object + 提示词要求），由调用方
       用 Pydantic 模型校验；校验失败可重试。
    3. 通过 :class:`LLMSettings`（env 前缀 ``THESIS_DEEPSEEK_``）配置 API key /
       base_url / model；key 缺失或调用失败时，由使用方决定回退（mock 生成器）。

注意：DeepSeek 新模型名以 ``deepseek-v4-*`` 为准，旧别名 ``deepseek-chat`` 已退役。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("thesis.llm")

#: DeepSeek 默认接入参数
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-v4-flash"

#: 请求默认超时（秒）与最大重试次数
_DEFAULT_TIMEOUT: float = 120.0
_DEFAULT_RETRY: int = 2


class LLMSettings(BaseSettings):
    """LLM 接入配置（env 前缀 THESIS_DEEPSEEK_，.env 文件生效）。"""

    model_config = SettingsConfigDict(
        env_prefix="THESIS_DEEPSEEK_", env_file=".env", extra="ignore"
    )

    #: API Key（必填；缺失时视为未配置，调用方应回退）
    api_key: str = Field(default="")
    #: 服务地址（默认 DeepSeek 官方）
    base_url: str = Field(default=_DEFAULT_BASE_URL)
    #: 模型名（DeepSeek V4 系列；deepseek-chat 已退役勿用）
    model: str = Field(default=_DEFAULT_MODEL)
    #: 是否启用（false 时直接回退，不发请求；测试/无 key 场景）
    enabled: bool = Field(default=True)
    #: 请求超时（秒）
    timeout: float = Field(default=_DEFAULT_TIMEOUT)
    #: 失败重试次数
    retry_max: int = Field(default=_DEFAULT_RETRY)
    #: LLM 不可用时是否回退确定性 Mock；正式默认关闭，测试/演示需显式开启
    fallback_to_mock: bool = Field(default=False)


def _load_settings() -> LLMSettings:
    """从 .env / 环境变量读取 LLM 配置。"""
    try:
        settings = LLMSettings()
        # 兼容 config.py 的 THESIS_DEEPSEEK_API_KEY 已在 LLMSettings 内处理
        return settings
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 LLM 配置失败，使用默认（可能未配置 API key）: %s", exc)
        return LLMSettings(enabled=False)


#: 模块级单例（惰性读取 .env，避免重复解析）
_llm_settings: Optional[LLMSettings] = None


def get_llm_settings() -> LLMSettings:
    """读取 LLM 配置单例。"""
    global _llm_settings
    if _llm_settings is None:
        _llm_settings = _load_settings()
    return _llm_settings


class LLMError(Exception):
    """LLM 调用/校验失败（业务层应捕获并决定回退）。"""


class StructuredOutputError(LLMError):
    """LLM 返回内容无法解析为 JSON / 不符合目标结构。"""


class LLMClient:
    """DeepSeek JSON 结构化输出客户端（轻量封装）。

    Usage::

        client = LLMClient()
        data = client.generate_json(
            system="你是学术选题助手",
            prompt="...",  # 需包含 "json" 要求与示例
            model=JSONModel,
        )
    """

    def __init__(self, settings: Optional[LLMSettings] = None) -> None:
        self._settings = settings or get_llm_settings()
        self._client: Optional[Any] = None

    # ------------------------------------------------------------------
    # 对外：结构化 JSON 调用
    # ------------------------------------------------------------------
    def generate_json(
        self,
        system: str,
        prompt: str,
        model_cls: type[BaseModel],
        temperature: float = 0.6,
        retry: Optional[int] = None,
    ) -> BaseModel:
        """调用 DeepSeek 并返回 Pydantic 模型实例。

        Args:
            system: 系统提示词。
            prompt: 用户提示词（必须包含 "json"/"JSON" 字样和输出示例，接口要求）。
            model_cls: 目标 Pydantic 模型（用于校验返回）。
            temperature: 采样温度。
            retry: 失败重试次数（None 用配置默认）。

        Raises:
            LLMError: 未配置 key / 网络失败。
            StructuredOutputError: 返回内容无法解析 / 校验失败（可重试）。
        """
        if not self._settings.enabled or not self._settings.api_key:
            raise LLMError("LLM 未配置（缺少 API key 或已禁用），请回退 Mock")
        retry_n = self._settings.retry_max if retry is None else retry

        last_err: Optional[Exception] = None
        for attempt in range(retry_n + 1):
            try:
                text = self._chat(system=system, prompt=prompt, temperature=temperature)
                return self._parse_json(text, model_cls)
            except StructuredOutputError as exc:
                last_err = exc
                # 结构化失败可重试（改温度或重发）；网络类由 _chat 内部重试
                if attempt < retry_n:
                    logger.warning("LLM 结构化解析失败第 %s 次: %s", attempt + 1, exc)
                    continue
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < retry_n:
                    continue
        raise StructuredOutputError(f"LLM 返回多次无法解析: {last_err}")

    # ------------------------------------------------------------------
    # 内部：HTTP 调用 + JSON 解析
    # ------------------------------------------------------------------
    def _chat(self, system: str, prompt: str, temperature: float) -> str:
        """单次 chat 调用（带网络层重试）。"""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                timeout=self._settings.timeout,
            )

        # 网络层重试（连接/超时/5xx）
        last_exc: Optional[Exception] = None
        for _ in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._settings.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    max_tokens=4096,
                )
                content = resp.choices[0].message.content
                if not content:
                    raise LLMError("LLM 返回空内容")
                return content
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("LLM 调用失败（重试前）: %s", exc)
                continue
        raise LLMError(f"LLM 调用失败: {last_exc}")

    @staticmethod
    def _parse_json(text: str, model_cls: type[BaseModel]) -> BaseModel:
        """解析 LLM 返回文本为 JSON 并校验为目标模型。"""
        # 容错：剥离可能出现的 markdown 代码围栏
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"返回非合法 JSON: {exc}") from exc
        try:
            return model_cls.model_validate(obj)
        except Exception as exc:  # noqa: BLE001
            raise StructuredOutputError(f"JSON 结构不符合 {model_cls.__name__}: {exc}") from exc


#: 模块级单例供执行体复用
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例。"""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def llm_available() -> bool:
    """LLM 是否可用（已配置 key 且启用）。"""
    s = get_llm_settings()
    return bool(s.enabled and s.api_key)
