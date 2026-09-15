"""真实 DOCX → gRPC 上传 → HTML/资源发布（storage 服务）→ 路径问答，验证完整资源链路。"""

import io
import json
from pathlib import Path

import grpc
import numpy as np
import pytest
from docx import Document

from agent_proto import agent_pb2 as pb
from document_service.document_resources import model as embedding_model


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


def upload(document_rpc):
    document = Document()
    document.add_heading("合同", 1)
    document.add_paragraph("付款期限为三十天。")
    data = io.BytesIO()
    document.save(data)
    return document_rpc.PrepareResources(pb.PrepareResourcesRequest(files=[
        pb.UploadedFile(filename="合同.docx", content=data.getvalue()),
        pb.UploadedFile(filename="附件.docx", content=data.getvalue()),
    ]), timeout=10)


def _bucket(refs):
    from traceagent_shared.object_store import parse_resource_path
    documents_location = next(ref.location for ref in refs if ref.type == "documents")
    bucket, _ = parse_resource_path(documents_location)
    return bucket


def test_prepare_real_docx_publishes_complete_resource(resources, document_rpc, s3_store):
    """真实多文档上传发布单个文档树归档和可用索引，不再内联返回 HTML。"""
    root, calls = resources
    result = upload(document_rpc)
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


def test_prepare_failure_does_not_publish_resource(resources, document_rpc, monkeypatch):
    """embedding 失败映射 INTERNAL，不发布半成品。"""
    def fail(**kwargs):
        raise RuntimeError("embedding unavailable")
    monkeypatch.setattr(embedding_model, "get_embedder", fail)
    with pytest.raises(grpc.RpcError) as error:
        upload(document_rpc)
    assert error.value.code() == grpc.StatusCode.INTERNAL
    assert "embedding unavailable" in error.value.details()


@pytest.mark.parametrize("files", [[], [pb.UploadedFile(filename="bad.txt", content=b"text")]])
def test_prepare_rejects_unsupported_or_missing_files(resources, document_rpc, files):
    """空上传或不支持的类型在处理前返回 INVALID_ARGUMENT。"""
    with pytest.raises(grpc.RpcError) as error:
        document_rpc.PrepareResources(pb.PrepareResourcesRequest(files=files), timeout=5)
    assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_prepare_pdf_calls_parser_then_builds_resource(resources, document_rpc, monkeypatch):
    """PDF bytes 交给解析器，返回的 HTML 进入真实资源构建。"""
    from document_service.document_processor import processor
    from document_service.document_processor.schemas import ProcessResult
    calls = []
    def parse(file, file_type=None):
        calls.append((file.filename, file.read()))
        return ProcessResult(filename=file.filename, html="<p>PDF 内容</p>")
    monkeypatch.setattr(processor, "process", parse)
    result = document_rpc.PrepareResources(pb.PrepareResourcesRequest(files=[
        pb.UploadedFile(filename="a.pdf", content=b"%PDF-1.4"),
    ]), timeout=5)
    assert calls == [("a.pdf", b"%PDF-1.4")]
    assert resources[1] == ["PDF 内容"]


def test_parser_failure_identifies_file_and_does_not_build_index(resources, document_rpc, monkeypatch):
    """解析异常映射 INTERNAL 并标明文件，不进入索引构建。"""
    from document_service.document_processor import processor
    def fail(file, file_type=None):
        raise RuntimeError("invalid PDF")
    monkeypatch.setattr(processor, "process", fail)
    with pytest.raises(grpc.RpcError) as error:
        document_rpc.PrepareResources(pb.PrepareResourcesRequest(files=[
            pb.UploadedFile(filename="bad.pdf", content=b"pdf"),
        ]), timeout=5)
    assert error.value.code() == grpc.StatusCode.INTERNAL
    assert "bad.pdf" in error.value.details() and "invalid PDF" in error.value.details()
    assert resources[1] == []
