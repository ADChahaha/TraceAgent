"""模型配置读取（config.toml 与环境变量覆盖）、标题模型回退与传输层装配测试。"""

from __future__ import annotations

import pytest
from service.file_extraction_agent.core import model as model_module
from service.file_extraction_agent.core.model import build_chat_model, load_title_model_config, normalize_model_config
from service.file_extraction_agent.schemas import ModelConfig


def test_normalize_model_config_loads_config_toml_and_ignores_dotenv(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[model]",
                'base_url = "https://example.com/v1"',
                'api_key = "key"',
                'model = "qa"',
                'api_transport = "chat_completions"',
                "temperature = 0.1",
                "top_p = 0.9",
                "top_k = 40",
                'reasoning_effort = "high"',
                "max_retries = 8",
                "request_timeout = 120.0",
                "",
                "[title_model]",
                'model = "qa-mini"',
                "request_timeout = 12.0",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text('MODEL="should-not-be-read"\nOPENAI_API_KEY="bad"\n', encoding="utf-8")
    monkeypatch.setenv("TRACEAGENT_CONFIG", str(config_path))
    monkeypatch.chdir(tmp_path)
    for name in (
        "PROVIDER",
        "BASE_URL",
        "API_KEY",
        "OPENAI_API_KEY",
        "MODEL",
        "MODEL_API_TRANSPORT",
        "TEMPERATURE",
        "TOP_P",
        "TOP_K",
        "REASONING_EFFORT",
        "MODEL_MAX_RETRIES",
        "MODEL_REQUEST_TIMEOUT",
        "TITLE_MODEL",
        "TITLE_BASE_URL",
        "TITLE_OPENAI_API_KEY",
        "TITLE_MODEL_REQUEST_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)

    config = normalize_model_config(None)
    assert config.base_url == "https://example.com/v1"
    assert config.api_key == "key"
    assert config.model_name == "qa"
    assert config.api_transport == "chat_completions"
    assert config.temperature == 0.1
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.reasoning_effort == "high"
    assert config.max_retries == 8
    assert config.request_timeout == 120.0

    title_config = load_title_model_config()
    assert title_config.model_name == "qa-mini"
    assert title_config.request_timeout == 12.0
    assert title_config.base_url == "https://example.com/v1"
    assert title_config.api_key == "key"

    empty_title_cfg = tmp_path / "empty-title.toml"
    empty_title_cfg.write_text(
        "\n".join(
            [
                "[model]",
                'base_url = "https://example.com/v1"',
                'api_key = "key"',
                'model = "qa"',
                'api_transport = "chat_completions"',
                "",
                "[title_model]",
                'base_url = ""',
                'api_key = ""',
                'model = ""',
                'api_transport = ""',
            ]
        ),
        encoding="utf-8",
    )
    fallback_title = load_title_model_config(empty_title_cfg)
    assert fallback_title.base_url == "https://example.com/v1"
    assert fallback_title.api_key == "key"
    assert fallback_title.model_name == "qa"
    assert fallback_title.api_transport == "chat_completions"

    monkeypatch.setenv("MODEL", "qa-from-env")
    assert normalize_model_config(None).model_name == "qa-from-env"


def test_build_chat_model_builds_responses_transport_by_default(monkeypatch):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_module, "_chat_model_class", lambda: FakeChatOpenAI)
    model = build_chat_model(
        ModelConfig(base_url="https://example.com/v1", api_key="key", model_name="qa"), "qa"
    )
    assert model.use_stream is True
    assert isinstance(model.model, FakeChatOpenAI)
    assert [kwargs["use_responses_api"] for kwargs in captured] == [True]
    assert [kwargs["streaming"] for kwargs in captured] == [True]
    assert [kwargs["timeout"] for kwargs in captured] == [8.0]


def test_build_chat_model_builds_chat_completions_transport_when_configured(monkeypatch):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_module, "_chat_model_class", lambda: FakeChatOpenAI)
    model = build_chat_model(
        ModelConfig(
            base_url="https://example.com/v1",
            api_key="key",
            model_name="qa",
            api_transport="chat_completions",
        ),
        "qa",
    )
    assert model.use_stream is True
    assert isinstance(model.model, FakeChatOpenAI)
    assert [kwargs["use_responses_api"] for kwargs in captured] == [False]
    assert [kwargs["streaming"] for kwargs in captured] == [True]


def test_build_chat_model_rejects_unknown_transport():
    with pytest.raises(ValueError, match="MODEL_API_TRANSPORT"):
        build_chat_model(ModelConfig(model_name="qa", api_transport="auto"), "qa")


def test_normalize_model_config_rejects_untyped_dict_input():
    with pytest.raises(TypeError, match="unexpected model config type"):
        normalize_model_config({"model": "qa"})
