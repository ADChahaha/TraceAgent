"""会话资源入口：只解析上传批次，复用已有文档与向量，处理成功后返回全量引用。

校验 session_id、文件名与删除引用后固定使用 res_<session_id> 桶。
原文件只列名称，增量构建或裁剪发布成功后写入、删除 raw；解析和 embedding
失败不改桶。逐对象发布和 raw 写入没有远端原子回滚；同桶由 backend 串行化。
"""

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from traceagent_shared.object_store import ObjectStore, ResourceRef, build_s3_object_store, parse_resource_path
from document_service.document_processor import processor
from document_service.document_resources.resources import publish_resources, remove_published_documents
from document_service.document_resources.schemas import InputDocument, UploadedFile


@dataclass
class UploadFileProxy:
    filename: str
    file: Any

    def read(self, *args):
        return self.file.read(*args)

    def seek(self, *args):
        return self.file.seek(*args)


def prepare_session_resources(
    session_id: str,
    files: list[UploadedFile],
    remove_raw: list[dict] = (),
    store: ObjectStore | None = None,
) -> list[ResourceRef]:
    """上传仅处理新增或替换文件、删除裁剪已有产物，返回全量引用。"""
    bucket = _session_bucket(session_id)
    store = store if store is not None else build_s3_object_store()
    removed = _removed_names(remove_raw, bucket)
    uploads = _validated_uploads(files)
    if removed and not uploads:
        names = {key.removeprefix("raw/") for key in store.list_objects(bucket, "raw/")}
        remaining = names - removed
        refs = remove_published_documents(store, bucket, removed) if remaining and names & removed else []
        if not remaining:
            _delete_published(store, bucket)
        for name in names & removed:
            store.delete_object(bucket, f"raw/{name}")
        if remaining and not refs:
            refs = [ResourceRef(type="documents", location=f"s3://{bucket}/documents.zip"),
                    ResourceRef(type="index", location=f"s3://{bucket}/index")]
        refs.extend(ResourceRef(type="raw", location=f"s3://{bucket}/raw/{name}") for name in sorted(remaining))
        return refs
    names = {key.removeprefix("raw/") for key in store.list_objects(bucket, "raw/")}
    if not uploads and not removed:
        raise ValueError("files or remove_raw must be non-empty")
    remaining = (names | uploads.keys()) - removed
    if not remaining:
        for name in names & removed:
            store.delete_object(bucket, f"raw/{name}")
        _delete_published(store, bucket)
        return []
    additions = {name: content for name, content in uploads.items() if name not in removed}
    if additions:
        documents = _parse_documents(additions)
        refs = publish_resources(store, bucket, documents, incremental=bool(names), removed=removed)
    else:
        refs = remove_published_documents(store, bucket, removed)
    # 解析、向量构建及校验成功发布后才写 raw，失败不会留下待处理原文件。
    for name, content in additions.items():
        store.put_object(bucket, f"raw/{name}", content)
    for name in names & removed:
        store.delete_object(bucket, f"raw/{name}")
    refs.extend(ResourceRef(type="raw", location=f"s3://{bucket}/raw/{name}") for name in sorted(remaining))
    return refs


def _session_bucket(session_id: str) -> str:
    """校验会话 id 并推导会话桶名 res_<session_id>。"""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id is required")
    session_id = session_id.strip()
    if "/" in session_id or "\\" in session_id or session_id in {".", ".."}:
        raise ValueError(f"invalid session_id: {session_id!r}")
    return f"res_{session_id}"


def _validated_uploads(files) -> dict[str, bytes]:
    """整批校验上传文件名与内容，返回 filename -> bytes；先校验后写桶。"""
    uploads = {}
    for file in files:
        filename = getattr(file, "filename", None)
        content = getattr(file, "content", None)
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("files require non-empty filename")
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError(f"filename must not contain path separators: {filename!r}")
        if not isinstance(content, bytes) or not content:
            raise ValueError(f"file content must be non-empty bytes: {filename}")
        uploads[filename] = content
    return uploads


def _removed_names(remove_raw, bucket: str) -> set[str]:
    """校验 remove_raw 引用并取出要删除的 raw 文件名；type 或桶不匹配直接拒绝。"""
    removed = set()
    for ref in remove_raw:
        try:
            ref_type, location = ref["type"], ref["location"]
        except (TypeError, KeyError) as exc:
            raise ValueError("remove_raw entries require type and location") from exc
        if ref_type != "raw":
            raise ValueError(f"remove_raw only supports raw resources: {ref_type!r}")
        try:
            ref_bucket, key = parse_resource_path(location)
        except ValueError as exc:
            raise ValueError(f"invalid remove_raw location: {location!r}") from exc
        name = key.removeprefix("raw/") if key.startswith("raw/") else ""
        if ref_bucket != bucket or not name or "/" in name:
            raise ValueError(f"remove_raw must reference raw in session bucket: {location!r}")
        removed.add(name)
    return removed


def _delete_published(store: ObjectStore, bucket: str) -> None:
    """会话无剩余文件时清理桶内已发布产物，raw/ 此时已为空。"""
    store.delete_object(bucket, "documents.zip")
    store.delete_object(bucket, "manifest.json")
    for key in store.list_objects(bucket, "index/"):
        store.delete_object(bucket, key)


def _parse_documents(raws: dict[str, bytes]) -> list[InputDocument]:
    """全批次类型校验后逐个解析；任一文件解析失败则整个请求失败。"""
    for name in raws:
        processor.detect_file_type(file_type=None, filename=name)
    documents = []
    for name, content in raws.items():
        with BytesIO(content) as buffered:
            try:
                result = processor.process(UploadFileProxy(name, buffered))
            except Exception as exc:
                raise RuntimeError(f"document parsing failed for {name}: {exc}") from exc
        documents.append(InputDocument(filename=result.filename, html=result.html))
    return documents
