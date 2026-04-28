last updated: 2026-04-28 14:19:45 CST

## 2026-04-28 14:19:45 CST
- completed work:
  - 清理 `routes/document_processor.py` 的边界依赖：route 层改为从公开 `service.document_processor.processor` 导入 `InvalidFileObjectError`，不再引用 `service.document_processor.impl.base`。
  - 为 document processor route 增加静态边界回归测试，固定 HTTP 适配层不依赖 `impl.*` 异常模块。
- current progress:
  - document processor route 继续只做 HTTP 协议适配，业务入口和异常契约由 `processor.py` 暴露。
  - 完整 agent 测试已通过：`126 passed, 2 warnings`。
- encountered problems:
  - 旧 route import 虽然运行时可用，但让 HTTP 层耦合内部实现文件，和 route 层只做协议适配的设计边界不一致。
- next step:
  - 后续如果扩展 route 错误处理，继续优先从公开业务入口或公开异常契约导入，不直接依赖 `impl/`。

## 2026-04-28 13:32:31 CST
- completed work:
  - 修复 `GET /v1/ocr/capabilities` 仍导入不存在 `docling_adapter` 的问题，改为复用当前 `impl/pdf/processor.py` 暴露的 docling 模型目录解析函数。
  - 为 capabilities route 增加回归测试，固定 `pdf/docx` 支持类型和 docling 模型目录返回行为。
- current progress:
  - `document_processor` 的 HTTP 能力查询接口已恢复可用，和 API 文档中的能力声明一致。
  - 真实文明寝室 PDF 端到端验证中，`document_processor` 输出 7 个 blocks、markdown 长度 6034。
- encountered problems:
  - capabilities route 保留了旧模块名，普通 process route 测试无法覆盖该 GET 路径。
- next step:
  - 后续如果继续调整 PDF 模型目录策略，需要同步维护 capabilities route 和 API 文档。

## 2026-04-27 18:59:19 CST
- completed work:
  - 新增 `document_processor/docs/API.md`，补齐 Python `process(...)`、HTTP `/v1/document-processor/process`、兼容旧路径 `/v1/ocr/process`、健康检查、能力查询、输入输出结构和失败语义说明。
  - 更新 `document_processor/README.md`、`document_processor/docs/DESIGN.md`、`agent/README.md` 和 `agent/docs/DESIGN.md`，让调用方能从顶层和包内入口找到 API 文档。
  - 修正 `document_processor/README.md` 中关于 `pdf/docx` 仍是占位实现的旧说法，改为说明当前已落地 `docling + RapidOCR` 与 `python-docx` 两条真实处理链路。
- current progress:
  - `document_processor` 的调用方文档已明确 `ProcessResult`、`ContentBlock`、PDF/DOCX 行为，以及它不负责生成 `file_extraction_agent` 所需 `block_id` 的边界。
- encountered problems:
  - 旧 README 和当前实现存在文档漂移，容易让调用方误判 PDF / DOCX 处理能力仍未落地。
- next step:
  - 后续如果扩展新文件类型，继续同步更新 API 文档中的支持类型、HTTP 请求字段和返回结构。

## 2026-04-24 12:33:50 CST
- completed work:
  - 修复 `document_processor.types._parse_file_type(...)` 对 `FileType` 枚举入参的处理，避免把 `FileType.PDF` 错误字符串化成 `"FileType.PDF"`。
  - 补充 `tests/document_processor/test_types.py` 覆盖显式传入 `FileType.PDF` 的入口行为，并同步更新对应测试说明文档。
- current progress:
  - `document_processor.process(file_obj, file_type=FileType.PDF)` 与 `file_type="pdf"` 现在应走同一条类型归一化路径。
- encountered problems:
  - 真实 PDF 联调时发现枚举入参会被误判为不支持类型，根因是 `_parse_file_type(...)` 没有优先识别已经归一化好的枚举对象。
- next step:
  - 后续如果扩展更多文件类型，继续优先保证字符串、带点后缀和枚举三类入口输入行为一致。

## 2026-04-19 21:55:00 CST
- completed work:
  - 复核 `document_processor` 与 `agent/routes/document_processor.py` 的当前接线状态，确认 FastAPI 已挂载 `/healthz`、`/v1/ocr/capabilities`、`/v1/ocr/process`。
  - 在 `agent-gate` 环境里实际验证 route 行为，确认 `document_processor` 的 Python 入口可用，但 route 侧当前不可用。
- current progress:
  - `document_processor` 当前应先视为“Python 入口可用、HTTP route 暂不可用”的状态，外部联调先不要依赖 `routes/document_processor.py`。
