"""有界、只读的环内工具调用循环。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolLoopError(RuntimeError):
    """工具协议、权限或收敛边界被违反。"""

    def __init__(
        self,
        message: str,
        *,
        trace: list[dict[str, Any]] | None = None,
        turns: int = 0,
        tool_call_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.trace = list(trace or [])
        self.turns = turns
        self.tool_call_count = tool_call_count


class AgentLoopSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="THESIS_AGENT_LOOP_", env_file=".env", extra="ignore"
    )

    enabled: bool = False
    max_turns: int = Field(default=6, ge=1, le=8)
    max_tool_calls: int = Field(default=12, ge=1, le=32)
    max_observation_chars: int = Field(default=4000, ge=256, le=16_000)
    max_output_tokens: int = Field(default=2048, ge=256, le=8192)


@dataclass(frozen=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelTurn:
    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()


@dataclass(frozen=True)
class ReadOnlyTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolLoopOutcome:
    content: str
    turns: int
    tool_call_count: int
    trace: list[dict[str, Any]] = field(default_factory=list)


class BoundedToolLoop:
    """模型只能调用注册的只读工具，并在固定轮数内返回最终内容。"""

    def __init__(
        self,
        complete: Callable[[list[dict[str, Any]], list[dict[str, Any]], int], ModelTurn],
        settings: AgentLoopSettings,
    ) -> None:
        self._complete = complete
        self._settings = settings

    def run(
        self,
        *,
        system: str,
        prompt: str,
        tools: list[ReadOnlyTool],
        require_tool_call: bool = False,
    ) -> ToolLoopOutcome:
        if not tools:
            raise ToolLoopError("Agent Loop至少需要一个已注册工具")
        registry = {tool.name: tool for tool in tools}
        if len(registry) != len(tools):
            raise ToolLoopError("工具名称重复")
        schemas = [tool.schema() for tool in tools]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        fingerprints: Counter[str] = Counter()
        cached_results: dict[str, Any] = {}
        trace: list[dict[str, Any]] = []
        total_calls = 0

        for turn_no in range(1, self._settings.max_turns + 1):
            turn = self._complete(
                messages,
                schemas,
                self._settings.max_output_tokens,
            )
            if not turn.tool_calls:
                if not turn.content.strip():
                    raise ToolLoopError("模型既未调用工具也未返回最终内容")
                if require_tool_call and total_calls == 0:
                    raise ToolLoopError("该任务要求至少调用一次只读工具")
                return ToolLoopOutcome(
                    content=turn.content,
                    turns=turn_no,
                    tool_call_count=total_calls,
                    trace=trace,
                )

            assistant_calls = []
            for call in turn.tool_calls:
                assistant_calls.append({
                    "id": call.call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                })
            messages.append({
                "role": "assistant",
                "content": turn.content or None,
                "tool_calls": assistant_calls,
            })

            for call in turn.tool_calls:
                total_calls += 1
                if total_calls > self._settings.max_tool_calls:
                    tool_names = [item.get("tool", "") for item in trace]
                    tool_names.append(call.name)
                    raise ToolLoopError(
                        f"工具调用次数超过上限; tools={tool_names}",
                        trace=trace,
                        turns=turn_no,
                        tool_call_count=total_calls,
                    )
                tool = registry.get(call.name)
                if tool is None:
                    raise ToolLoopError(f"模型请求了未注册工具: {call.name}")
                try:
                    arguments = json.loads(call.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise ToolLoopError(f"工具 {call.name} 参数不是合法JSON") from exc
                if not isinstance(arguments, dict):
                    raise ToolLoopError(f"工具 {call.name} 参数必须是JSON对象")
                try:
                    _validate_schema(arguments, tool.parameters)
                except ValueError as exc:
                    raise ToolLoopError(
                        f"工具 {call.name} 参数校验失败: {exc}"
                    ) from exc
                fingerprint = f"{call.name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
                fingerprints[fingerprint] += 1
                cached = fingerprints[fingerprint] == 2
                if fingerprints[fingerprint] > 2:
                    raise ToolLoopError(
                        f"检测到持续重复工具动作: {call.name}",
                        trace=trace,
                        turns=turn_no,
                        tool_call_count=total_calls,
                    )
                if cached:
                    original = cached_results[fingerprint]
                    if isinstance(original, dict):
                        result = {
                            **original,
                            "_agent_notice": "重复只读调用已使用缓存结果；请立即继续或返回最终结果。",
                        }
                    else:
                        result = {
                            "cached_result": original,
                            "_agent_notice": "重复只读调用已使用缓存结果。",
                        }
                else:
                    try:
                        result = tool.handler(arguments)
                    except Exception as exc:  # noqa: BLE001
                        raise ToolLoopError(f"工具 {call.name} 执行失败: {exc}") from exc
                    cached_results[fingerprint] = result
                observation = json.dumps(result, ensure_ascii=False, default=str)
                truncated = len(observation) > self._settings.max_observation_chars
                if truncated:
                    observation = observation[: self._settings.max_observation_chars]
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": observation,
                })
                trace.append({
                    "turn": turn_no,
                    "tool": call.name,
                    "observation_chars": len(observation),
                    "truncated": truncated,
                    "cached": cached,
                })

        tool_names = [item.get("tool", "") for item in trace]
        raise ToolLoopError(
            f"Agent Loop在 {self._settings.max_turns} 轮内未收敛; "
            f"tools={tool_names}",
            trace=trace,
            turns=self._settings.max_turns,
            tool_call_count=total_calls,
        )


def _validate_schema(value: Any, schema: dict[str, Any], path: str = "args") -> None:
    """校验本项目工具使用的JSON Schema子集，替代供应商Beta strict模式。"""
    expected = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    if expected in type_checks and not type_checks[expected](value):
        raise ValueError(f"{path}应为{expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}不在允许枚举中")
    if expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path}低于minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path}超过maximum")
    if expected == "object":
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ValueError(f"{path}缺少字段: {missing}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ValueError(f"{path}包含多余字段: {extras}")
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], f"{path}.{key}")
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")
