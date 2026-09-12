"""直接迭代事件 → 完成或失败；取消测试见 test_rpc_execution_chain.py。"""
import pytest
from routes import file_extraction_agent as module
from service.file_extraction_agent.core.contracts import MessageDelta, ModelFailed

@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_outer_stream_alone_emits_terminal(monkeypatch, failure):
    async def events(**kwargs):
        yield MessageDelta("message", "正文")
        if failure:
            raise RuntimeError("生成失败")
    monkeypatch.setattr(module, "run_qa_stream", events)
    runtime = module.stream_completion([], object(), [])
    output = [event async for event in runtime]
    assert [event.type for event in output] == [
        "completion.created", "source_indexed", "model_message.delta",
        "completion.failed" if failure else "completion.completed",
    ]
    assert [event.seq for event in output] == [1, 2, 3, 4]
    if failure:
        assert output[-1].error_message == "生成失败"


@pytest.mark.asyncio
async def test_model_failure_becomes_single_failed_completion(monkeypatch):
    async def outputs(**kwargs):
        yield ModelFailed("attempt-id", "请求耗尽")
    monkeypatch.setattr(module, "run_qa_stream", outputs)
    output = [event async for event in module.stream_completion({}, object(), [])]
    assert [event.type for event in output] == [
        "completion.created", "source_indexed", "completion.failed",
    ]
    assert output[-1].error_message == "请求耗尽"