- encountered problems:
  - `POST /v1/ocr/process` 当前把 FastAPI `UploadFile` 包成不具备 `read()` 的代理对象，传入 `document_processor.process(...)` 后会在入口校验阶段返回 422，尚未真正接入处理链路。
  - `GET /v1/ocr/capabilities` 当前依赖不存在的 `document_processor.impl.pdf.docling_adapter`，不能作为稳定能力声明接口使用。
- next step:
  - 当前先不处理 route，后续如果要恢复外部 HTTP 接入，再单独按 TDD 修正协议适配层和相关测试。

## 2026-04-19 21:37:53 CST
- completed work:
  - 新增 `impl/pdf/processor.py` 和 `impl/pdf/__init__.py`，落地 `PDF -> docling + RapidOCR -> markdown + blocks` 的真实处理链路。
  - 把 `PDF` 默认 OCR 从 `OcrAutoOptions` 切换为显式 `RapidOcrOptions(backend="torch", lang=["chinese", "english"])`，并兼容需要 `document` 参数的节点 `export_to_markdown(...)`。
  - 把 `docling`、Hugging Face 和 `RapidOCR` 的默认模型目录统一收口到 `agent/document_processor/impl/pdf/models/`，同时增加 `.gitignore`，避免下载产物被直接提交进仓库。
  - 补齐 `tests/document_processor/test_pdf_processor.py`、`tests/document_processor/test_integration.py` 及对应文档，并加入真实 `pdf/docx` fixture。
  - 同步更新 `agent/README.md`、`document_processor/docs/DESIGN.md` 和相关测试文档。
  - 在 `agent-gate` 环境中验证 `python -m pytest tests/document_processor -q`，共 `34 passed`。
- current progress:
  - `document_processor` 的 `PDF` 路径已经可处理真实中文通知 PDF，默认模型目录固定在 `impl/pdf/models/`，不再依赖本机用户缓存路径。
- encountered problems:
  - `docling` 默认 OCR 对真实中文 PDF 效果很差，初始结果几乎只有图片占位；切到 `RapidOCR` 后正文和表格文本才恢复出来。
  - `RapidOCR` 和 Hugging Face 的下载产物一开始分别落在 `site-packages` 与用户缓存目录，后续通过显式模型目录和本地迁移才统一到包内 `models/`。
  - 使用非 `agent-gate` 解释器运行测试时，会看到旧代码路径和旧依赖行为，容易误判为当前实现仍然失败。
- next step:
  - 如果后续继续优化 `PDF` 效果，可优先从 OCR 质量、表格结构归一化和图片占位去除策略三条线继续细化。

## 2026-04-19 19:15:53 CST
- completed work:
  - 清理 `docs/DESIGN.md` 中已经与当前代码不一致的预留结构说明，删除 `impl/docling_blocks.py` 和 `impl/markdown_export.py` 两个未落地模块条目。
- current progress:
  - `document_processor` 的设计文档已和当前实现对齐，不再暗示存在尚未落地的 block 标准化 / markdown 导出公共模块。
- encountered problems:
  - 无。
- next step:
  - 继续在真实实现落地后再决定是否需要抽出共享的 block 标准化或 markdown 导出层。

## 2026-04-19 19:05:10 CST
- completed work:
  - 把 `impl/docx/processor.py` 的 `DOCX` 主实现从 `docling` 切换为 `python-docx`，直接遍历正文段落和表格并生成统一的 `markdown`、`md_list`、`blocks` 和 `meta_info`。
  - 删除了 `DOCX` 解析对 `docling` 和本机 LibreOffice 的运行时依赖，避免模板页脚文本框一类对象触发外部桌面程序转换。
  - 补齐 `tests/document_processor/test_docx_processor.py` 及对应文档，固定“当前实现使用 `python-docx`、不再暴露 `DocumentConverter`、默认文件名兜底”这几个约束。
  - 实际拿 `示例 DOCX 文件` 运行 `DocxProcessor`，成功输出解析结果，并写入 `agent/output/实验报告-模板.parsed.md`。
  - 在 `agent-gate` 环境中验证 `python -m pytest tests/document_processor/test_docx_processor.py -q` 和 `python -m pytest tests/document_processor -q`，共 `23 passed`。
- current progress:
  - `document_processor` 的 `DOCX` 链路已经稳定切换到 `python-docx`，可以直接处理当前实验报告模板这类文档。
- encountered problems:
  - 中途尝试保留 `docling` 并做 header/footer 预清洗，但这种方案仍然容易受 Word 内部 XML 细节影响，最终改为直接使用 `python-docx` 实现整条 `DOCX` 处理链路。
