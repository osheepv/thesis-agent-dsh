# -*- coding: utf-8 -*-
"""DeepSeek接口接入层。

设计要点：
    1. 基于openai SDK连接用户配置的DeepSeek兼容端点。
    2. 仅请求 JSON 结构化输出（response_format=json_object + 提示词要求），由调用方
       用 Pydantic 模型校验；校验失败可重试。
    3. 使用``THESIS_DEEPSEEK_*``配置；运行时可切换DeepSeek模型和能力。
    4. 多Provider抽象留到后续阶段，本期不暴露OpenAI/Ollama等接口。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("thesis.llm")

#: DeepSeek默认接入参数
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-v4-flash"

#: 请求默认超时（秒）与最大重试次数
_DEFAULT_TIMEOUT: float = 120.0
_DEFAULT_RETRY: int = 2


class LLMSettings(BaseSettings):
    """DeepSeek配置（环境变量前缀``THESIS_DEEPSEEK_``）。"""

    model_config = SettingsConfigDict(
        env_prefix="THESIS_DEEPSEEK_", env_file=".env", extra="ignore"
    )

    api_key: str = Field(default="")
    base_url: str = Field(default=_DEFAULT_BASE_URL)
    model: str = Field(default=_DEFAULT_MODEL)
    #: 是否启用（false 时直接回退，不发请求；测试/无 key 场景）
    enabled: bool = Field(default=True)
    #: 请求超时（秒）
    timeout: float = Field(default=_DEFAULT_TIMEOUT)
    #: 失败重试次数
    retry_max: int = Field(default=_DEFAULT_RETRY)
    #: LLM 不可用时是否回退确定性 Mock；正式默认关闭，测试/演示需显式开启
    fallback_to_mock: bool = Field(default=False)
    #: 结构化写作默认关闭思考模式，避免推理Token耗尽后最终JSON为空。
    thinking_mode: Literal["enabled", "disabled"] = Field(default="disabled")
    #: 显式启用思考模式时的推理强度。
    reasoning_effort: Literal["low", "high", "max"] = Field(default="low")
    supports_tools: bool = Field(default=True)
    supports_vision: bool = Field(default=False)

    def is_available(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model)

    def public_view(self) -> dict[str, Any]:
        return {
            "provider": "deepseek",
            "base_url": self.base_url,
            "model": self.model,
            "enabled": self.enabled,
            "api_key_configured": bool(self.api_key),
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "capabilities": {
                "json_output": True,
                "tools": self.supports_tools,
                "thinking": True,
                "vision": self.supports_vision,
                "streaming": True,
            },
            "runtime_only": True,
        }


def _load_settings() -> LLMSettings:
    """从环境变量或.env读取DeepSeek配置。"""
    try:
        return _validated_settings(LLMSettings())
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 LLM 配置失败，使用默认（可能未配置 API key）: %s", exc)
        return LLMSettings(enabled=False)


def _validated_settings(settings: LLMSettings) -> LLMSettings:
    """拒绝可能在公开元数据中泄露凭据的URL。"""
    if settings.base_url:
        parsed = urlparse(settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LLM base_url必须是http/https URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("LLM base_url不得包含凭据、查询参数或片段")
    settings.base_url = settings.base_url.rstrip("/")
    settings.model = settings.model.strip()
    return settings


#: 模块级单例（惰性读取 .env，避免重复解析）
_llm_settings: Optional[LLMSettings] = None


def get_llm_settings() -> LLMSettings:
    """读取 LLM 配置单例。"""
    global _llm_settings
    if _llm_settings is None:
        _llm_settings = _load_settings()
    return _llm_settings


def deepseek_model_presets() -> list[dict[str, Any]]:
    return [
        {"model": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "tools": True, "vision": False},
        {"model": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "tools": True, "vision": False},
        {"model": "deepseek-v4-flash-vision-exp", "label": "DeepSeek V4 Vision Exp", "tools": True, "vision": True},
    ]


def configure_deepseek_provider(value: dict[str, Any]) -> dict[str, Any]:
    """进程内切换DeepSeek模型；API Key不回显、不写磁盘。"""
    global _llm_settings, _client

    current = get_llm_settings()
    data = current.model_dump()
    for key in (
        "base_url", "model", "enabled",
        "timeout", "retry_max", "fallback_to_mock", "thinking_mode",
        "reasoning_effort", "supports_tools", "supports_vision",
    ):
        if key in value:
            data[key] = value[key]
    if value.get("clear_api_key") is True:
        data["api_key"] = ""
    elif str(value.get("api_key", "")).strip():
        data["api_key"] = str(value["api_key"]).strip()
    settings = _validated_settings(LLMSettings(**data))
    if settings.enabled:
        if not settings.base_url or not settings.model or not settings.api_key:
            raise ValueError("启用DeepSeek时Base URL、模型名和API Key不能为空")
    _llm_settings = settings
    _client = None
    return settings.public_view()


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
        max_output_tokens: int = 4096,
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
                text = self._chat(
                    system=system,
                    prompt=prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                return self._parse_json(text, model_cls)
            except Exception as exc:  # cooperative cancellation/budget must not be retried
                from jobs.registry import JobBudgetExceededError, JobCancelledError

                if isinstance(exc, (JobBudgetExceededError, JobCancelledError)):
                    raise
                if isinstance(exc, StructuredOutputError):
                    last_err = exc
                    if attempt < retry_n:
                        logger.warning("LLM 结构化解析失败第 %s 次: %s", attempt + 1, exc)
                        continue
                elif isinstance(exc, LLMError):
                    raise
                else:
                    last_err = exc
                    if attempt < retry_n:
                        continue
        raise StructuredOutputError(f"LLM 返回多次无法解析: {last_err}")

    # ------------------------------------------------------------------
    # 内部：HTTP 调用 + JSON 解析
    # ------------------------------------------------------------------
    def _chat(
        self,
        system: str,
        prompt: str,
        temperature: float,
        max_output_tokens: int = 4096,
    ) -> str:
        """单次 chat 调用（带网络层重试）。"""
        from jobs.runtime import get_current_job_runtime
        from jobs.registry import JobBudgetExceededError, JobCancelledError

        runtime = get_current_job_runtime()
        estimated_input_tokens = max(1, (len(system) + len(prompt) + 3) // 4)
        max_output_tokens = max(256, int(max_output_tokens))
        if runtime is not None:
            runtime.before_llm(estimated_input_tokens, max_output_tokens)
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
                request: dict[str, Any] = {
                    "model": self._settings.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": temperature,
                    "max_tokens": max_output_tokens,
                    "extra_body": {
                        "thinking": {"type": self._settings.thinking_mode}
                    },
                }
                if self._settings.thinking_mode == "enabled":
                    request["reasoning_effort"] = self._settings.reasoning_effort
                resp = self._client.chat.completions.create(**request)
                choice = resp.choices[0]
                message = choice.message
                content = getattr(message, "content", "") or ""
                reasoning_content = getattr(message, "reasoning_content", "") or ""
                finish_reason = getattr(choice, "finish_reason", None)
                if runtime is not None:
                    usage = getattr(resp, "usage", None)
                    input_tokens = int(
                        getattr(usage, "prompt_tokens", 0) or estimated_input_tokens
                    )
                    output_tokens = int(
                        getattr(usage, "completion_tokens", 0)
                        or max(1, (len(content) + 3) // 4)
                    )
                    runtime.record_llm_usage(input_tokens, output_tokens)
                if not content:
                    usage = getattr(resp, "usage", None)
                    completion_tokens = int(
                        getattr(usage, "completion_tokens", 0) or 0
                    )
                    raise LLMError(
                        "LLM 返回空内容 "
                        f"(finish_reason={finish_reason or 'unknown'}, "
                        f"reasoning_chars={len(reasoning_content)}, "
                        f"completion_tokens={completion_tokens}, "
                        f"thinking_mode={self._settings.thinking_mode})"
                    )
                if finish_reason not in (None, "stop"):
                    logger.warning(
                        "LLM 非正常结束: finish_reason=%s content_chars=%s thinking_mode=%s",
                        finish_reason,
                        len(content),
                        self._settings.thinking_mode,
                    )
                return content
            except (JobBudgetExceededError, JobCancelledError):
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("LLM 调用失败（重试前）: %s", exc)
                continue
        raise LLMError(f"LLM 调用失败: {last_exc}")

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int = 2048,
    ):
        """执行一轮非思考模式工具调用，返回统一ModelTurn。"""
        from common.agent_loop import ModelToolCall, ModelTurn
        from jobs.registry import JobBudgetExceededError, JobCancelledError
        from jobs.runtime import get_current_job_runtime

        if not self._settings.enabled or not self._settings.api_key:
            raise LLMError("LLM 未配置（缺少 API key 或已禁用）")
        if not self._settings.supports_tools:
            raise LLMError(
                f"当前DeepSeek模型 {self._settings.model} 未声明Tools能力"
            )
        runtime = get_current_job_runtime()
        serialized = json.dumps(messages, ensure_ascii=False, default=str)
        estimated_input_tokens = max(1, (len(serialized) + 3) // 4)
        max_output_tokens = max(256, int(max_output_tokens))
        if runtime is not None:
            runtime.before_llm(estimated_input_tokens, max_output_tokens)
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                timeout=self._settings.timeout,
            )

        last_exc: Optional[Exception] = None
        for _ in range(2):
            try:
                response = self._client.chat.completions.create(
                    model=self._settings.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.2,
                    max_tokens=max_output_tokens,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                choice = response.choices[0]
                message = choice.message
                content = getattr(message, "content", "") or ""
                raw_calls = getattr(message, "tool_calls", None) or []
                calls = tuple(
                    ModelToolCall(
                        call_id=str(getattr(call, "id", "")),
                        name=str(getattr(getattr(call, "function", None), "name", "")),
                        arguments=str(
                            getattr(getattr(call, "function", None), "arguments", "{}")
                            or "{}"
                        ),
                    )
                    for call in raw_calls
                )
                if runtime is not None:
                    usage = getattr(response, "usage", None)
                    runtime.record_llm_usage(
                        int(getattr(usage, "prompt_tokens", 0) or estimated_input_tokens),
                        int(
                            getattr(usage, "completion_tokens", 0)
                            or max(1, (len(content) + 3) // 4)
                        ),
                    )
                if not content and not calls:
                    raise LLMError(
                        "工具调用轮次返回空内容且无tool_calls "
                        f"(finish_reason={getattr(choice, 'finish_reason', None) or 'unknown'})"
                    )
                return ModelTurn(content=content, tool_calls=calls)
            except (JobBudgetExceededError, JobCancelledError):
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("LLM 工具调用失败（重试前）: %s", exc)
        raise LLMError(f"LLM 工具调用失败: {last_exc}")

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
    return s.is_available()
