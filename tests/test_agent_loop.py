"""有界工具循环与DeepSeek工具协议适配测试。"""

from types import SimpleNamespace

import pytest

from common.agent_loop import (
    AgentLoopSettings,
    BoundedToolLoop,
    ModelToolCall,
    ModelTurn,
    ReadOnlyTool,
    ToolLoopError,
)
from common.llm import LLMClient, LLMSettings


def _tool(handler=lambda args: {"echo": args.get("query", "")}):
    return ReadOnlyTool(
        name="search",
        description="只读检索",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def test_tool_loop_executes_observation_then_returns_final_content():
    seen_messages = []
    turns = iter([
        ModelTurn(tool_calls=(ModelToolCall("call-1", "search", '{"query":"引用"}'),)),
        ModelTurn(content='{"plan":"done"}'),
    ])

    def complete(messages, tools, max_tokens):
        seen_messages.append(list(messages))
        assert tools[0]["function"]["name"] == "search"
        assert max_tokens == 1024
        return next(turns)

    outcome = BoundedToolLoop(
        complete,
        AgentLoopSettings(max_turns=3, max_tool_calls=4, max_output_tokens=1024),
    ).run(system="system", prompt="prompt", tools=[_tool()])

    assert outcome.content == '{"plan":"done"}'
    assert outcome.turns == 2
    assert outcome.tool_call_count == 1
    assert seen_messages[1][-1]["role"] == "tool"
    assert seen_messages[1][-1]["tool_call_id"] == "call-1"


def test_tool_loop_rejects_unknown_and_persistent_repeated_actions():
    unknown = BoundedToolLoop(
        lambda *_: ModelTurn(
            tool_calls=(ModelToolCall("x", "delete_everything", "{}"),)
        ),
        AgentLoopSettings(max_turns=2),
    )
    with pytest.raises(ToolLoopError, match="未注册工具"):
        unknown.run(system="s", prompt="p", tools=[_tool()])

    calls = iter([
        ModelTurn(tool_calls=(ModelToolCall("1", "search", '{"query":"same"}'),)),
        ModelTurn(tool_calls=(ModelToolCall("2", "search", '{"query":"same"}'),)),
        ModelTurn(tool_calls=(ModelToolCall("3", "search", '{"query":"same"}'),)),
    ])
    repeated = BoundedToolLoop(
        lambda *_: next(calls),
        AgentLoopSettings(max_turns=3),
    )
    with pytest.raises(ToolLoopError, match="持续重复工具动作") as repeated_error:
        repeated.run(system="s", prompt="p", tools=[_tool()])
    assert repeated_error.value.trace[1]["cached"] is True

    no_tool = BoundedToolLoop(
        lambda *_: ModelTurn(content="final"),
        AgentLoopSettings(max_turns=2),
    )
    with pytest.raises(ToolLoopError, match="至少调用一次"):
        no_tool.run(
            system="s", prompt="p", tools=[_tool()], require_tool_call=True
        )

    bad_arguments = BoundedToolLoop(
        lambda *_: ModelTurn(tool_calls=(ModelToolCall(
            "bad", "search", '{"query":"ok","unexpected":true}'
        ),)),
        AgentLoopSettings(max_turns=2),
    )
    with pytest.raises(ToolLoopError, match="参数校验失败.*多余字段"):
        bad_arguments.run(system="s", prompt="p", tools=[_tool()])


def test_tool_loop_enforces_turn_limit_and_truncates_observation():
    counter = {"value": 0}

    def complete(*_):
        counter["value"] += 1
        return ModelTurn(tool_calls=(ModelToolCall(
            str(counter["value"]),
            "search",
            f'{{"query":"q{counter["value"]}"}}',
        ),))

    loop = BoundedToolLoop(
        complete,
        AgentLoopSettings(
            max_turns=2,
            max_tool_calls=3,
            max_observation_chars=256,
        ),
    )
    with pytest.raises(ToolLoopError, match="未收敛"):
        loop.run(
            system="s",
            prompt="p",
            tools=[_tool(lambda _: {"text": "x" * 1000})],
        )

    calls = iter([
        ModelTurn(tool_calls=(ModelToolCall("1", "search", '{"query":"q1"}'),)),
        ModelTurn(tool_calls=(ModelToolCall("2", "search", '{"query":"q2"}'),)),
    ])
    with pytest.raises(ToolLoopError) as exc_info:
        BoundedToolLoop(
            lambda *_: next(calls),
            AgentLoopSettings(max_turns=2, max_tool_calls=3),
        ).run(system="s", prompt="p", tools=[_tool()])
    assert exc_info.value.turns == 2
    assert exc_info.value.tool_call_count == 2
    assert [item["tool"] for item in exc_info.value.trace] == ["search", "search"]

    too_many = BoundedToolLoop(
        lambda *_: ModelTurn(tool_calls=(
            ModelToolCall("1", "search", '{"query":"q1"}'),
            ModelToolCall("2", "search", '{"query":"q2"}'),
        )),
        AgentLoopSettings(max_turns=2, max_tool_calls=1),
    )
    with pytest.raises(ToolLoopError) as max_calls:
        too_many.run(system="s", prompt="p", tools=[_tool()])
    assert max_calls.value.turns == 1
    assert max_calls.value.tool_call_count == 2
    assert max_calls.value.trace[0]["tool"] == "search"


def test_llm_client_adapts_openai_tool_calls_and_disables_thinking():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(
                        id="call-1",
                        function=SimpleNamespace(
                            name="search",
                            arguments='{"query":"evidence"}',
                        ),
                    )],
                ),
            )],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
        )

    client = LLMClient(LLMSettings(enabled=True, api_key="test", retry_max=0))
    client._client = SimpleNamespace(  # noqa: SLF001
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    turn = client.complete_with_tools(
        [{"role": "user", "content": "use a tool"}],
        [_tool().schema()],
        512,
    )

    assert turn.tool_calls[0].name == "search"
    assert captured["tool_choice"] == "auto"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "response_format" not in captured