- next step:
  - 继续补 `PDF` 的真实处理器实现，并视需要细化 `DOCX` 标题识别、表格导出和 block 结构表达。

## 2026-04-19 18:23:36 CST
- completed work:
  - 新增 `impl/doc/processor.py`，落地 `DocxProcessor`，把 `DOCX` 文件对象交给 `docling` 解析，并统一产出 `markdown`、`md_list`、`blocks` 和 `meta_info`。
  - 调整 `impl/interface.py` 的默认注册逻辑，让 `FileType.DOCX` 指向新的 `DocxProcessor`，不再返回“未实现”的占位 warning。
  - 为 `tests/document_processor/test_processor.py` 增加真实 `DOCX -> docling` 解析测试，以及 `docling` 失败时直接抛错、没有回退逻辑的约束测试；同步更新测试文档和 `docs/DESIGN.md`。
  - 在 `agent-gate` 环境中验证 `python -m pytest tests/document_processor/test_processor.py -q` 和 `python -m pytest tests/document_processor -q`，共 `22 passed`。
- current progress:
  - `document_processor` 现在已经有可运行的 `DOCX` 真实处理链路，策略固定为“只走 `docling`，失败直接报错”。
- encountered problems:
  - 起始范围只允许改 `impl/doc/...`，但运行时默认注册入口还在 `impl/interface.py`，后续补齐最小必要范围后才让新处理器真正接入。
- next step:
  - 继续补 `PDF` 的真实处理器实现，并根据需要细化 block 标准化和 markdown 导出规则。

## 2026-04-19 18:03:00 CST
- completed work:
  - 把 `document_processor` 重构为“外层 `processor.py` 编排入口 + `impl/interface.py` 固定接口类 + `impl/base.py` 抽象基类 + 内部注册机制”的三层结构。
  - 删除旧的 `impl/dispatcher.py` 方向，改为由外层入口负责输入校验和文件类型推断，内部接口类只负责按 `FileType` 查找并调用已注册处理器。
  - 增加 `tests/document_processor/test_processor.py` 和对应文档，固定新的注册式多态入口行为；同步更新 `README.md`、`docs/DESIGN.md` 和测试说明文档。
  - 在 `agent-gate` 环境中验证 `tests/document_processor/test_processor.py` 和整个 `tests/document_processor/` 测试集均通过。
- current progress:
  - `document_processor` 的编排层、内部固定接口层和处理器基类层已经分清，外部调用方式稳定为统一 `process(...)` 入口。
- encountered problems:
  - 中途一度把输入校验、类型推断和注册逻辑混在内部接口类里，后来按职责重新拆回外层入口和内部接口层。
  - 旧文档里默认假设 `pdf/docx` 已经接入 Docling，已改成“当前是占位处理器，后续再补真实算法实现”的表述。
- next step:
  - 在 `impl/` 下补 `pdf/docx` 的真实处理器文件，并通过内部注册机制挂到固定接口类上。

## 2026-04-19 16:19:53 CST
- completed work:
  - 补上 `document_processor/types.py`，新增 `FileType`、`UnsupportedFileTypeError` 和 `infer_file_type(...)`。
  - 增加 `tests/document_processor/test_types.py`，固定显式类型规范化、按文件名扩展名推断和异常场景的行为。
  - 在 `agent-gate` 环境中验证 `test_types.py` 和 `test_schemas.py` 均通过。
- current progress:
  - `document_processor` 的 schema 层和文件类型推断层已经补齐，route 依赖的类型定义已有落地实现。
- encountered problems:
  - `types.py` 尚未存在时，新增测试在导入阶段直接失败；补上模块后问题消失，说明失败点与目标行为一致。
- next step:
  - 继续补 `processor.py` 和后续分发实现，把类型推断真正接到处理主入口。

## 2026-04-19 15:36:49 CST
- completed work:
  - 为 `document_processor` 建立了第一版 schema 契约，包括 `BoundingBox`、`ContentBlock`、`ProcessResult`。
  - 增加了 `tests/document_processor/test_schemas.py`，把 schema 的字段形状、默认值、容器隔离和 `asdict()` 序列化行为固定下来。
- current progress:
  - schema 层已经能支撑 route 读取返回值，相关测试通过。
- encountered problems:
  - 直接运行 `pytest` 时，本地包导入路径不稳定；改用 `python -m pytest` 后正常。
- next step:
  - 继续补 `types.py` 和 `processor.py`，把 schema 接到真正的处理入口上。
