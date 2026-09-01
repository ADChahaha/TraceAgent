# `test_docx_processor.py`

这份测试覆盖 DOCX 解析行为。测试用 `python-docx` 在内存里生成真实
`.docx` 文件，只验证结构解析，不依赖 Word 渲染。

注意：这里不直接调用 DOCX 内部函数 `_process_docx`，而是通过统一入口
`processor.process(file_obj)` 触发 DOCX 分流。

## 实现链路

```text
BytesIO(.docx)
  -> processor.process(file_obj)  按 .docx 后缀分流到 DOCX 分支
  -> read_source_bytes(...) 读取 bytes 并复位
  -> python-docx Document(BytesIO(...))
  -> 按 Word body 原始顺序遍历 paragraph/table
  -> 只用 Word heading style 创建 section
  -> 普通 paragraph/table 保留原顺序生成 block
  -> 输出 ProcessResult(html/display_html/markdown/md_list/blocks/semantic_document)
```

## 测试函数

- `test_process_docx_builds_sections_from_word_heading_styles`：验证显式
  `Heading 1/2` 会创建嵌套 section，DOM id、table row evidence id、Markdown
  heading 和 `semantic_document` 都保持稳定顺序。
- `test_process_docx_without_heading_styles_keeps_flat_original_order`：验证没有
  heading style 的 DOCX 不做字体/粗体启发式猜测，段落和表格按原文顺序作为
  flat blocks 输出。
