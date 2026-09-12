from __future__ import annotations

import pytest

from service.file_extraction_agent.schemas import (
    DocumentQaMessage,
    ModelConfig,
    RunOptions,
)


def test_message_accepts_tool_history():
    """当前入口使用的消息对象保留工具调用与对应结果。"""
    assistant = DocumentQaMessage(role="assistant", content="", tool_calls=[
        {"id": "call", "name": "read", "args": {"path": "documents/a.md"}},
    ])
    result = DocumentQaMessage(role="tool", content="结果", tool_call_id="call", name="read")
    assert assistant.tool_calls[0]["id"] == result.tool_call_id


@pytest.mark.parametrize("values", [
    {"role": "user", "content": " "},
    {"role": "tool", "content": "结果"},
    {"role": "user", "content": "问题", "memory": {}},
])
def test_message_rejects_invalid_content_or_extra_fields(values):
    """空正文、缺工具 ID 或未定义字段不能进入历史。"""
    with pytest.raises(ValueError):
        DocumentQaMessage.model_validate(values)


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


def test_run_options_only_configures_tool_timeout():
    from dataclasses import fields

    assert [field.name for field in fields(RunOptions)] == ["tool_execution_timeout"]
    assert RunOptions().tool_execution_timeout == 60.0


def test_protocol_removes_tool_budget_without_reusing_field_number():
    from agent_proto import agent_pb2 as pb
    from google.protobuf.descriptor_pb2 import DescriptorProto

    descriptor = pb.RunOptions.DESCRIPTOR
    assert list(descriptor.fields_by_name) == ["tool_execution_timeout"]
    assert descriptor.fields_by_name["tool_execution_timeout"].number == 2
    message = DescriptorProto()
    descriptor.CopyToProto(message)
    assert "max_tool_calls" in message.reserved_name
    assert any(r.start <= 1 < r.end for r in message.reserved_range)
