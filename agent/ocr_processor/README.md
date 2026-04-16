# OCR Processor Design

## 目标

`ocr_processor` 负责接收原始文档文件对象，对其进行预处理，并输出后续 `file_extraction` 可以直接消费的内容。

这一层的重点不是直接做字段抽取，而是：

- 把原始文件转换成统一的文本块结构
- 在可能的情况下保留原文定位信息
- 为前端高亮和后续抽取同时服务

## 支持的输入

当前设计上支持：

- `pdf`
- `doc`
- `docx`

输入形式优先为**文件对象**，而不是路径。

这样做的原因是：

- 更容易和 FastAPI 的 `UploadFile` 对接
- 不强依赖本地文件路径
- 后续也更容易接 storage、内存流或内部下载结果

## 目录结构

当前目录分为两层：

- 顶层保留公共接口和公共数据结构
- `impl/` 里放具体实现

```text
agent/ocr_processor/
├── README.md
├── pyproject.toml
├── processor.py
├── schemas.py
├── types.py
└── impl/
    ├── __init__.py
    ├── base.py
    ├── dispatcher.py
    ├── doc/
    │   ├── __init__.py
    │   ├── docling_adapter.py
    │   └── processor.py
    └── pdf/
        ├── artifacts/
        │   └── docling-models/
        ├── __init__.py
        ├── docling_adapter.py
        └── processor.py
```

这样做的目的，是让外部调用时只需要关注顶层入口，而具体的多态实现各自收在自己的目录里。

当前 `ocr_processor` 作为独立 Python 包维护，包配置位于：

- `agent/ocr_processor/pyproject.toml`

注意：

- `agent/ocr_processor/impl/pdf/artifacts/` 是本地模型目录约定，不是仓库内置资源
- 该目录被 `.gitignore` 忽略，用户需要自行准备 Docling PDF artifacts
- 也可以通过环境变量 `DOCLING_ARTIFACTS_PATH` 指向自己安装好的模型目录

## 处理方式

这一层内部采用“类型分发”的方式。

对外则提供一个统一入口：

```python
from ocr_processor.processor import process

result = process(file_obj)
```

默认情况下，`process(file_obj)` 会根据文件对象中的信息自动判断类型并分发。

如果后续有特殊需要，也可以显式指定类型。

也就是内部仍然是：

1. 上层调用时明确传入 `file_type`
2. `ProcessorDispatcher` 根据类型分发
3. 不同类型走不同处理逻辑

当前设计可以理解为：

- `pdf -> PdfProcessor`
- `doc/docx -> DocProcessor`

这样做的好处是：

- 分支清楚
- 行为可控
- 后续替换单个处理器不会影响整个接口
- 对外仍然可以保持一个简单的 `process(file_obj)` 调用方式

## 统一返回结构

虽然不同文件类型的处理细节不同，但当前约定统一返回一个 `ProcessResult`。

`ProcessResult` 的核心内容是：

- `file_type`
- `filename`
- `md_list`
- `markdown`
- `blocks`
- `meta_info`
- `warnings`

其中最重要的是 `blocks`、`md_list` 和 `markdown`。

## Content Block

`blocks` 是一个内容块列表，每个块至少包含：

- `text`
- `page_no`
- `bbox`
- `kind`
- `meta_info`

也就是：

```python
ContentBlock(
    text="...",
    page_no=1,
    bbox=BoundingBox(...),
    kind="text",
    meta_info={...},
)
```

这样设计的原因是：

- `file_extraction` 只需要消费 `text`
- 前端如果需要定位能力，可以继续使用 `page_no + bbox`
- 不同文件类型可以共用一套外壳

## Markdown 输出

除了 block 列表，当前 `ProcessResult` 还会提供一份整篇 `markdown`，用于前端展示处理后的文档内容。

当前规则是：

- 普通 `text` block 直接按段落拼接
- `table` block 原样保留 Markdown 表格
- 其他语义类型可以继续在 block 级别扩展，再映射到 Markdown
- `md_list` 默认与归一化后的 `blocks` 一一对应

这意味着：

- `pdf/docx` 都可以直接输出标准化阅读视图
- 前端可以直接消费 `md_list` 或整篇 `markdown`
- `pdf` 如果后续仍需要原页定位，也可以继续额外使用 `page_no + bbox`

## PDF 和 DOC/DOCX 的差异

统一结构不代表所有字段都必须有值。

