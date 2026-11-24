# DOCX 解析管线与输出约束

返回 [Document Processor 设计](../DESIGN.md)。

## 执行流程

`docx/docx_processor.py` 对外暴露单一函数 `convert_docx_to_html(source_bytes)`：

```text
上传的 .docx file_obj
  -> processor.process(...) 完成 file-like 校验、文件名解析与类型分流
  -> _process_docx(file_obj, filename) 读取 bytes 并复位文件指针
  -> docx.convert_docx_to_html(source_bytes)
  -> python-docx 打开 Document(BytesIO(bytes))
  -> iter_block_items(document) 按 document.element.body 原始顺序遍历 paragraph 与 table
  -> 空文本 paragraph 跳过
  -> paragraph style.name 匹配 Heading N / 标题 N / 見出し N -> 生成 heading block
  -> 非 heading paragraph -> 生成 docx_bNNN paragraph block 保留原顺序
  -> table -> 生成 docx_bNNN table block 保留原顺序
  -> 生成带 CSS 的完整 HTML 文档，返回 ProcessResult(filename, html)
```

## 标题与输出约束

- 刻意不根据字号、加粗或手工排版猜测标题；只有显式 Word heading 样式才会生成 heading block，无标题样式文档输出为扁平有序的 paragraph/table 列表。
- DOCX 没有稳定的页码与 bbox，块 ID 只表达文档内顺序（如 `docx_b001`、`docx_b002`）。
- `html` 是带 CSS 的完整 HTML 文档：前端可直接渲染，同时保留 `h1-h6`/`p`/`ul`/`ol`/`table` 骨架供文档树构建；`ProcessResult` 仅保留 `filename` 与 `html`。
