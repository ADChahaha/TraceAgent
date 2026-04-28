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
        structured_output_strategy="json_schema",
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
