last updated: 2026-04-28 12:51:12

## 2026-04-28 12:51:12

### 已完成工作

- 新增 `agent/docs/API.md`，记录 agent service 的健康检查、文档标准化、字段抽取和 route policy 三类 HTTP API。
- 文档中补齐三段式全流程 pipeline：`document_processor -> file_extraction_agent -> route_policy_agent`。
- 记录 backend 在两段接口之间需要完成的组装职责：为 blocks 补齐 `document_id/block_id`，并从抽取 trace 组装 `refs_with_text`。
- 实现并挂载 `route_policy_agent` HTTP 出口 `POST /v1/route-policy-agent/evaluate`，与 `agent/docs/DESIGN.md` 中的三阶段链路保持一致。
- 使用真实 PDF `18【本科生】2025-2026学年第一学期 文明模范寝室.pdf` 走 HTTP 全流程并验证三段接口均返回 200。

### 当前进展

- agent service 当前具备三段 HTTP 出口：文档标准化、字段抽取、route policy 判断。
- 真实 HTTP 全流程结果可用：模范寝室为 `106、218、413、521、603`，文明寝室为 `212、214、302、324、401、518、519、523、614、618、620、621`，楼宇平均分为 `85.1`。
- route policy 对本次样例的 4 个字段均返回 `accept`。

### 遇到的问题

- RapidOCR 日志提示 `ppocr_keys_v1.txt` 不存在，但本次 OCR 和接口返回未受阻断。
- 模型结构化输出阶段出现 Pydantic serializer warning，但 HTTP 链路和业务结果正常返回。

### 下一步

- 后续可把 route policy 的真实 HTTP 样例沉淀为集成测试或脚本，避免只依赖手工 curl 验证。

## 2026-04-28 10:56:45

### 已完成工作

- 新增 `route_policy_agent` 的设计文档，明确它作为 agent service 下第三个独立阶段，负责小 LLM + rules 的字段级 route 判断。
- 同步更新 `agent/docs/DESIGN.md`，把 agent service 从两个阶段扩展为 `document_processor`、`file_extraction_agent`、`route_policy_agent` 三个阶段。
- 明确 `file_extraction_agent` 只产出 `ExtractionResult(result + trace)`，不内置 `accept / review / reject` 判断。

### 当前进展

- agent service 的职责边界调整为：文档标准化、字段抽取与 trace、route policy 三阶段分离。
- backend 不做 LLM route 判断，只调用 agent 的 route policy 能力并保存输出。

### 下一步

- 后续实现 `route_policy_agent` 时，按 TDD 补 schemas、rules、policy client、processor 和 HTTP route。
- 为新增测试文件同步维护 `tests/docs/` 下的一一对应说明文档。

## 2026-04-27 14:46:39

### 已完成工作

- 清理 `agent/tests/` 下的本机绝对路径：PDF 处理器测试改为从被测模块路径推导 `impl/pdf/models/`，测试说明文档的运行命令不再写开发者个人主目录。
- 在 `agent/pyproject.toml` 的 pytest 配置中加入 `--import-mode=importlib`，避免不同测试子目录里的同名测试文件在默认 collection 阶段发生模块名冲突。
- 同步更新 `tests/document_processor/docs/test_pdf_processor.md` 等测试说明文档，保持测试代码和测试文档一致。

### 当前进展

- 默认命令 `pytest -q` 已可直接运行完整 `agent` 测试集。
- 已确认测试树和 pytest 配置不再命中开发者个人主目录一类本机路径。
- 在 `agent-gate` Conda 环境中验证：`94 passed, 2 warnings`。

### 遇到的问题

- 原默认 pytest 配置会把不同目录下同名测试文件当成同一顶层模块导入，导致 `test_processor.py`、`test_schemas.py` collection 冲突。
- 测试说明文档里曾保留本机绝对路径，迁移到其他机器或 CI 时不够干净。

### 下一步

- 继续处理 `file_extraction_agent.impl` 未被打包、`/v1/ocr/capabilities` 依赖不存在模块、设计文档与当前模型配置实现不一致等剩余问题。

## 2026-04-25 17:24:12

### 已完成工作

- 新增 `file_extraction_agent` 的 HTTP 出口 `POST /v1/file-extraction-agent/extract`，由 route 层解析 JSON 后调用 `file_extraction_agent.processor.extract(...)`。
- 为 `document_processor` 增加规范路径 `POST /v1/document-processor/process`，并兼容保留旧路径 `POST /v1/ocr/process`。
- 修复 `UploadFileProxy` 缺少 `read()` / `seek()` / `tell()` 的问题，确保上传文件传入业务入口后仍是可读 file-like 对象。
- 新增路由层测试和对应 `tests/routes/docs/` 测试说明，验证 HTTP 出口只做协议适配并调用业务入口。
- 使用真实文明寝室 PDF 走完整 API 集成测试，确认文档标准化与字段抽取结果正确。
- 同步更新 `agent/docs/DESIGN.md`，记录当前 HTTP 出口和暂不迁移 `src/` / `app/` 目录的理由。

### 当前进展

- `agent` 根层已经形成两个可调用 API 出口：文档标准化和字段抽取。
- 真实 API 链路已验证通过：文档处理产出 7 个 blocks，字段抽取返回 `18栋`、12 个文明寝室房间号和数量 `12`。
- 当前继续沿用 `main.py + routes/ + 业务包` 的结构，避免为目录迁移扩大改动面。

### 遇到的问题

- 首次真实 API 集成测试发现 `UploadFileProxy` 不能被业务入口识别为 file-like 对象，已通过最小委托方法修复。
- 普通沙箱下模型服务请求会出现 `APIConnectionError`；放开网络后同一份 `.env` 可正常完成模型调用。

### 下一步

- 后续如果服务入口、配置加载或部署结构继续变复杂，再评估是否整体迁移到 `src/` 或 `app/` 目录。

## 2026-04-25 16:02:27

### 已完成工作

- 完善 `file_extraction_agent/README.md`，补齐包职责、主处理链路、快速使用、输入输出契约、模型配置、运行选项、输出结构和测试入口。
- 同步更新 `file_extraction_agent/docs/DESIGN.md`，明确当前没有独立 `impl/validation.py`；`validation_rules` 作为字段定案后的通用后处理，收在 `impl/resolution.py::_apply_validation_rules(...)`。
- 同步修正本层 `docs/DESIGN.md` 中对校验逻辑入口的引用，避免继续指向不存在的 `file_extraction_agent/impl/validation.py`。

### 当前进展

- `file_extraction_agent` 文档入口和设计文档已与当前代码结构对齐。
- validation 相关文档口径统一为：模型先完成字段定案，系统再在 `resolution.py` 内执行规则后处理并记录 `validation_rule` trace action。

### 遇到的问题

- 旧文档里保留了 `impl/validation.py` 的引用，但当前实现已经把规则校验、规则覆盖和跨字段一致性收口放在 `resolution.py` 中。

### 下一步

- 后续如果 `validation_rules` 类型明显增多，或需要被 resolution 以外的节点复用，再评估是否拆出独立 validation 模块。

## 2026-04-19 23:44:10

### 已完成工作

完成document_processor模块的实现，进行过端到端测试，验证了基本功能的正确性和稳定性。

### 当前进展

更新了DESIGN.md在file_extraction_agent目录下，明确了模块职责边界和设计方案。

### 遇到的问题

暂无

### 下一步

继续完善file_extraction_agent模块的设计文档，准备后续的实现工作。
