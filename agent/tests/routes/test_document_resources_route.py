"""真实 DOCX → gRPC 上传 → HTML/资源发布 → 路径问答，验证完整资源链路。"""

import io
import json
from pathlib import Path

import grpc
import numpy as np
import pytest
from docx import Document

from agent_proto import agent_pb2 as pb
from service.document_resources import model as embedding_model


@pytest.fixture
def resources(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_RESOURCES_ROOT", str(tmp_path))
    calls = []
    class Embedder:
        def encode(self, texts):
            calls.extend(texts)
            return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)
    monkeypatch.setattr(embedding_model, "get_embedder", lambda **kwargs: Embedder())
    monkeypatch.setattr(embedding_model, "get_tokenizer", lambda *a, **k: lambda text: [(i, i + 1) for i in range(len(text))])
    return tmp_path, calls


def upload(rpc):
    document = Document()
    document.add_heading("合同", 1)
    document.add_paragraph("付款期限为三十天。")
    data = io.BytesIO()
    document.save(data)
    return rpc.PrepareResources(pb.PrepareResourcesRequest(files=[
        pb.UploadedFile(filename="合同.docx", content=data.getvalue()),
        pb.UploadedFile(filename="附件.docx", content=data.getvalue()),
    ]), timeout=10)


def chat_request(path):
    return pb.ChatCompletionRequest(completion_id="cmp_resource", resource_path=str(path),
                                    messages=[pb.QaMessage(role="user", content="你好")])


def test_prepare_real_docx_publishes_complete_resource(resources, rpc):
    """真实多文档上传返回 HTML、文档树和可用索引。"""
    root, calls = resources
    result = upload(rpc)
    path = Path(result.resource_path)
    assert path.parent == root
    assert (path / "manifest.json").is_file()
    assert (path / "index" / "vectors.npy").is_file()
    assert len(list((path / "documents").iterdir())) == 2
    assert [doc.filename for doc in result.documents] == ["合同.docx", "附件.docx"]
    assert "三十天" in result.documents[0].html
    assert calls


def test_prepare_failure_does_not_publish_resource(resources, rpc, monkeypatch):
    """embedding 失败映射 INTERNAL，清理临时目录且不发布半成品。"""
    def fail(**kwargs):
        raise RuntimeError("embedding unavailable")
    monkeypatch.setattr(embedding_model, "get_embedder", fail)
    with pytest.raises(grpc.RpcError) as error:
        upload(rpc)
    assert error.value.code() == grpc.StatusCode.INTERNAL
    assert "embedding unavailable" in error.value.details()
    assert list(resources[0].iterdir()) == []


@pytest.mark.parametrize("files", [[], [pb.UploadedFile(filename="bad.txt", content=b"text")]])
def test_prepare_rejects_unsupported_or_missing_files(resources, rpc, files):
    """空上传或不支持的类型在处理前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        rpc.PrepareResources(pb.PrepareResourcesRequest(files=files), timeout=5)
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert list(resources[0].iterdir()) == []


def test_qa_uses_prepared_path_without_rebuilding_or_deleting(resources, rpc, monkeypatch):
    """两轮真实图执行复用同一路径，不重建向量、不删除资源。"""
    from langchain_core.messages import AIMessage
    from service.file_extraction_agent import manager
    class Model:
        def bind_tools(self, tools):
            return self
        def invoke(self, messages):
            return AIMessage(content="回答", response_metadata={"finish_reason": "stop"})
    monkeypatch.setattr(manager, "build_qa_model", lambda config: Model())
    path = upload(rpc).resource_path
    before = list(resources[1])
    for cid in ("cmp_first", "cmp_second"):
        request = chat_request(path)
        request.completion_id = cid
        events = list(rpc.ChatCompletion(request, timeout=5))
        assert events[-1].type == "completion.completed"
        assert Path(path).is_dir()
    assert resources[1] == before


def test_qa_rejects_unmanaged_resource_path(resources, rpc):
    """受管理根目录之外的路径在首事件前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        next(rpc.ChatCompletion(chat_request(resources[0].parent), timeout=5))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.parametrize("damage", ["missing_index", "bad_version", "outside_reference"])
def test_qa_rejects_damaged_resource_without_rebuilding(resources, rpc, damage):
    """索引缺失、清单版本错误、引用越界均拒绝执行且不重建。"""
    path = Path(upload(rpc).resource_path)
    if damage == "missing_index":
        (path / "index" / "vectors.npy").unlink()
    elif damage == "bad_version":
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = -1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        index_path = path / "index" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["chunks"][0]["covered_files"] = ["../../outside.md"]
        index_path.write_text(json.dumps(index), encoding="utf-8")
    before = list(resources[1])
    with pytest.raises(grpc.RpcError) as error:
        next(rpc.ChatCompletion(chat_request(path), timeout=5))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert resources[1] == before


def test_prepare_pdf_calls_parser_then_builds_resource(resources, rpc, monkeypatch):
    """PDF bytes 交给解析器，返回的 HTML 进入真实资源构建。"""
    from service.document_processor import processor
    from service.document_processor.schemas import ProcessResult
    calls = []
    def parse(file, file_type=None):
        calls.append((file.filename, file.read()))
        return ProcessResult(filename=file.filename, html="<p>PDF 内容</p>")
    monkeypatch.setattr(processor, "process", parse)
    result = rpc.PrepareResources(pb.PrepareResourcesRequest(files=[
        pb.UploadedFile(filename="a.pdf", content=b"%PDF-1.4"),
    ]), timeout=5)
    assert calls == [("a.pdf", b"%PDF-1.4")]
    assert result.documents[0].html == "<p>PDF 内容</p>"
    assert resources[1] == ["PDF 内容"]


def test_parser_failure_identifies_file_and_does_not_build_index(resources, rpc, monkeypatch):
    """解析异常映射 INTERNAL 并标明文件，不进入索引构建。"""
    from service.document_processor import processor
    def fail(file, file_type=None):
        raise RuntimeError("invalid PDF")
    monkeypatch.setattr(processor, "process", fail)
    with pytest.raises(grpc.RpcError) as error:
        rpc.PrepareResources(pb.PrepareResourcesRequest(files=[
            pb.UploadedFile(filename="bad.pdf", content=b"pdf"),
        ]), timeout=5)
    assert error.value.code() == grpc.StatusCode.INTERNAL
    assert "bad.pdf" in error.value.details() and "invalid PDF" in error.value.details()
    assert resources[1] == [] and list(resources[0].iterdir()) == []
