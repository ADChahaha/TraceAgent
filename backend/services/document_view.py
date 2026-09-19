"""会话归档与引用 key -> 按原文顺序读取同一文档的全部 Markdown 块。"""

import io
import re
import zipfile

from backend.services.errors import NotFoundError, ValidationError


def full_document(archive: bytes, key: str) -> dict:
    parts = key.split("/")
    if len(parts) < 2 or parts[0] != "documents" or any(part in {"", ".", ".."} for part in parts):
        raise ValidationError("无效的文档路径")
    root = "/".join(parts[:2])
    with zipfile.ZipFile(io.BytesIO(archive)) as members:
        names = [name for name in members.namelist()
                 if name.endswith(".md") and (name == root or name.startswith(root + "/"))]
        if not names:
            raise NotFoundError("文档不存在")
        names.sort(key=lambda name: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)])
        return {"key": root, "blocks": [{"key": name, "text": members.read(name).decode("utf-8")} for name in names]}
