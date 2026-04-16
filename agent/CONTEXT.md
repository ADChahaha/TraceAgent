# Agent Context (handoff-ready)

> 最后更新：2026-04-17
> 目标：让任何新接入的 LLM/开发者在 2-5 分钟内理解当前 `agent/` 的状态并继续工作。

## 0) 项目总览

- 项目名：`agent_gate`
- 当前聚焦：`agent/` 服务的 OCR 预处理链路落地与稳定化，输出契约开始向 Markdown 优先的最小可用结构收敛
- 主模块：`ocr_processor`（预处理/OCR）与 `file_extraction_agent`（抽取，待完善）
- 主链路：`raw file -> ocr_processor -> ProcessResult(blocks + md_list + markdown) -> file_extraction_agent`
- 当前支持：`pdf`、`docx`；`doc` 明确未实现
- PDF 默认模型路径：`agent/ocr_processor/impl/pdf/artifacts/docling-models`
- 当前状态：`ocr_processor` 关键用例可跑通，返回契约已扩展到 `blocks + md_list + markdown + meta_info`，PDF 表格会输出 `kind="table"` + Markdown，`docx` 在 Docling 失败时可回退到 python-docx；FastAPI 入口已移到包外的 `agent/routes/`，并明确作为独立于业务接口的 HTTP 适配层存在

## 1) 当前目标与边界

`agent` 负责文档处理链路，分为两段：

- `ocr_processor`：文档预处理/OCR，输出统一 `ProcessResult(blocks + md_list + markdown)`
- `file_extraction_agent`：消费预处理结果做抽取（后续完善）
- `ocr_processor/README.md` 已明确写出安装方式、PDF artifacts 前提，以及 `.doc` 当前不支持

系统职责边界：

- `agent` 不直接查 backend DB，不直接管 backend storage
- 与 backend 通过 API 交互（任务输入/文件读取/结果回传）

## 2) 最近关键决策（已落地）

### 包导入与打包约定

已确认并落地：

- 除 `__init__.py` 外，模块内部统一使用绝对导入
- `ocr_processor` 使用独立的 `agent/ocr_processor/pyproject.toml`
- `agent/pyproject.toml` 负责 `agent` 层 FastAPI 入口依赖与 `routes` 打包，并同步打包 `ocr_processor`，保证 `agent-service` 单独安装时也能启动
- `ocr_processor` 的 FastAPI 入口移到包外的 `agent/routes/`，避免把 HTTP 层塞回业务包
- `docling_blocks.py` 和 `markdown_export.py` 已收进 `ocr_processor/impl/`，明确它们属于内部实现逻辑
- `ocr_processor` 同时保留两套并行接口：业务层 `process(...)` 和 route 层 `routes/ocr_processor.py`
- route 层只负责请求/响应映射，不直接把业务 dataclass 当成 HTTP 契约
- `ocr_processor/__init__.py` 改为惰性导出，避免 import 内部小模块时被迫加载整条 OCR 处理链和 `docling` 依赖
- `processor/dispatcher/docling_adapter` 现在统一按需导入 `docling`，保证 `main`、route 层和健康检查不被 OCR 依赖劫持
- `ocr_processor` 根包不再导出 `build_markdown_from_blocks` 这类内部 helper
- `agent/pyproject.toml` 现已补齐 `fastapi` / `python-multipart` / `uvicorn`，`agent-gate` 环境已通过 editable install 安装 `agent-service` 与 `ocr-processor`
- `agent-service` 当前同时声明 `docling` / `pdfplumber` / `python-docx` 依赖，并把 `main.py` 与 `ocr_processor` 一起纳入构建产物，避免单独安装后缺包

### PDF artifacts 路径归属

已确认并落地：PDF 的 Docling 本地模型目录按模块归属放在：

- `agent/ocr_processor/impl/pdf/artifacts/docling-models`

补充约定：

- 该目录是本地安装位置，不随仓库提交
- `agent/.gitignore` 已忽略 `artifacts/`
- 运行方需要自行准备 Docling PDF artifacts，或设置 `DOCLING_ARTIFACTS_PATH`

