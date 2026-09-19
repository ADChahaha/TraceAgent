"""会话资源入口：上传合并 raw 后全量重建，纯删除裁剪已发布的文档与向量。

输入 session_id、files 和 remove_raw；校验文件名及引用归属后固定使用
res_<session_id> 桶。纯删除只列举 raw 名称，调用 remove_published_documents
剔除目标文档和索引行，发布成功后删除 raw；最后一个文件直接清空产物。
上传仍读回全部 raw、合并并先解析后发布；解析失败不改变桶。
返回 documents/index 及剩余 raw 的全量 ResourceRef；空会话返回 []。
构建或校验异常向上传递，发布仍逐对象执行，无远端回滚；同桶操作依赖调用方串行化。
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
    """上传全量重建、纯删除复用已发布产物，返回剩余资源引用。"""
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
    raws = _read_raws(store, bucket)
    if not uploads and not removed and not raws:
        raise ValueError("files or remove_raw must be non-empty")
    merged = dict(raws)
    merged.update(uploads)
    for name in removed:
        merged.pop(name, None)
    if not merged:
        for name in removed:
            store.delete_object(bucket, f"raw/{name}")
        _delete_published(store, bucket)
        return []
    # 解析先于任何写桶操作：解析失败时会话桶保持原状，坏文件不会成为
    # 事实来源毒化后续重建，也不会留下 remove_file 够不到的孤儿 raw。
    documents = _parse_documents(merged)
    for name in removed:
        store.delete_object(bucket, f"raw/{name}")
    for name, content in uploads.items():
        if name in merged:
            store.put_object(bucket, f"raw/{name}", content)
    refs = publish_resources(store, bucket, documents)
    refs.extend(ResourceRef(type="raw", location=f"s3://{bucket}/raw/{name}") for name in sorted(merged))
    return refs


def _session_bucket(session_id: str) -> str:
    """校验会话 id 并推导会话桶名 res_<session_id>。"""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id is required")
    session_id = session_id.strip()
    if "/" in session_id or "\\" in session_id or session_id in {".", ".."}:
        raise ValueError(f"invalid session_id: {session_id!r}")
    return f"res_{session_id}"


def _read_raws(store: ObjectStore, bucket: str) -> dict[str, bytes]:
    """读回桶内现有 raw 对象；读取端以桶内容为准，不依赖调用方传入全量文件。"""
    raws = {}
    for key in store.list_objects(bucket, "raw/"):
        data = store.get_object(bucket, key)
        name = key.removeprefix("raw/")
        if data and name:
            raws[name] = data
    return raws


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
