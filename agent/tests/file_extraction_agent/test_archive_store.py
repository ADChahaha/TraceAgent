"""ArchiveObjectStore / CompositeObjectStore：zip 内存对象存储与按前缀路由。"""

from __future__ import annotations

import io
import zipfile

from service.object_store import ArchiveObjectStore, CompositeObjectStore


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for key, text in files.items():
            archive.writestr(key, text)
    return buffer.getvalue()


def test_archive_store_lists_and_reads_members_without_disk():
    store = ArchiveObjectStore("res_x", _zip_bytes({
        "documents/a/1.md": "hello",
        "documents/b/2.md": "world",
    }))

    assert store.get_object("res_x", "documents/a/1.md") == b"hello"
    assert store.get_object("res_x", "documents/missing.md") is None
    assert store.get_object("other", "documents/a/1.md") is None
    assert store.list_objects("res_x", prefix="documents/a") == ["documents/a/1.md"]
    assert sorted(store.list_objects("res_x")) == ["documents/a/1.md", "documents/b/2.md"]
    assert store.list_objects("other") == []


class _RecordingStore:
    def __init__(self) -> None:
        self.gets: list[tuple[str, str]] = []
        self.lists: list[tuple[str, str]] = []

    def get_object(self, bucket: str, key: str) -> bytes | None:
        self.gets.append((bucket, key))
        return b"s3"

    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        self.lists.append((bucket, prefix))
        return ["index/index.json"]


def test_composite_store_routes_documents_to_archive_and_rest_to_default():
    archive = ArchiveObjectStore("res_x", _zip_bytes({"documents/a/1.md": "hello"}))
    default = _RecordingStore()
    store = CompositeObjectStore(archive, default)

    assert store.get_object("res_x", "documents/a/1.md") == b"hello"
    assert store.get_object("res_x", "index/vectors.npy") == b"s3"
    assert default.gets == [("res_x", "index/vectors.npy")]
    assert store.list_objects("res_x", prefix="documents/a") == ["documents/a/1.md"]
    assert default.lists == []