### PDF

对于 `pdf`，理想情况下每个 `block` 应尽量保留：

- `text`
- `page_no`
- `bbox`

这样前端可以根据页码和边界框做高亮定位。

当前实现优先使用 `Docling` 做转换；如果当前环境下 `Docling` 的 PDF 管线不可用，则回退到 `pdfplumber` 提取行级文本和边界框。

当前 PDF 映射中还做了一层轻量 bbox 修正：

- 如果 Docling 返回的文本框高度异常小，会在对应页面图像中局部搜索深色像素，重新收缩出更接近真实文字区域的矩形框
- 这一步主要改善扫描 PDF 上“框压在文字中线”的情况
- 会先把明显越出页面边界的 bbox 丢弃，并清理页脚/印章区域的短小噪声框
- 对表格页，会对 table bbox 做一层向下扩张的抑制，尽量吃掉“本来属于表格、但 OCR 框略微漏出表格底边”的碎文本框
- 对非表格碎片化 OCR，后续仍可继续做更细的聚合/过滤

当前 PDF 还会在 table structure artifacts 可用时保留表格语义：

- 会开启 Docling 的 table structure 分析
- 整张表会输出为 `kind = "table"` 的 block
- `block.text` 直接保存表格 Markdown，便于下游抽取和检索
- `block.meta_info` 会补 `row_count` / `column_count` / `format = "markdown"`
- 落在 table bbox 内的普通文本块会被抑制，避免前端高亮时出现整表框和碎文字框重叠

当前 PDF 处理默认使用本地 `Docling` artifacts，约定路径为：

- `agent/ocr_processor/impl/pdf/artifacts/docling-models`

仓库不会提交这套模型；需要用户自行安装到上述目录，或通过环境变量 `DOCLING_ARTIFACTS_PATH` 覆盖到自己的模型路径。

### DOC / DOCX

对于 `doc` 或 `docx`，可以先保证：

- `text`
- `meta_info`

如果没有稳定的页面或几何位置信息，则允许：

- `page_no = None`
- `bbox = None`

也就是说，PDF 的定位能力更强，DOC/DOCX 则先以文本为主。

当前实现中：

- `docx` 默认使用 `Docling`
- 如果 `docx` 的 Docling 管线失败，或成功但未产出任何 block，则回退到 python-docx 结构抽取
- `pdf` 使用 `Docling + PyPdfium + RapidOCR`
- `doc` 老格式当前未实现，返回空块和 warning
- `docx` fallback 和 `doc` 当前都不提供稳定的页码和几何位置信息，因此返回 `page_no = None`、`bbox = None`

## Docling Block 转换

当前 `pdf/docx` 的主思路是：

1. 先尽量把文件转换成 `DoclingDocument`
2. 优先用 `iterate_items()` 按阅读顺序遍历 Docling items
3. 把 `title / section_header / text / list_item / table` 映射成我们的 `ContentBlock`
4. 过滤 `page_header / page_footer / picture` 等高噪声元素
5. 再导出 `md_list` 和整篇 `markdown`

## 为什么不拆成两套 API

当前不建议因为 PDF 有 `bbox`、DOC/DOCX 没有，就把外部 API 拆成两套。

原因是：

- 后续 `file_extraction` 主要只依赖 `text`
- 前端高亮只是附加需求
- 统一返回结构更容易在后端和前端之间流转

因此当前策略是：

- 返回最小可用字段：`file_type / filename / md_list / markdown / blocks / meta_info / warnings`
- PDF 在 block 上补充 `page_no` 和 `bbox`
- PDF 表格使用 `kind = "table"`，并把 Markdown 放进 `text`
- DOC/DOCX 没有时就为空

## 当前阶段的边界

当前阶段先把接口和结果结构固定下来，不急着一次性把所有字段设计完。

优先保证：

- 输入是文件对象
- 可以自动识别类型并分发
- 返回统一的 `ProcessResult`
- `block` 至少有 `text / page_no / bbox / kind / meta_info`

当前已经使用 `Docling` 作为主要解析器，并在必要时对底层输出做映射和兜底。

## 当前处理链路

这一层在整体系统中的位置可以理解为：

`raw file -> ocr_processor -> ProcessResult(blocks + md_list + markdown) -> file_extraction`

其中：

- `ocr_processor` 负责生成文本块和可选定位信息
- `file_extraction` 负责基于这些文本块做真正的信息抽取
