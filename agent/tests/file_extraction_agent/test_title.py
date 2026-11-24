"""会话标题生成模块与 AgentService.GenerateTitle gRPC 路由测试。"""

from __future__ import annotations

import grpc
import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage

from agent_proto import agent_pb2 as pb, agent_pb2_grpc as rpc
from routes import AgentService
from service.file_extraction_agent.core import title as title_module
from service.file_extraction_agent.core.title import build_title_messages, generate_title, sanitize_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Payment terms and liability cap."', "Payment terms and liability cap"),
        ("标题：**《2026年采购合同付款条款》**。", "2026年采购合同付款条款"),
        ("\n# - `Quarterly Revenue Summary`\nSecond line ignored", "Quarterly Revenue Summary"),
        ("「請求書の支払期限と振込先」", "請求書の支払期限と振込先"),
        ("   \n  ", ""),
    ],
)
def test_sanitize_title_strips_markdown_quotes_and_noise(raw: str, expected: str):
    assert sanitize_title(raw) == expected


def test_sanitize_title_truncates_safely():
    long_english = "Detailed comparison of indemnity clauses termination rights and annual renewal conditions across agreements"
    result = sanitize_title(long_english, max_length=40)
    assert len(result) <= 40
    assert not result.endswith(" ")


def test_build_title_messages_includes_question_and_limited_filenames():
    messages = build_title_messages("What are the termination terms?", ["a.pdf", "b.docx", "c.pdf", "d.pdf", "e.pdf", "f.pdf"])
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "What are the termination terms?" in messages[1].content
    assert "e.pdf" in messages[1].content
    assert "f.pdf" not in messages[1].content


async def test_generate_title_streams_visible_text_and_sanitizes():
    captured = []

    class FakeStreamingModel:
        async def astream(self, messages):
            captured.append(messages)
            yield AIMessageChunk(content=[{"type": "reasoning", "summary": []}])
            yield AIMessageChunk(content='Title: "')
            yield AIMessageChunk(content=[{"type": "text", "text": "Contract Renewal Terms"}])
            yield AIMessageChunk(content='."')

    result = await generate_title(
        question="When does the contract auto-renew?",
        filenames=["master-agreement.pdf"],
        chat_model=FakeStreamingModel(),
    )
    assert result == "Contract Renewal Terms"
    assert len(captured) == 1


async def test_generate_title_rejects_empty_question_and_empty_model_output():
    with pytest.raises(ValueError, match="question"):
        await generate_title(question="   ", chat_model=object())

    class EmptyModel:
        async def astream(self, messages):
            yield AIMessageChunk(content="   ")

    with pytest.raises(RuntimeError, match="empty"):
        await generate_title(question="Summarize this", chat_model=EmptyModel())


async def test_grpc_generate_title_route_success_and_validation(monkeypatch):
    seen = {}

    async def fake_generate_title(*, question, filenames, model_config=None):
        seen["args"] = (question, list(filenames), model_config)
        if not question.strip():
            raise ValueError("question must not be empty")
        return "合同违约金条款分析"

    monkeypatch.setattr(title_module, "generate_title", fake_generate_title)
    server = grpc.aio.server()
    rpc.add_AgentServiceServicer_to_server(AgentService(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = rpc.AgentServiceStub(channel)
            response = await stub.GenerateTitle(
                pb.GenerateTitleRequest(question="这份合同的违约金怎么算？", filenames=["contract.pdf"])
            )
            assert response.title == "合同违约金条款分析"
            assert seen["args"][:2] == ("这份合同的违约金怎么算？", ["contract.pdf"])

            with pytest.raises(grpc.aio.AioRpcError) as exc_info:
                await stub.GenerateTitle(pb.GenerateTitleRequest(question="   "))
            assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    finally:
        await server.stop(0)
