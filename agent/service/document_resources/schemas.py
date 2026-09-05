"""资源准备输入：解析器输出的文件名和 HTML。"""

from pydantic import BaseModel, ConfigDict


class InputDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    html: str
