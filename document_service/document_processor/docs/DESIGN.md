# Document Processor 设计

`document_service.document_processor` 将上传文档转换为可供问答 agent 建树与前端预览的完整 HTML 文档。模块仅处理 PDF 与 DOCX（不抽取业务字段，不支持旧版 `.doc`），并将两种结构差异较大的管线拆分为独立子包：PDF 经 MinerU/OCR，DOCX 经 `python-docx`。

document service 的 gRPC 入口为 `DocumentResourceService.PrepareResources`：先调用本模块 `processor.process(...)` 解析，再由同级 `document_resources` 生成 Markdown 文件树与 embedding 索引并返回资源路径。本模块不单独暴露网络入口。

```text
file_obj (+ 可选 file_type)
  -> processor.process -> validate_file_obj -> resolve_filename -> detect_file_type
     |- pdf  -> _process_pdf -> pdf.convert_pdf_to_html (engine="mineru-pipeline")
     \- docx -> _process_docx -> docx.convert_docx_to_html (engine="python-docx")
  -> ProcessResult(filename, html)
```

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 入口分流与目录结构 | [design/entry-and-dispatch.md](design/entry-and-dispatch.md) | 文件树、`processor.py` 公开契约、共享校验辅助函数与引擎硬隔离原则 |
| PDF MinerU 管线与 HTML 规则 | [design/pdf-pipeline.md](design/pdf-pipeline.md) | `pdf/converter.py` CLI 配置、`pdf/html.py` 标题降级、确定性 block ID 与表格处理 |
| DOCX 解析管线与输出约束 | [design/docx-pipeline.md](design/docx-pipeline.md) | `docx/docx_processor.py` 原始顺序遍历、标题样式识别与 `docx_bNNN` 约束 |

## 相关入口

- 模块接口说明：[API.md](API.md) / 包说明：[README.md](../README.md)
- 上层服务与资源设计：[document_service/docs/DESIGN.md](../../docs/DESIGN.md) / [document_resources/docs/DESIGN.md](../../document_resources/docs/DESIGN.md)
