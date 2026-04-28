from __future__ import annotations

from service.route_policy_agent.policy_client import (
    RoutePolicyClientConfigError,
    build_policy_client,
)


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
