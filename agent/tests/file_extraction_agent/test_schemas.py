from __future__ import annotations

import pytest

from service.file_extraction_agent.schemas import (
    CompletionStatus,
    DocumentQaCompletionRequest,
    DocumentQaMessage,
    ModelConfig,
    RunOptions,
)


def test_completion_request_accepts_resource_path_and_append_only_messages():
    request = DocumentQaCompletionRequest(
        completion_id="cmp_123",
        resource_path="D:/resources/res_test",
        messages=[
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮回答摘要"},
            {"role": "user", "content": "可以提前终止吗？"},
        ],
    )

    assert request.completion_id == "cmp_123"
    assert request.resource_path == "D:/resources/res_test"
    assert request.messages[-1] == DocumentQaMessage(role="user", content="可以提前终止吗？")
    assert not hasattr(request, "memory")


def test_completion_request_rejects_memory_field():
    with pytest.raises(ValueError, match="memory"):
        DocumentQaCompletionRequest(
            completion_id="cmp_123",
            resource_path="D:/resources/res_test",
            messages=[{"role": "user", "content": "问题"}],
            memory={"prior_answers": ["会破坏 append-only prompt cache"]},
        )


def test_completion_request_accepts_openai_tool_messages():
    request = DocumentQaCompletionRequest(
        completion_id="cmp_123",
        resource_path="D:/resources/res_test",
        messages=[
            {"role": "user", "content": "看通知期限"},
            {
                "role": "assistant",
                "content": "我先读通知条款。",
                "tool_calls": [
                    {
                        "id": "call_read_notice",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": "{\"path\":\"/abs/0001-contract/0001-section/0001-block.md\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_read_notice",
                "name": "read",
                "content": "{\"ok\":true}",
            },
            {"role": "user", "content": "所以是多少天？"},
        ],
    )

    assert request.messages[1].tool_calls[0]["id"] == "call_read_notice"
    assert request.messages[2].role == "tool"
    assert request.messages[2].tool_call_id == "call_read_notice"


def test_completion_status_values_match_public_events():
    assert CompletionStatus.__args__ == (
        "queued",
        "in_progress",
        "cancelling",
        "cancelled",
        "completed",
        "failed",
    )


def test_model_config_keeps_model_transport_and_sampling_options():
    config = ModelConfig(
        base_url="https://example.com/v1",
        api_key="key",
        model_name="qa",
        api_transport="chat_completions",
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        max_retries=7,
        request_timeout=90.0,
    )

    assert config.model_name == "qa"
    assert config.api_transport == "chat_completions"
    assert config.temperature == 0.2
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.max_retries == 7
    assert config.request_timeout == 90.0


def test_model_config_defaults_disable_sdk_retries_for_outer_backoff():
    config = ModelConfig(model_name="qa")

    assert config.api_transport == "responses"
    assert config.max_retries == 0


def test_run_options_defaults_to_tool_budget_only():
    assert RunOptions().max_tool_calls == 200
