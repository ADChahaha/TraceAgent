"""具体文档处理器的抽象基类。

实现步骤：

```text
具体文件处理器继承 BaseDocumentProcessor
  -> 外部或内部接口类调用 processor.process(file_obj)
  -> 基类先检查 file_obj 是否至少有可调用的 read()
  -> 输入合法时，把真正处理工作委托给子类实现的 _process(file_obj)
  -> 子类只需要专注“拿到一个文档之后怎么处理”
  -> 最终返回统一的 ProcessResult
```
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from document_processor.processor import InvalidFileObjectError


class BaseDocumentProcessor(ABC):
    """所有具体文件处理器都必须继承的抽象基类。"""

    def process(self, file_obj):
        self.validate_file_obj(file_obj)
        return self._process(file_obj)

    @abstractmethod
    def _process(self, file_obj):
        """由具体文件处理器实现真实的单文档处理逻辑。"""

    @staticmethod
    def validate_file_obj(file_obj) -> None:
        """确保输入对象提供了这里所需的最小 file-like 接口。"""

        read_method = getattr(file_obj, "read", None)
        if not callable(read_method):
            raise InvalidFileObjectError(
                "Expected a file-like object with a callable read() method."
            )
