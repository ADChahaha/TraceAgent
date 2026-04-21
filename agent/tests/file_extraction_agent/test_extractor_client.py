from __future__ import annotations

import json

from pydantic import BaseModel

from file_extraction_agent import extractor_client as extractor_client_module


class DummyOutput(BaseModel):
    answer: str


def test_build_extractor_client_from_env_requires_all_runtime_variables(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL", raising=False)

    try:
        extractor_client_module.build_extractor_client_from_env()
    except extractor_client_module.ExtractorClientConfigError as exc:
        message = str(exc)
        assert "BASE_URL" in message
        assert "OPENAI_API_KEY" in message
        assert "MODEL" in message
    else:
        raise AssertionError("缺少环境变量时应拒绝构造 extractor client")


def test_build_extractor_client_from_env_uses_json_schema_strategy_from_config(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "model_client_config.json"
    config_path.write_text(
        json.dumps(
            {
                "request_options": {"temperature": 0},
            }
        ),
        encoding="utf-8",
    )

    created_kwargs: dict[str, object] = {}

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            return self.schema(answer=payload["messages"][-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

        def with_structured_output(self, schema, *, method, strict):
            assert method == "json_schema"
            assert strict is True
            return FakeRunnable(schema)

    monkeypatch.setenv("BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL", "gpt-compatible")
    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client_from_env(
        config_path=config_path,
        structured_output_strategy="json_schema",
    )
    result = client.invoke(
        output_schema=DummyOutput,
        messages=[{"role": "user", "content": "可调用"}],
    )

    assert created_kwargs["base_url"] == "https://llm.example.com/v1"
    assert created_kwargs["api_key"] == "test-key"
    assert created_kwargs["model"] == "gpt-compatible"
    assert created_kwargs["temperature"] == 0
    assert client.structured_output_strategy == "json_schema"
    assert result.answer == "可调用"


def test_build_extractor_client_from_env_uses_tool_call_strategy_from_config(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "model_client_config.json"
    config_path.write_text(
        json.dumps({"request_options": {"temperature": 0}}),
        encoding="utf-8",
    )

    seen_methods: list[tuple[str, bool | None]] = []

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            return self.schema(answer=payload["messages"][-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            seen_methods.append((method, strict))
            return FakeRunnable(schema)

    monkeypatch.setenv("BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL", "gpt-compatible")
    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client_from_env(
        config_path=config_path,
        structured_output_strategy="tool_call",
    )
    result = client.invoke(
        output_schema=DummyOutput,
        messages=[{"role": "user", "content": "tool"}],
    )

    assert client.structured_output_strategy == "tool_call"
    assert seen_methods == [("function_calling", True)]
    assert result.answer == "tool"


def test_build_extractor_client_from_env_falls_back_to_tool_call_when_json_schema_is_unsupported(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "model_client_config.json"
    config_path.write_text(
        json.dumps({"request_options": {"temperature": 0}}),
        encoding="utf-8",
    )

    seen_methods: list[tuple[str, bool | None]] = []

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            return self.schema(answer=payload["messages"][-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            seen_methods.append((method, strict))
            if method == "json_schema":
                raise RuntimeError("json_schema unsupported")
            return FakeRunnable(schema)

    monkeypatch.setenv("BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL", "gpt-compatible")
    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client_from_env(
        config_path=config_path,
        structured_output_strategy="auto",
    )
    result = client.invoke(
        output_schema=DummyOutput,
        messages=[{"role": "user", "content": "fallback"}],
    )

    assert client.structured_output_strategy == "auto"
    assert seen_methods == [("json_schema", True), ("function_calling", True)]
    assert result.answer == "fallback"


def test_build_extractor_client_from_env_rejects_unknown_structured_output_strategy_argument(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "model_client_config.json"
    config_path.write_text(
        json.dumps({"request_options": {"temperature": 0}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MODEL", "gpt-compatible")

    try:
        extractor_client_module.build_extractor_client_from_env(
            config_path=config_path,
            structured_output_strategy="unsupported",  # type: ignore[arg-type]
        )
    except extractor_client_module.ExtractorClientConfigError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("未知 structured output 策略应被拒绝")
