from __future__ import annotations

from pydantic import BaseModel

from service.file_extraction_agent import extractor_client as extractor_client_module


class DummyOutput(BaseModel):
    answer: str


def test_build_extractor_client_from_env_requires_all_runtime_variables(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL", raising=False)

    try:
        extractor_client_module.build_extractor_client(
            structured_output_strategy="auto",
        )
    except extractor_client_module.ExtractorClientConfigError as exc:
        message = str(exc)
        assert "base_url" in message
        assert "api_key" in message
        assert "model" not in message
    else:
        raise AssertionError("缺少显式连接参数时应拒绝构造 extractor client")


def test_build_extractor_client_uses_environment_when_arguments_are_omitted(monkeypatch):
    created_kwargs: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    monkeypatch.setenv("BASE_URL", "https://env-llm.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("MODEL", "env-model")
    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        structured_output_strategy="tool_call",
    )

    assert created_kwargs["base_url"] == "https://env-llm.example.com/v1"
    assert created_kwargs["api_key"] == "env-key"
    assert created_kwargs["model"] == "env-model"
    assert client.base_url == "https://env-llm.example.com/v1"
    assert client.model_name == "env-model"


def test_build_extractor_client_defaults_model_when_env_model_is_omitted(monkeypatch):
    created_kwargs: dict[str, object] = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    monkeypatch.setenv("BASE_URL", "https://env-llm.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        structured_output_strategy="auto",
    )

    assert created_kwargs["model"] == extractor_client_module.DEFAULT_MODEL
    assert client.model_name == extractor_client_module.DEFAULT_MODEL


def test_build_extractor_client_from_env_uses_json_schema_strategy_argument(monkeypatch):
    created_kwargs: dict[str, object] = {}
    seen_payloads: list[object] = []

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            seen_payloads.append(payload)
            return self.schema(answer=payload[-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

        def with_structured_output(self, schema, *, method, strict):
            assert method == "json_schema"
            assert strict is True
            return FakeRunnable(schema)

    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="gpt-compatible",
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
    assert seen_payloads == [[{"role": "user", "content": "可调用"}]]
    assert result.answer == "可调用"


def test_build_extractor_client_from_env_uses_tool_call_strategy_argument(monkeypatch):
    seen_methods: list[tuple[str, bool | None]] = []
    seen_payloads: list[object] = []

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            seen_payloads.append(payload)
            return self.schema(answer=payload[-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            seen_methods.append((method, strict))
            return FakeRunnable(schema)

    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="gpt-compatible",
        structured_output_strategy="tool_call",
    )
    result = client.invoke(
        output_schema=DummyOutput,
        messages=[{"role": "user", "content": "tool"}],
    )

    assert client.structured_output_strategy == "tool_call"
    assert seen_methods == [("function_calling", True)]
    assert seen_payloads == [[{"role": "user", "content": "tool"}]]
    assert result.answer == "tool"


def test_build_extractor_client_from_env_falls_back_to_tool_call_when_json_schema_is_unsupported(
    monkeypatch,
):
    seen_methods: list[tuple[str, bool | None]] = []

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            return self.schema(answer=payload[-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            seen_methods.append((method, strict))
            if method == "json_schema":
                raise RuntimeError("json_schema unsupported")
            return FakeRunnable(schema)

    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="gpt-compatible",
        structured_output_strategy="auto",
    )
    result = client.invoke(
        output_schema=DummyOutput,
        messages=[{"role": "user", "content": "fallback"}],
    )

    assert client.structured_output_strategy == "auto"
    assert seen_methods == [("json_schema", True), ("function_calling", True)]
    assert result.answer == "fallback"


def test_invoke_rejects_raw_json_content_when_structured_invoke_fails(monkeypatch):
    class FakeRunnable:
        def invoke(self, payload):
            assert payload == [{"role": "user", "content": "json please"}]
            raise RuntimeError("structured invoke failed")

    class FakeMessage:
        def __init__(self, content):
            self.content = content
            self.additional_kwargs = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            del schema, method, strict
            return FakeRunnable()

        def invoke(self, messages):
            assert messages == [{"role": "user", "content": "json please"}]
            return FakeMessage('{"answer":"raw-json"}')

    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="gpt-compatible",
        structured_output_strategy="json_schema",
    )

    try:
        client.invoke(
            output_schema=DummyOutput,
            messages=[{"role": "user", "content": "json please"}],
        )
    except extractor_client_module.ExtractorClientInvocationError as exc:
        assert "failed to invoke structured output runnable" in str(exc)
    else:
        raise AssertionError("结构化调用失败后不应继续解析裸 JSON 文本")


def test_invoke_rejects_raw_tool_call_arguments_when_structured_invoke_fails(monkeypatch):
    class FakeRunnable:
        def invoke(self, payload):
            assert payload == [{"role": "user", "content": "tool please"}]
            raise RuntimeError("structured invoke failed")

    class FakeMessage:
        def __init__(self):
            self.content = None
            self.additional_kwargs = {
                "tool_calls": [
                    {
                        "function": {
                            "name": "DummyOutput",
                            "arguments": '{"answer":"tool-json"}',
                        }
                    }
                ]
            }

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            del schema, method, strict
            return FakeRunnable()

        def invoke(self, messages):
            assert messages == [{"role": "user", "content": "tool please"}]
            return FakeMessage()

    monkeypatch.setattr(extractor_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = extractor_client_module.build_extractor_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="gpt-compatible",
        structured_output_strategy="tool_call",
    )

    try:
        client.invoke(
            output_schema=DummyOutput,
            messages=[{"role": "user", "content": "tool please"}],
        )
    except extractor_client_module.ExtractorClientInvocationError as exc:
        assert "failed to invoke structured output runnable" in str(exc)
    else:
        raise AssertionError("结构化调用失败后不应继续解析裸 tool call 参数")


def test_build_extractor_client_from_env_rejects_unknown_structured_output_strategy_argument(
    monkeypatch,
):
    try:
        extractor_client_module.build_extractor_client(
            base_url="https://llm.example.com/v1",
            api_key="test-key",
            model="gpt-compatible",
            structured_output_strategy="unsupported",  # type: ignore[arg-type]
        )
    except extractor_client_module.ExtractorClientConfigError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("未知 structured output 策略应被拒绝")
