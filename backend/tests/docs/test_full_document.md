# test_full_document.py

- `test_full_document_returns_ordered_blocks_of_only_selected_document`：通过 HTTP 和内存对象存储构造乱序、多文档归档；验证引用块或文档目录均返回同一整份文档，Markdown 原样保留、按数字顺序排列且不混入其他文档。缺失文档与跨会话访问返回 404，越界路径返回 422。
