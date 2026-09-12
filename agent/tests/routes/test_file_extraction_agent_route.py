"""真实 RPC → 请求内执行流 → protobuf，验证事件、校验和原生模型取消。"""
import asyncio
import json
import time
import grpc
import pytest
from tests.async_helpers import async_items
from agent_proto import agent_pb2 as pb
from routes import file_extraction_agent as qa_routes
from langchain_core.messages import AIMessage, ToolMessage
from service.file_extraction_agent.schemas import RunOptions

@pytest.fixture
def execution(monkeypatch):
    async def fake_prepare(resource_path):
        return {"stub": True}
    monkeypatch.setattr(qa_routes, "prepare_workspace", fake_prepare)
    monkeypatch.setattr(qa_routes, "build_qa_model", lambda config: object())

def request(**fields):
    values = dict(completion_id="cmp_rpc",
                  resource_path=[pb.ResourceRef(type="documents", location="s3://res_test/documents"),
                                 pb.ResourceRef(type="index", location="s3://res_test/index")],
                  messages=[pb.QaMessage(role="user", content="问题")])
    values.update(fields)
    return pb.ChatCompletionRequest(**values)


@pytest.mark.parametrize("cancel", [False, True])
def test_real_graph_streams_native_chunks_and_retry_over_rpc(rpc, execution, monkeypatch, cancel):
    """真实图和模型回调 → RPC 增量；验证重试字段及生成期间业务取消。"""
    from tests.file_extraction_agent.test_streaming_retry import StreamingModel
    from service.file_extraction_agent.core import loop

    model = StreamingModel(failures=0 if cancel else 1)
    if not cancel:
        model._release.set()
    monkeypatch.setattr(qa_routes, "build_qa_model", lambda config: model)
    monkeypatch.setattr(loop, "build_tools", lambda workspace: [])
    stream = rpc.ChatCompletion(request(), timeout=5)
    events = []
    try:
        for event in stream:
            events.append(event)
            if cancel and event.type == "model_message.delta":
                assert not model._closed.is_set()
                stream.cancel()
                break
    finally:
        stream.cancel()
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert not any(e.type == "completion.cancelled" for e in events)
    if not cancel:
        assert events[-1].type == "completion.completed"
    if cancel:
        assert not any(e.type == "model_message.done" for e in events)
        limit = time.monotonic() + 2
        while not model._closed.is_set() and time.monotonic() < limit:
            time.sleep(0.01)
        assert model._closed.is_set()
        assert model._calls == 1
    else:
        retry = next(e for e in events if e.type == "model_request.retrying")
        assert retry.attempt == 2 and retry.max_attempts == 5
        assert 375 <= retry.retry_delay_ms <= 500
        done = next(e for e in events if e.type == "model_message.done")
        assert done.content == "前半后半" and done.message_id != retry.message_id
        assert model._calls == 2


def test_chat_streams_typed_events_and_preserves_json(rpc, execution, monkeypatch):
    """事件按序逐条传输，动态 JSON 保留大整数、空值和特殊字符。"""
    payload = {"number": 2 ** 60 + 1, "text": '中文\n"引号"', "null": None}
    async def events(**kwargs):
        yield AIMessage(content="回答", tool_calls=[{"id": "call1", "name": "read", "args": payload}])
        yield ToolMessage(content="结果", name="read", tool_call_id="call1", artifact=payload,
                          additional_kwargs={"tool_args": payload})
    monkeypatch.setattr(qa_routes, "run_qa_stream", events)
    result = list(rpc.ChatCompletion(request(), timeout=5))
    assert [e.seq for e in result] == [1, 2, 3, 4, 5, 6]
    assert result[0].type == "completion.created"
    result = result[2:]
    assert result[0].HasField("is_final") and result[0].is_final is False
    assert json.loads(result[0].tool_calls[0].args_json) == payload
    assert json.loads(result[2].result_json) == payload
    assert json.loads(result[2].args_json) == payload
    assert result[-1].type == "completion.completed"
    assert "completion_id" not in result[0].DESCRIPTOR.fields_by_name