对应代码默认路径：

- `ocr_processor/impl/pdf/docling_adapter.py` 中 `_DEFAULT_DOCLING_ARTIFACTS_PATH`

对应文档已同步：

- `ocr_processor/README.md`

### 为什么这样改

- 只有 PDF 管线依赖这套 artifacts（DOCX 不依赖该本地模型目录）
- 放到 `impl/pdf` 下语义更清晰，避免顶层目录混乱

## 3) 当前处理行为（重点）

### 输入类型

- 支持：`pdf` / `doc` / `docx`
- 业务入口：`ocr_processor.processor.process(file_obj, file_type=None)`

### API 层

- 路由入口：`agent/routes/ocr_processor.py`
- 响应 schema：当前直接定义在 `agent/routes/ocr_processor.py`
- 当前职责：`UploadFile` 适配、HTTP 错误码映射、`ProcessResult` -> HTTP response 显式转换
- 设计约束：不让 FastAPI/Pydantic 反向塑造业务层接口

### 输出结构

统一输出 `ProcessResult`，核心字段：

- `file_type`
- `filename`
- `md_list`（按 block 切分的 Markdown 列表）
- `markdown`（整篇标准化 Markdown，供前端展示）
- `blocks`（每块至少 `text/page_no/bbox/meta_info`）
- `meta_info`（`engine / fallback_used / kind_counts / has_table` 等摘要信息）
- `warnings`

当前这轮按 TDD 推进：

- `red`：先新增最小字段契约测试，确认旧结构因 `processor_name/meta_info` 失败
- `green`：移除顶层冗余字段，并补齐 `md_list / meta_info`
- `refactor`：补齐 README、AGENT 协作约定、Docling block 转换层、真实文件验证测试

### PDF 处理链路

- 首选：Docling + RapidOCR
- 回退：pdfplumber
- Docling item 会先转换成统一 `ContentBlock`，再做 PDF 专属 bbox 精修和噪声过滤
- 当 Docling 返回的高层文本框高度异常小时，会基于页面图像做一次局部 bbox 精修
- 如果本地 Docling artifacts 中包含 table structure 模型，则会开启表格结构分析，并把整表输出成 `kind="table"` block
- table block 的 `text` 直接使用 Markdown，`meta_info` 中会补 `row_count` / `column_count`
- 当前默认会压掉落在 table bbox 内的普通 text blocks，避免前端高亮时出现“整表大框 + 表内碎框”双重噪声

### DOC/DOCX 处理链路

- `docx`：默认 Docling；若 Docling 失败则回退到 python-docx 结构抽取
- `doc`：显式返回空 blocks + warning
- `docx` 在 Docling 成功时与 `pdf` 共用一套 Docling item -> block 转换逻辑

## 4) 测试状态（已验证）

在 `agent-gate` conda 环境下，`ocr_processor` 测试通过：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_processor.py -q`
- 结果：`10 passed`

新增 PDF `docling_adapter` 单测：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_pdf_docling_adapter.py -q`
- 结果：`6 passed`

新增 Markdown 导出单测：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_markdown_export.py -q`
- 结果：`2 passed`

新增 Docling block 转换单测：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_docling_blocks.py -q`
- 结果：`1 passed`

