"""资源准备输入：解析器输出的文件名和 HTML。"""

from pydantic import BaseModel, ConfigDict
from dataclasses import dataclass


@dataclass(frozen=True)
class UploadedFile:
    """调用方上传的文件名和完整字节，不携带传输协议对象。"""

    filename: str
    content: bytes


class InputDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    html: str
