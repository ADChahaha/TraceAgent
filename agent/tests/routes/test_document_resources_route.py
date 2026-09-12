"""真实 DOCX → gRPC 上传 → HTML/资源发布（storage 服务）→ 路径问答，验证完整资源链路。"""

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
        def tokenize(self, text):
            return [(i, i + 1) for i in range(len(text))]

        def encode(self, texts):
            calls.extend(texts)
            return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)
    monkeypatch.setattr(embedding_model, "get_embedder", lambda **kwargs: Embedder())
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


def chat_request(refs, completion_id="cmp_resource"):
    return pb.ChatCompletionRequest(
        completion_id=completion_id,
        resource_path=[pb.ResourceRef(type=ref.type, location=ref.location) for ref in refs],
        messages=[pb.QaMessage(role="user", content="你好")],
    )


def _bucket(refs):
    from service.object_store import parse_resource_path
    documents_location = next(ref.location for ref in refs if ref.type == "documents")
    bucket, _ = parse_resource_path(documents_location)
    return bucket


def test_prepare_real_docx_publishes_complete_resource(resources, rpc, s3_store):
    """真实多文档上传发布单个文档树归档和可用索引，不再内联返回 HTML。"""
    root, calls = resources
    result = upload(rpc)
    refs = list(result.resource_path)
    assert [ref.type for ref in refs] == ["documents", "index", "raw", "raw"]
    bucket = _bucket(refs)
    assert s3_store.get_object(bucket, "documents.zip") is not None
    assert s3_store.get_object(bucket, "manifest.json") is not None
    assert s3_store.get_object(bucket, "index/vectors.npy") is not None
    assert s3_store.get_object(bucket, "index/index.json") is not None
    assert s3_store.list_objects(bucket, prefix="documents/") == []  # 树只存在于归档里
    assert calls


def test_protocol_prepare_response_drops_documents_payload():
    """共享协议不再暴露 documents/Document，调用方只拿资源定位。"""
    fields = pb.PrepareResourcesResponse.DESCRIPTOR.fields_by_name
    assert "resource_path" in fields
    assert "documents" not in fields
    assert "Document" not in pb.DESCRIPTOR.message_types_by_name


def test_prepare_failure_does_not_publish_resource(resources, rpc, monkeypatch):
    """embedding 失败映射 INTERNAL，不发布半成品。"""
    def fail(**kwargs):
        raise RuntimeError("embedding unavailable")
    monkeypatch.setattr(embedding_model, "get_embedder", fail)
    with pytest.raises(grpc.RpcError) as error:
        upload(rpc)
    assert error.value.code() == grpc.StatusCode.INTERNAL
    assert "embedding unavailable" in error.value.details()


@pytest.mark.parametrize("files", [[], [pb.UploadedFile(filename="bad.txt", content=b"text")]])
def test_prepare_rejects_unsupported_or_missing_files(resources, rpc, files):
    """空上传或不支持的类型在处理前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        rpc.PrepareResources(pb.PrepareResourcesRequest(files=files), timeout=5)
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_qa_uses_prepared_path_without_rebuilding_or_deleting(resources, rpc, monkeypatch, s3_store):
    """两轮真实图执行复用同一资源，不重建向量、不删除资源。"""
    from tests.file_extraction_agent.test_streaming_retry import StreamingModel
    from service.file_extraction_agent import application as qa_route
    model = StreamingModel()
    model._release.set()
    monkeypatch.setattr(qa_route, "build_qa_model", lambda config: model)
    refs = list(upload(rpc).resource_path)
    bucket = _bucket(refs)
    before = sorted(s3_store.list_objects(bucket))
    for cid in ("cmp_first", "cmp_second"):
        request = chat_request(refs, completion_id=cid)
        events = list(rpc.ChatCompletion(request, timeout=5))
        assert events[-1].type == "completion.completed"
        assert "".join(e.delta for e in events if e.type == "model_message.delta") == "前半后半"
        assert sum(e.type == "model_message.done" for e in events) == 1
        assert s3_store.get_object(bucket, "manifest.json") is not None
    assert sorted(s3_store.list_objects(bucket)) == before


def test_qa_rejects_unmanaged_resource_path(resources, rpc):
    """缺少 documents/index 定位的资源引用在首事件前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        next(rpc.ChatCompletion(pb.ChatCompletionRequest(
            completion_id="cmp_bad",
            resource_path=[pb.ResourceRef(type="raw", location="s3://nonexistent/raw/a.pdf")],
            messages=[pb.QaMessage(role="user", content="你好")],
        ), timeout=5))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.parametrize("damage", ["missing_index", "bad_version", "outside_reference"])
def test_qa_rejects_damaged_resource_without_rebuilding(resources, rpc, s3_store, damage):
    """索引缺失、清单版本错误、引用越界均拒绝执行且不重建。"""
    refs = list(upload(rpc).resource_path)
    bucket = _bucket(refs)
    if damage == "missing_index":
        s3_store.delete_object(bucket, "index/vectors.npy")
    elif damage == "bad_version":
        manifest = json.loads(s3_store.get_object(bucket, "manifest.json").decode("utf-8"))
        manifest["version"] = -1
        s3_store.put_object(bucket, "manifest.json", json.dumps(manifest).encode("utf-8"))
    else:
        index = json.loads(s3_store.get_object(bucket, "index/index.json").decode("utf-8"))
        index["chunks"][0]["covered_files"] = ["../../outside.md"]
        s3_store.put_object(bucket, "index/index.json", json.dumps(index).encode("utf-8"))
    with pytest.raises(grpc.RpcError) as error:
        next(rpc.ChatCompletion(chat_request(refs), timeout=5))
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


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
    assert resources[1] == []
