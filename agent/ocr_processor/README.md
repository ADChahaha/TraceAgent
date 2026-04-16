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
├── processor.py
├── schemas.py
├── types.py
└── impl/
    ├── __init__.py
    ├── base.py
    ├── dispatcher.py
    ├── docling_adapter.py
    ├── doc/
    │   ├── __init__.py
    │   └── processor.py
    └── pdf/
        ├── artifacts/
        │   └── docling-models/
        ├── __init__.py
        └── processor.py
```

这样做的目的，是让外部调用时只需要关注顶层入口，而具体的多态实现各自收在自己的目录里。

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

- `processor_name`
- `file_type`
- `filename`
- `blocks`
- `meta_info`
- `warnings`

其中最重要的是 `blocks`。

## Content Block

`blocks` 是一个内容块列表，每个块至少包含：

- `text`
- `page_no`
- `bbox`
- `meta_info`

也就是：

```python
ContentBlock(
    text="...",
    page_no=1,
    bbox=BoundingBox(...),
    meta_info={...},
)
```

这样设计的原因是：

- `file_extraction` 只需要消费 `text`
- 前端高亮需要 `page_no + bbox`
- 不同文件类型可以共用一套外壳

## PDF 和 DOC/DOCX 的差异

统一结构不代表所有字段都必须有值。

### PDF

对于 `pdf`，理想情况下每个 `block` 应尽量保留：

- `text`
- `page_no`
- `bbox`

这样前端可以根据页码和边界框做高亮定位。

当前实现优先使用 `Docling` 做转换；如果当前环境下 `Docling` 的 PDF 管线不可用，则回退到 `pdfplumber` 提取行级文本和边界框。

返回结果中的 `meta_info["engine"]` 用于标识当前实际使用的处理链路：

- `docling_rapidocr`：Docling PDF 管线可用
- `pdfplumber_fallback`：Docling 不可用或未提取到文本时的回退链路

当前 PDF 处理默认使用本地 `Docling` artifacts，约定路径为：

- `agent/ocr_processor/impl/pdf/artifacts/docling-models`

也可以通过环境变量 `DOCLING_ARTIFACTS_PATH` 覆盖。

### DOC / DOCX

对于 `doc` 或 `docx`，可以先保证：

- `text`
- `meta_info`

如果没有稳定的页面或几何位置信息，则允许：

- `page_no = None`
- `bbox = None`

也就是说，PDF 的定位能力更强，DOC/DOCX 则先以文本为主。

当前实现中：

- `docx` 使用 `Docling`
- `pdf` 使用 `Docling + PyPdfium + RapidOCR`
- `doc` 老格式暂时未实现，会返回空块和 warning（`engine = "unimplemented"`）

## 为什么不拆成两套 API

当前不建议因为 PDF 有 `bbox`、DOC/DOCX 没有，就把外部 API 拆成两套。

原因是：

- 后续 `file_extraction` 主要只依赖 `text`
- 前端高亮只是附加需求
- 统一返回结构更容易在后端和前端之间流转

因此当前策略是：

- 统一返回 `blocks`
- PDF 在 block 上补充 `page_no` 和 `bbox`
- DOC/DOCX 没有时就为空

## 当前阶段的边界

当前阶段先把接口和结果结构固定下来，不急着一次性把所有字段设计完。

优先保证：

- 输入是文件对象
- 可以自动识别类型并分发
- 返回统一的 `ProcessResult`
- `block` 至少有 `text / page_no / bbox / meta_info`

当前已经使用 `Docling` 作为主要解析器，并在必要时对底层输出做映射和兜底。

## 当前处理链路

这一层在整体系统中的位置可以理解为：

`raw file -> ocr_processor -> ProcessResult(blocks) -> file_extraction`

其中：

- `ocr_processor` 负责生成文本块和可选定位信息
- `file_extraction` 负责基于这些文本块做真正的信息抽取
