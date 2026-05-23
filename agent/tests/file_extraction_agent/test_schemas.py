from __future__ import annotations

from service.file_extraction_agent.schemas import (
    CompletionStatus,
    DocumentQaCompletionRequest,
    DocumentQaMemory,
    DocumentQaMessage,
    InputDocument,
    ModelConfig,
    RunOptions,
)


def test_completion_request_accepts_documents_messages_and_memory():
    request = DocumentQaCompletionRequest(
        completion_id="cmp_123",
        documents=[{"filename": "contract.html", "html": "<p>正文</p>"}],
        messages=[
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮回答摘要"},
            {"role": "user", "content": "可以提前终止吗？"},
        ],
        memory={
            "reading_history": ["evidence://0001"],
            "evidence_notes": [
                {
                    "locator": "evidence://0001.0001.0001/S001",
                    "note": "终止权",
                }
            ],
            "prior_answers": ["上一轮回答摘要"],
            "open_threads": ["通知期限待确认"],
        },
    )

    assert request.completion_id == "cmp_123"
    assert request.documents[0] == InputDocument(filename="contract.html", html="<p>正文</p>")
    assert request.messages[-1] == DocumentQaMessage(role="user", content="可以提前终止吗？")
    assert request.memory.reading_history == ["evidence://0001"]
    assert request.memory.evidence_notes[0]["note"] == "终止权"


def test_completion_request_accepts_openai_tool_messages():
    request = DocumentQaCompletionRequest(
        completion_id="cmp_123",
        documents=[{"filename": "contract.html", "html": "<p>正文</p>"}],
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
                            "arguments": "{\"locator\":\"evidence://0001.0001.0001\"}",
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


def test_memory_defaults_to_empty_lists():
    memory = DocumentQaMemory()

    assert memory.reading_history == []
    assert memory.evidence_notes == []
    assert memory.prior_answers == []
    assert memory.open_threads == []


def test_completion_status_values_match_public_events():
    assert CompletionStatus.__args__ == (
        "queued",
        "in_progress",
        "cancelling",
        "cancelled",
        "completed",
        "failed",
    )


def test_model_config_keeps_resolution_model_and_sampling_options():
    config = ModelConfig(
        base_url="https://example.com/v1",
        api_key="key",
        resolution_model_name="resolution",
        temperature=0.2,
        top_p=0.9,
        top_k=40,
        max_retries=7,
        request_timeout=90.0,
    )

    assert config.resolution_model_name == "resolution"
    assert config.temperature == 0.2
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.max_retries == 7
    assert config.request_timeout == 90.0


def test_run_options_defaults_to_tool_budget_only():
    assert RunOptions().max_tool_calls == 200
