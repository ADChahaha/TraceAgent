"""直接迭代事件 → 完成或失败；取消测试见 test_rpc_execution_chain.py。"""
import pytest
from service.file_extraction_agent import completion_runtime as module
from service.file_extraction_agent.core.contracts import ModelFailed

@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_outer_stream_alone_emits_terminal(monkeypatch, failure):
    async def events(**kwargs):
        yield {"type": "model_message.delta", "delta": "正文"}
        if failure:
            raise RuntimeError("生成失败")
    monkeypatch.setattr(module, "stream_completion_events", events)
    runtime = module.stream_completion([], object(), [])
    output = [event async for event in runtime]
    assert [event["type"] for event in output] == [
        "completion.created", "model_message.delta",
        "completion.failed" if failure else "completion.completed",
    ]
    assert [event["seq"] for event in output] == [1, 2, 3]
    if failure:
        assert output[-1]["error_message"] == "生成失败"


@pytest.mark.asyncio
async def test_inner_failure_raises_without_completion_event(monkeypatch):
    async def outputs(**kwargs):
        yield ModelFailed("attempt-id", "请求耗尽")
    monkeypatch.setattr(module, "run_qa_stream", outputs)
    output = []
    with pytest.raises(RuntimeError, match="请求耗尽"):
        async for event in module.stream_completion_events(workspace=[], messages=[], qa_model=object()):
            output.append(event)
    assert all(not event["type"].startswith("completion.") for event in output)
