"""storage 底层：本地目录对象存储（一个桶 = 数据根下的一个子目录）。

桶名走 S3 风格白名单（小写字母/数字/下划线/连字符，1-63 字符，无点号），
并在拼接后校验解析结果必须直接位于数据根下，杜绝 "." 等名字把桶解析到
数据根、越过目录隔离边界；key 必须是安全的桶内相对路径。
"""

from __future__ import annotations

import re
from pathlib import Path

BUCKET_NAME_RE = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")


class InvalidBucketName(ValueError):
    """桶名不在白名单内，或拼接后不落在数据根的直接子级。"""


class InvalidKey(ValueError):
    """key 为空、以桶目录为根解析或含逃逸路径。"""


class DirectoryObjectStore:
    """本地目录实现：一个桶 = 根目录下的一个子目录，key 即桶内相对路径。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _bucket_dir(self, bucket: str) -> Path:
        if not BUCKET_NAME_RE.fullmatch(bucket):
            raise InvalidBucketName(f"invalid bucket name: {bucket}")
        path = self.root / bucket
        if path.parent != self.root:
            raise InvalidBucketName(f"invalid bucket name: {bucket}")
        return path

    def create_bucket(self, bucket: str) -> None:
        self._bucket_dir(bucket).mkdir(parents=True, exist_ok=True)

    def _obj_path(self, bucket: str, key: str) -> Path:
        relative = Path(key)
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise InvalidKey(f"key must be a safe relative path: {key}")
        return self._bucket_dir(bucket) / relative

    def put_object(self, bucket: str, key: str, data: bytes) -> None:
        path = self._obj_path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_object(self, bucket: str, key: str) -> bytes | None:
        path = self._obj_path(bucket, key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def head_object(self, bucket: str, key: str) -> dict | None:
        path = self._obj_path(bucket, key)
        if not path.is_file():
            return None
        return {"size": path.stat().st_size}

    def delete_object(self, bucket: str, key: str) -> None:
        path = self._obj_path(bucket, key)
        if path.is_file():
            path.unlink()

    def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        bucket_dir = self._bucket_dir(bucket)
        if not bucket_dir.is_dir():
            return []
        keys: list[str] = []
        for path in bucket_dir.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(bucket_dir).as_posix()
            if key.startswith(prefix or ""):
                keys.append(key)
        return keys


__all__ = ["DirectoryObjectStore", "InvalidBucketName", "InvalidKey"]
