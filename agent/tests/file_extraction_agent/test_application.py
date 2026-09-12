"""普通 Python 请求 → 业务入口预检 → 类型化事件；不依赖 RPC。"""

import importlib
from contextlib import aclosing

import pytest

from service.file_extraction_agent.schemas import DocumentQaMessage, ResourceRef


@pytest.mark.asyncio
async def test_application_prepares_before_emitting_and_closes(monkeypatch):
    app = importlib.import_module("service.file_extraction_agent.application")
    calls = []

    async def prepare(refs):
        calls.append(refs)
        return {"ready": True}

    async def outputs(**kwargs):
        assert kwargs["workspace"] == {"ready": True}
        try:
            from service.file_extraction_agent.core.contracts import MessageDelta
            yield MessageDelta("m", "回答")
        finally:
            calls.append("closed")

    monkeypatch.setattr(app, "prepare_workspace", prepare)
    monkeypatch.setattr(app, "build_qa_model", lambda config: object())
    monkeypatch.setattr(app, "run_qa_stream", outputs)
    refs = [ResourceRef(type="documents", location="s3://test/documents.zip")]
    async with aclosing(app.stream_completion(
        completion_id="cmp_test", resource_refs=refs,
        messages=[DocumentQaMessage(role="user", content="问题")],
    )) as events:
        first = await anext(events)
        assert calls == [refs]
        assert first.type == "completion.created"
        assert not hasattr(first, "DESCRIPTOR")
        await anext(events)
        assert (await anext(events)).delta == "回答"
    assert calls[-1] == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("completion_id,messages", [("../bad", [DocumentQaMessage(role="user", content="问题")]), ("valid", [])])
async def test_invalid_request_never_prepares(monkeypatch, completion_id, messages):
    app = importlib.import_module("service.file_extraction_agent.application")
    async def prepare(refs):
        pytest.fail("无效输入不能触发资源预检")
    monkeypatch.setattr(app, "prepare_workspace", prepare)
    with pytest.raises(ValueError):
        await anext(app.stream_completion(completion_id=completion_id, resource_refs=[], messages=messages))