def test_chat_preserves_history_options_and_model_defaults(rpc, execution, monkeypatch):
    """历史工具消息、显式零值和未传配置的默认值保持一致。"""
    seen = {}
    def build(config):
        seen["config"] = config
        return object()
    async def events(**kwargs):
        seen.update(kwargs)
        if False:
            yield {}
    monkeypatch.setattr(qa_routes, "build_qa_model", build)
    monkeypatch.setattr(qa_routes, "run_qa_stream", events)
    history = [{"id": "a", "name": "read", "args": {"path": "a.md"}}]
    messages = [
        pb.QaMessage(role="assistant", content="", tool_calls_json=json.dumps(history)),
        pb.QaMessage(role="tool", content="结果", tool_call_id="a", name="read"),
    ]
    list(rpc.ChatCompletion(request(messages=messages, run_options=pb.RunOptions(tool_execution_timeout=0),
                                   model_config=pb.ModelConfig(top_k=0, temperature=0)), timeout=5))
    assert seen["messages"][0].tool_calls == history
    assert seen["messages"][1].tool_call_id == "a"
    assert seen["run_options"] == RunOptions(tool_execution_timeout=0)
    assert seen["config"].top_k == 0
    assert seen["config"].api_transport == "responses"
    assert seen["config"].request_timeout is None
    list(rpc.ChatCompletion(request(), timeout=5))
    assert seen["config"] is None and seen["run_options"] is None


def test_chat_model_override_precedence(rpc, execution, monkeypatch):
    """兼容扁平模型参数，嵌套模型配置优先。"""
    configs = []
    monkeypatch.setattr(qa_routes, "build_qa_model", lambda config: configs.append(config))
    monkeypatch.setattr(qa_routes, "run_qa_stream",
                        lambda **kwargs: async_items([]))
    flat = dict(base_url="https://example.com/v1", openai_api_key="key", model="qa",
                api_transport="chat_completions", temperature=0.2, top_p=0.9, top_k=40)
    list(rpc.ChatCompletion(request(**flat), timeout=5))
    assert configs[-1].api_key == "key" and configs[-1].model_name == "qa"
    assert configs[-1].top_p == 0.9 and configs[-1].top_k == 40
    list(rpc.ChatCompletion(request(**flat, model_config=pb.ModelConfig(model_name="nested")), timeout=5))
    assert configs[-1].model_name == "nested" and configs[-1].api_key is None


@pytest.mark.parametrize("fields", [
    {"completion_id": "../bad"}, {"messages": []},
    {"messages": [pb.QaMessage(role="unknown", content="问题")]},
    {"messages": [pb.QaMessage(role="tool", content="结果")]},
    {"messages": [pb.QaMessage(role="assistant", tool_calls_json="{bad")]},
    {"messages": [pb.QaMessage(role="assistant", tool_calls_json="{}")]},
])
def test_chat_rejects_invalid_input_before_first_event(rpc, execution, fields):
    """无效 ID、角色、历史工具 JSON 或空消息在首事件前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        next(rpc.ChatCompletion(request(**fields), timeout=5))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_chat_runtime_failure_is_terminal_event(rpc, execution, monkeypatch):
    """开始执行后的异常通过 completion.failed 保留原始错误文本。"""
    def fail(**kwargs):
        raise RuntimeError('失败\n"原因"')
    monkeypatch.setattr(qa_routes, "run_qa_stream", fail)
    events = list(rpc.ChatCompletion(request(), timeout=5))
    assert len(events) == 3
    assert events[0].type == "completion.created"
    assert events[-1].type == "completion.failed"
    assert events[-1].error_message == '失败\n"原因"'


def test_legacy_request_fields_are_not_in_protocol():
    """新契约只接收资源路径，不定义旧业务字段。"""
    fields = pb.ChatCompletionRequest.DESCRIPTOR.fields_by_name
    assert not {"documents", "metadata", "memory", "task_spec"} & set(fields.keys())
