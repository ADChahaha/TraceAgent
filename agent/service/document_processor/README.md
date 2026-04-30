# Document Processor

`service.document_processor` 负责把原始文档交给合适的内部处理器，并产出统一的 `ProcessResult`，供后续抽取或展示使用。

## 支持的文件类型

- `pdf`
- `docx`

当前不支持：

- `doc`

## Usage

更完整的调用方接口说明见 [`docs/API.md`](docs/API.md)。

```python
from service.document_processor.processor import process

result = process(file_obj, file_type=None)
```

其中：

- `file_obj` 建议传文件对象，而不是文件路径
- `file_type` 可省略；如果文件名可识别，会自动推断
- HTTP 入口是 `POST /v1/document-processor/process`，兼容旧路径 `POST /v1/ocr/process`

## 当前实现结构

当前代码已经落地的是三层结构：

```text
file_obj
  -> service.document_processor.processor.process(...)
  -> 外层入口做输入校验和文件类型推断
  -> impl/interface.py 里的 InternalProcessorInterface
  -> 内部注册表按 FileType 找到具体处理器
  -> 具体处理器继承 impl/base.py 里的 BaseDocumentProcessor
  -> ProcessResult
```

也就是说：

- `processor.py` 是外层编排入口
- `impl/interface.py` 是 `impl/` 内部固定接口类
- `impl/base.py` 是具体处理器的抽象基类
- 具体处理器通过内部注册机制接入，外部不能显式注入处理器实例

返回结果统一为 `ProcessResult`，主要包括：

- `file_type`
- `filename`
- `markdown`
- `md_list`
- `blocks`
- `meta_info`
- `warnings`

## PDF 配置速查

默认 PDF 链路是全平台通用实现，不依赖 macOS 专用 OCR。处理流程是：

```text
pdf file_obj
  -> docling
  -> RapidOCR
  -> onnxruntime backend
  -> markdown + blocks
```

推荐先用下面这组启动配置作为基线：

```bash
export DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND=onnxruntime
export DOCUMENT_PROCESSOR_RAPIDOCR_ONNX_USE_COREML=0
```

如果 PDF 自带的 OCR/text layer 质量很差，默认解析可能会优先吃到那层坏文本，表现为最后几页表格列错位、序号和学号粘连。此时可以强制 RapidOCR 整页重识别：

```bash
export DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR=1
```

这会增加一点 OCR 成本，但在 8 页扫描表格样本上仍能控制在 1 分钟内，并且能明显改善坏文本层导致的表格崩坏。密集表格列粘连时，还可以临时关闭 docling 的 cell matching 做对照：

```bash
export DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING=0
```

这个开关不建议默认开启，因为它可能让序号/学号列更清楚，但让“学院/作品类型”等宽列更容易错位。

这些环境变量在 `PdfProcessor` 初始化 `DocumentConverter` 时读取；如果服务已经启动，修改环境变量后通常需要重启 worker 才会生效。

### 默认 PDF / RapidOCR 环境变量

```text
上传的 PDF
  -> DOCUMENT_PROCESSOR_PDF_ENGINE 选择 PDF 引擎
  -> 默认 PdfProcessor 初始化 docling DocumentConverter
  -> RapidOCR 按 backend/device/batch/整页 OCR 配置运行
  -> docling 导出 markdown、table、text blocks
```

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DOCUMENT_PROCESSOR_PDF_ENGINE` | `docling` / `rapidocr` | PDF 引擎。默认走 `docling + RapidOCR`；可设为 `pdf-paddle` 或 `pdf-marker` 切到实验路径。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND` | `onnxruntime` | RapidOCR 后端。支持 `onnxruntime`、`openvino`、`paddle`、`torch`。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_ONNX_USE_COREML` | `0` | 仅 `onnxruntime` 后端使用。设为 `1` 会尝试 CoreML EP；当前样本上可用但更慢，所以默认关闭。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_TORCH_USE_MPS` | 跟随 `DOCUMENT_PROCESSOR_DOCLING_DEVICE=mps` | 仅 `torch` 后端使用。设为 `1` 时 RapidOCR torch 后端尝试走 MPS。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR` | `0` | 设为 `1` 时忽略 PDF 内置文本层并整页 OCR，适合坏文本层或扫描件表格。 |
| `DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING` | `1` | docling 表格 cell matching。设为 `0` 可做密集表格列粘连对照实验。 |
| `DOCUMENT_PROCESSOR_DOCLING_DEVICE` | docling 默认值 | 传给 docling `AcceleratorOptions.device`，常用值是 `cpu` 或 `mps`。 |
| `DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS` | docling 默认值 | 传给 docling `AcceleratorOptions.num_threads`，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_OCR_BATCH_SIZE` | docling 默认值 | 传给 docling `ocr_batch_size`，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_LAYOUT_BATCH_SIZE` | docling 默认值 | 传给 docling `layout_batch_size`，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_TABLE_BATCH_SIZE` | docling 默认值 | 传给 docling `table_batch_size`，必须是正整数。 |

