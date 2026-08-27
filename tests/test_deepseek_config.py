"""DeepSeek运行时配置不得泄露密钥或混入其他Provider。"""

from application.main import build_app
from application.service.uc_main_orchestration import MainOrchestration
from common import llm
from common.llm import LLMSettings
from fastapi.testclient import TestClient


def test_runtime_config_is_deepseek_only_and_never_echoes_key(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_llm_settings",
        LLMSettings(
            api_key="existing-test-secret",
            model="deepseek-v4-flash",
            supports_tools=True,
        ),
    )
    monkeypatch.setattr(llm, "_client", object())

    public = llm.configure_deepseek_provider({
        "api_key": "replacement-test-secret",
        "model": "deepseek-v4-pro",
        "supports_tools": True,
        "supports_vision": False,
    })

    assert public["provider"] == "deepseek"
    assert public["model"] == "deepseek-v4-pro"
    assert public["api_key_configured"] is True
    assert "replacement-test-secret" not in str(public)
    assert llm.get_llm_settings().api_key == "replacement-test-secret"
    assert llm._client is None  # noqa: SLF001 - 配置变化必须重建客户端
    assert {item["model"] for item in llm.deepseek_model_presets()} == {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp",
    }
    vision = next(
        item for item in llm.deepseek_model_presets()
        if item["model"] == "deepseek-v4-flash-vision-exp"
    )
    assert vision["tools"] is True
    assert vision["vision"] is True


def test_blank_key_preserves_existing_and_invalid_url_is_rejected(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_llm_settings",
        LLMSettings(api_key="keep-test-secret", enabled=True),
    )

    public = llm.configure_deepseek_provider({
        "api_key": "",
        "model": "deepseek-v4-pro",
    })
    assert public["api_key_configured"] is True
    assert llm.get_llm_settings().api_key == "keep-test-secret"

    try:
        llm.configure_deepseek_provider({"base_url": "https://user:pass@example.com?q=x"})
    except ValueError as exc:
        assert "不得包含凭据" in str(exc)
    else:
        raise AssertionError("带凭据或查询参数的Base URL必须拒绝")


def test_deepseek_config_api_returns_safe_runtime_metadata(monkeypatch):
    monkeypatch.setenv("THESIS_JOB_WORKER_ENABLED", "false")
    monkeypatch.setattr(
        llm,
        "_llm_settings",
        LLMSettings(api_key="api-test-secret", enabled=True),
    )
    app = build_app(orchestration=MainOrchestration())
    client = TestClient(app)

    fetched = client.get("/api/v1/console/provider/deepseek").json()
    updated = client.post(
        "/api/v1/console/provider/deepseek",
        json={"model": "deepseek-v4-pro", "api_key": ""},
    ).json()

    assert fetched["code"] == 0
    assert fetched["data"]["config"]["provider"] == "deepseek"
    assert updated["code"] == 0
    assert updated["data"]["config"]["model"] == "deepseek-v4-pro"
    assert "api-test-secret" not in str(fetched)
    assert "api-test-secret" not in str(updated)
