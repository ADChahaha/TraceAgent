from __future__ import annotations

from pydantic import BaseModel

from service.route_policy_agent.policy_client import (
    RoutePolicyClientConfigError,
    RoutePolicyClientInvocationError,
    build_policy_client,
)


class DummyRouteOutput(BaseModel):
    route: str


def test_build_policy_client_requires_connection_params(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL", raising=False)

    try:
        build_policy_client()
    except RoutePolicyClientConfigError as exc:
        message = str(exc)
        assert "base_url" in message
        assert "api_key" in message
        assert "model" not in message
    else:
        raise AssertionError("未提供 policy client 和连接参数时应明确拒绝")


def test_build_policy_client_uses_tool_call_only(monkeypatch):
    from service.route_policy_agent import policy_client as policy_client_module

    seen_methods: list[tuple[str, bool | None]] = []

    class FakeRunnable:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, payload):
            return self.schema(route=payload[-1]["content"])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            seen_methods.append((method, strict))
            return FakeRunnable(schema)

    monkeypatch.setattr(policy_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = build_policy_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="route-model",
        structured_output_strategy="tool_call",
    )
    result = client.invoke(
        output_schema=DummyRouteOutput,
        messages=[{"role": "user", "content": "accept"}],
    )

    assert client.structured_output_strategy == "tool_call"
    assert seen_methods == [("function_calling", True)]
    assert result.route == "accept"


def test_build_policy_client_rejects_json_schema_and_auto_strategy_arguments():
    for strategy in ["json_schema", "auto"]:
        try:
            build_policy_client(
                base_url="https://llm.example.com/v1",
                api_key="test-key",
                model="route-model",
                structured_output_strategy=strategy,  # type: ignore[arg-type]
            )
        except RoutePolicyClientConfigError as exc:
            assert "only supported structured_output_strategy: tool_call" in str(exc)
        else:
            raise AssertionError(f"route policy 不应再支持 {strategy}")


def test_policy_client_rejects_raw_json_content_when_structured_invoke_fails(monkeypatch):
    from service.route_policy_agent import policy_client as policy_client_module

    class FakeRunnable:
        def invoke(self, payload):
            assert payload == [{"role": "user", "content": "route please"}]
            raise RuntimeError("structured route invoke failed")

    class FakeMessage:
        content = '{"route":"accept"}'
        additional_kwargs = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            del kwargs

        def with_structured_output(self, schema, *, method, strict):
            del schema, method, strict
            return FakeRunnable()

        def invoke(self, messages):
            assert messages == [{"role": "user", "content": "route please"}]
            return FakeMessage()

    monkeypatch.setattr(policy_client_module, "ChatOpenAI", FakeChatOpenAI)

    client = build_policy_client(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="route-model",
        structured_output_strategy="tool_call",
    )

    try:
        client.invoke(
            output_schema=DummyRouteOutput,
            messages=[{"role": "user", "content": "route please"}],
        )
    except RoutePolicyClientInvocationError as exc:
        assert "failed to invoke route policy structured output" in str(exc)
    else:
        raise AssertionError("route policy 结构化调用失败后不应继续解析裸 JSON 文本")