新增真实文件文档测试：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_sample_documents.py -q`
- 结果：`2 passed`

并且已验证 PDF 可产出 bbox（含扫描 PDF 场景）。

真实样本验证（2026-04-16）：

- `实验报告-模板.docx` 当前输出包含 `md_list` 和 `meta_info`，样本上因 Docling 失败会回退到 `python-docx`
- `daa1d114-5c04-45d2-82b3-16bb8dc57206.pdf` 当前可稳定产出 Docling-based blocks，实测约 `9` 个 blocks、`9` 个 md items、`1695` 字符 Markdown，并保留教师名单表格的 Markdown 结构
- PDF `bbox` 能力仍保留，但当前主展示方向已转为 Markdown 优先

## 5) 最近提交（与当前上下文相关）

- `ef12230` `fix(ocr): move docling artifacts path under impl/pdf`
- `e976b18` `docs(ocr): align README with current pdf artifacts layout`
- `ce96674` `test(agent): cover scanned pdf bbox extraction`
- `6857f1b` `test(agent): define legacy doc extraction behavior`
- `fdd9389` `feat(agent): support legacy doc extraction via textutil`
- `74a9671` `docs: sync agent context and TDD guidance`
- `28dd171` `test(agent): mark legacy doc as unimplemented again`
- `e9cc347` `fix(agent): revert legacy doc to explicit unimplemented`
- `981e119` `test(agent): define docx fallback on docling failure`
- `eea2f70` `fix(agent): add docx fallback for docling failures`
- `114bdf4` `test(agent): define pdf bbox image refinement behavior`
- `21fe8fb` `test(agent): define table block extraction behavior`
- `1bf2a8f` `test(agent): define pdf noise filtering behavior`

## 5.1) 本轮未提交改动（2026-04-17）

- 新增：`routes/ocr_processor.py`
- 新增：`routes/__init__.py`
- 新增：`ocr_processor/impl/docling_blocks.py`
- 新增：`ocr_processor/impl/markdown_export.py`
- 删除：`ocr_processor/api/router.py`
- 删除：`ocr_processor/api/schemas.py`
- 删除：`ocr_processor/api/__init__.py`
- 删除：`ocr_processor/docling_blocks.py`
- 删除：`ocr_processor/markdown_export.py`
- 调整：`main.py` 改为从 `routes` 挂载路由
- 调整：`agent/pyproject.toml` 增加 `fastapi` / `python-multipart` 依赖，并把 `routes` 纳入打包
- 调整：`agent/pyproject.toml` 进一步增加 `uvicorn` 依赖，用于直接启动本地 API 服务
- 调整：`agent/pyproject.toml` 把 `ocr_processor`、其子包和 `main.py` 一并纳入 `agent-service` 构建产物
- 调整：`agent/pyproject.toml` 补齐 `docling` / `pdfplumber` / `python-docx` 依赖，保证 `agent-service` 单独安装即可运行 OCR 链路
- 调整：`ocr_processor/pyproject.toml` 去掉不再需要的 `api` extra
- 调整：`processor.py`、`impl/dispatcher.py`、`impl/doc|pdf/__init__.py` 改为懒导入，切断启动时对 `docling` 的硬依赖
- 调整：`impl/doc/docling_adapter.py`、`impl/pdf/docling_adapter.py` 改为函数内导入 `docling`
- 调整：`routes/ocr_processor.py` 不再在模块加载时直接 import OCR 主链路或 PDF Docling adapter
- 调整：`ocr_processor/__init__.py` 去掉内部 markdown helper 的公共导出
- 修复：`impl/pdf/docling_adapter.py` 中 `convert_pdf_with_docling()` 对 `_load_docling_pdf_modules()` 的错误解包，恢复 Docling PDF 主链路
- 新增：`tests/ocr_processor/test_pdf_docling_adapter.py` 回归测试，覆盖 `convert_pdf_with_docling()` 可接受完整模块元组返回值
- 调整：`routes/ocr_processor.py` 通过显式适配函数把业务结果转换为 HTTP response，不直接复用业务 dataclass 作为接口契约
- 调整：`ocr_processor/README.md` 目录结构和安装说明
- 调整：`ocr_processor` 内部对 `docling_blocks` / `markdown_export` 的引用切到 `impl/`
- 调整：`ocr_processor/README.md` 新增业务层 pipeline、PDF pipeline、DOCX pipeline、HTTP API pipeline 的调用链说明
- 调整：`agent/README.md`、`agent/CONTEXT.md` 补充“业务接口和 API 接口并行存在”的边界说明
- 调整：`tests/test_api.py` 适配新导入路径

## 6) 当前工作区状态（需要注意）

仓库根目录当前有未提交内容：

- 修改：`agent/CONTEXT.md`
- 修改：`agent/README.md`
- 修改：`agent/pyproject.toml`
- 新增：`agent/routes/__init__.py`
- 新增：`agent/routes/ocr_processor.py`
- 新增：`agent/ocr_processor/pyproject.toml`
- 新增：`agent/ocr_processor/impl/docling_blocks.py`
- 修改：`agent/ocr_processor/impl/pdf/docling_adapter.py`
- 新增：`agent/ocr_processor/impl/doc/docling_adapter.py`
- 新增：`agent/ocr_processor/impl/markdown_export.py`
- 修改：`agent/ocr_processor/impl/pdf/processor.py`
- 修改：`agent/ocr_processor/impl/doc/processor.py`
- 修改：`agent/ocr_processor/__init__.py`
- 修改：`agent/ocr_processor/schemas.py`
- 修改：`agent/ocr_processor/README.md`
- 修改：`agent/tests/ocr_processor/test_processor.py`
- 修改：`agent/tests/ocr_processor/test_markdown_export.py`
- 新增：`agent/tests/ocr_processor/test_pdf_docling_adapter.py`
- 修改：`agent/tests/ocr_processor/test_docling_blocks.py`
- 修改：`agent/tests/test_api.py`
- 新增：`agent/tests/ocr_processor/test_sample_documents.py`
- 未跟踪：`agent/output/`（真实样本验证输出）
- 未跟踪：`backend/`、`frontend/`

本轮针对 P1/P3 的附加验证：

- 命令：`python -c "import main; print('main import ok without docling')"`
- 结果：通过，证明在无 `docling` 环境下服务入口仍可导入
- 命令：`pytest tests/test_api.py -q`
- 结果：`4 passed`
- 命令：`pytest tests/ocr_processor/test_uploadfile_compat.py -q`
- 结果：`2 passed`

本轮针对 PDF Docling 回归的附加验证：

- 命令：`conda run -n agent-gate pytest tests/ocr_processor/test_pdf_docling_adapter.py -q`
- 结果：`7 passed`
- 命令：`conda run -n agent-gate pytest tests/test_api.py -q`
- 结果：`4 passed`

本轮针对 `agent-service` 打包完整性的附加验证：

- 命令：`python -m pip install ./agent --no-deps --no-build-isolation -t /tmp/agent_service_pkg_test`
- 结果：通过，可构建并安装 `agent-service` wheel
- 命令：`PYTHONPATH=/tmp/agent_service_pkg_test python -c "import main; import routes.ocr_processor; import ocr_processor; print('installed package import ok')"`
- 结果：通过，说明 `main/routes/ocr_processor/ocr_processor` 已随 `agent-service` 一起打包

进行下一次提交时，建议只按目标文件精确 `git add`，避免误带无关改动。

## 7) 下一个建议动作（按优先级）

1. **细化 block 语义**：把 `heading / paragraph / list_item / table` 判别做稳，提升 Markdown 质量。
2. **继续收命名**：若还觉得 `ocr_processor/` 顶层语义不清，下一步优先考虑把 `types.py` 重命名成更具体的名字，例如 `file_types.py`。
3. **规划前端消费契约**：优先按 `md_list` 展示和高亮，`blocks` 作为抽取和辅助定位输入。
4. **规划 legacy `.doc` 策略**：若要支持，优先选非平台专属的转换方案。

## 8) 快速上手命令

```bash
# 进入 agent
cd ./agent

# 运行 OCR 相关测试
conda run -n agent-gate pytest tests/ocr_processor/test_processor.py -q

# 查看当前改动
cd .
git status --short
```

## 9) 关键文件索引

- `ocr_processor/processor.py`：外部统一入口
- `ocr_processor/impl/dispatcher.py`：类型分发
- `ocr_processor/impl/pdf/processor.py`：PDF 处理 + fallback
- `ocr_processor/impl/doc/processor.py`：DOC/DOCX 处理
- `ocr_processor/impl/pdf/docling_adapter.py`：PDF Docling 适配 + artifacts 路径
- `ocr_processor/impl/doc/docling_adapter.py`：DOCX Docling 适配
- `ocr_processor/README.md`：模块说明
- `tests/ocr_processor/test_processor.py`：核心测试