模型和缓存目录默认会收口到 `impl/pdf/models/` 下，避免下载产物散落到用户目录：

| 环境变量 | 未设置时的默认目录 |
| --- | --- |
| `DOCLING_CACHE_DIR` | `impl/pdf/models/docling` |
| `RAPIDOCR_MODEL_ROOT` | `impl/pdf/models/rapidocr` |
| `HF_HOME` | `impl/pdf/models/huggingface` |

如果已经设置了 `HF_HOME`、`HF_HUB_CACHE` 或 `HUGGINGFACE_HUB_CACHE`，处理器不会覆盖 Hugging Face 缓存目录。

### 可选 PaddleOCR 环境变量

启用方式：

```bash
export DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-paddle
```

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DOCUMENT_PROCESSOR_PADDLE_OCR_VERSION` | `PP-OCRv4` | PaddleOCR PPStructureV3 使用的 OCR 版本；`PP-OCRv5` 通常更重、更慢。 |
| `PADDLE_PDX_CACHE_HOME` | `impl/pdf/models/paddlex` | PaddleX / PaddleOCR 模型缓存目录。 |

PaddleOCR 路径需要额外安装 `agent-service[paddle]`，主要用于对比密集表格质量，不是默认生产路径。

### 可选 Marker 环境变量

启用方式：

```bash
export DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-marker
```

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DOCUMENT_PROCESSOR_MARKER_FORCE_OCR` | `1` | Marker 强制 OCR。 |
| `DOCUMENT_PROCESSOR_MARKER_DISABLE_MULTIPROCESSING` | `1` | 关闭 Marker 多进程，减少本地联调不稳定因素。 |
| `MODEL_CACHE_DIR` | `impl/pdf/models/marker` | Marker / Surya 模型缓存目录。 |
| `HF_HOME` | `impl/pdf/models/marker/huggingface` | Marker 路径下 Hugging Face 缓存目录；如果外部已设置则不覆盖。 |
| `XDG_CACHE_HOME` | `impl/pdf/models/marker/xdg` | Marker 相关 XDG 缓存目录。 |

Marker 质量通常更好但很慢，并且 `marker-pdf` 的依赖会和项目主依赖 `openai>=2.28,<3` 冲突。生产上如果要用，建议放到隔离环境或 sidecar runtime。

## 当前行为说明

- 当前 `pdf` 和 `docx` 已经有内部注册入口和真实处理器
- `pdf` 固定走 `docling + RapidOCR`
- 如果启动前设置 `DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-paddle`，`pdf` 会改走 `pypdfium2 + PaddleOCR PPStructureV3`，输出结构化 markdown；识别到表格时生成 `kind="table"` blocks，普通文字生成 `kind="text"` blocks；该路径需要额外安装 `agent-service[paddle]`，模型默认缓存到 `impl/pdf/models/paddlex/`
- 如果启动前设置 `DOCUMENT_PROCESSOR_PDF_ENGINE=pdf-marker`，`pdf` 会改走 `Marker/marker-pdf`，优先追求扫描件和密集表格的 markdown 质量；该路径需要单独安装 Marker，建议放在隔离环境或 sidecar 中，模型默认缓存到 `impl/pdf/models/marker/`
- `docx` 固定走 `python-docx`
- 输出的 `blocks` 不包含 `block_id`；如果要继续交给 `service.file_extraction_agent`，应由 backend 或 session 聚合层补齐稳定唯一 `block_id`
- `.doc` 当前仍不支持

## 当前阶段说明

这一层现在已经把“外层编排 / 内部固定接口 / 具体处理器基类 / 注册式扩展”这套结构固定下来，并落地了 PDF / DOCX 两条真实解析链路。后续增加新文件类型时，应直接在 `impl/` 下增加具体处理器类，并通过内部注册机制挂到 `InternalProcessorInterface` 上，而不是回到手写分支分发。
