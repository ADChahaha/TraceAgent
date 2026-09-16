"""会话资源入口：以会话桶内的 raw 对象为事实来源，增量合并后全量重建发布。

prepare_session_resources 是 PrepareResources 的业务入口：bucket 固定为
res_<session_id>。每次调用的真实流程是：

```text
输入 session_id + files(上传文件) + remove_raw(要移除的 raw 引用)
  -> 校验 session_id 并推导 bucket = res_<session_id>
  -> 从桶内读回 raw/* 作为现有文件集（桶是事实来源）
  -> 校验新文件（文件名非空且不含路径分隔符、内容非空）并按文件名覆盖合并
  -> 校验 remove_raw（type 必须为 raw、location 必须属于本会话桶），
     对桶内同名 raw 执行 delete_object，目标不存在则幂等跳过
  -> 剩余为空：删除桶内 documents.zip、manifest.json、index/*，返回 []
  -> 否则全批次类型校验（PDF/DOCX）后逐个解析为 HTML
  -> resources.publish_resources 在同一桶内重建 documents.zip 与 index
  -> 返回 documents/index 加全部剩余 raw 的资源定位数组
```

解析失败包装 RuntimeError 并标明文件名；调用参数只接收普通 Python 数据。
当前没有远端回滚或原子发布：重建失败可能留下新写入的 raw 对象，会在下一次
调用时随桶内容合并恢复；同一桶并发调用存在读改写竞争，依赖调用方串行化。
"""

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from traceagent_shared.object_store import ObjectStore, ResourceRef, build_s3_object_store, parse_resource_path
from document_service.document_processor import processor
from document_service.document_resources.resources import publish_resources
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
    """应用会话桶内的增删并全量重建，返回资源定位数组。"""
    bucket = _session_bucket(session_id)
    store = store if store is not None else build_s3_object_store()
    raws = _read_raws(store, bucket)
    removed = _removed_names(remove_raw, bucket)
    uploads = _validated_uploads(files)
    if not uploads and not removed and not raws:
        raise ValueError("files or remove_raw must be non-empty")
    raws.update(uploads)
    for name in removed:
        raws.pop(name, None)
        store.delete_object(bucket, f"raw/{name}")
    for name, content in uploads.items():
        if name in raws:
            store.put_object(bucket, f"raw/{name}", content)
    if not raws:
        _delete_published(store, bucket)
        return []
    documents = _parse_documents(raws)
    refs = publish_resources(store, bucket, documents)
    refs.extend(ResourceRef(type="raw", location=f"s3://{bucket}/raw/{name}") for name in sorted(raws))
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
