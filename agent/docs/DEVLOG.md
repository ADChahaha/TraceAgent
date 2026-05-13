last updated: 2026-05-13 19:46:45

## 2026-05-13 19:46:45

### 已完成工作

- 将 `file_extraction_agent` 改为 stream-first 只读虚拟文件树抽取器，输入从单个聚合 `html` 改为 `documents(filename + html) + task_spec`。
- 新 HTTP 入口为 `POST /v1/file-extraction-agent/extract/stream`，返回 `application/x-ndjson`；工具事件在每次工具调用后立即流出。
- 虚拟树把文档目录、section 目录、paragraph `.md`、list `.list` 和 table `.table` 统一到路径空间；paragraph 文件名使用编号加前 N 个可见字符预览。
- 工具集收口为 `tree/read/anchors/query_table/write_field/submit_result`，移除 soft plan、旧 block 读取和旧字段定案工具语义。
- 证据 selector 统一为 paragraph `sentences`、list `items`、table `rows`；`write_field` 覆盖写入字段，`submit_result` 内部做 schema/type/evidence 校验。
- 同步更新 agent 顶层 README/API/DESIGN、`file_extraction_agent` README/DESIGN，以及对应测试说明文档。

### 验证

- `conda run -n agent-gate python -m pytest tests/file_extraction_agent tests/routes/test_file_extraction_agent_route.py -q`，结果 `36 passed`。

## 2026-05-10 04:11:05

### 已完成工作

- `file_extraction_agent` 的 `query_table` 返回结构收口为 `rows`、轻量 `table_audit` 和顶层 `summary`，不再返回详细 `query_audit`。
- `table_audit.blank_cells.by_column` 按列给出空 cell 数和前 10 个空值行 id，不再额外返回截断标记。
- `rows[].values` 直接保留 SQL 选中列里的空字符串，`summary` 只描述本次查询返回行数和输出列空值数量。
- 同步更新 `file_extraction_agent` README、设计文档、prompt 测试和对应测试说明文档。

### 验证

- `PYTHONPATH=. pytest tests/file_extraction_agent -q`，结果 `87 passed`。

## 2026-05-10 01:45:57

### 已完成工作

- `file_extraction_agent` 新增 `preview_inline_evidence` 工具，用于把本轮已读取的文本块细化为 inline 证据 id。
- `set_field(status="resolved")` 增加证据粒度硬校验：文本必须使用 inline id，表格必须包含 `tr` 行 id，列表必须包含 `li` item id。
- 更新 resolution prompt，让模型在写文本证据前先调用 `preview_inline_evidence`，并明确 table/list 证据分别走 row/item 粒度。
- 同步更新 `file_extraction_agent` README、设计文档、工具测试和对应测试说明文档。

### 验证

- `PYTHONPATH=. pytest tests/file_extraction_agent -q`，结果 `85 passed`。

## 2026-05-05 03:13:09

### 已完成工作

- 移除字段定义里的宽泛 `type=list`，列表字段必须显式声明为 `list[string]` 或 `list[number]`。
- `file_extraction_agent` 的 `set_field` 在写入 `resolved` 字段前立即校验值类型；类型不匹配时返回 `ok=false` 的工具结果，并且不写入 `field_states`。
- 同步 route policy 和 backend 测试 fixture 的列表字段类型，避免下游继续依赖裸 `list`。

### 验证

- `python -m pytest tests/file_extraction_agent/test_schemas.py tests/file_extraction_agent/test_html_tools_new.py tests/route_policy_agent -q`，结果 `62 passed`。
- `python -m pytest`，在 `agent/` 下结果 `120 passed`。
- `python -m pytest backend/tests`，结果 `16 passed`。

## 2026-05-04 02:20:00

### 已完成工作

- 将 `file_extraction_agent` 收口到 HTML 文档工作流：broad 只看完整 HTML 并产出 plan，resolution 通过工具读取 section/element/table/paragraph 并逐步 `set_field`。
- 新增/扩展 HTML index：基于 document_processor 已补好的 DOM id 建立元素索引、表格索引、标题树和表格行证据 id，不再在抽取包内重新生成 element id。
- resolution 工具返回 HTML 片段而不是自定义 JSON 文本，`read_section(depth=1)` 默认只读当前层，可由模型显式调大 depth；表格查询错误会作为工具错误返回给模型自行修正，不直接终止 agent。
- 增加 `update_plan`/tool action trace，要求模型每一步写 reason，便于前端复现“人类查找文档”的过程。
- 模型配置继续走 `agent/.env`，支持 broad/resolution 分别配置模型名、temperature、top_k 等参数。
- 更新 file_extraction_agent 设计文档和测试，覆盖 broad plan、HTML index、table row evidence、工具错误恢复和 resolution tool loop。

### 当前进展

- 用立命馆真实 PDF 走 backend 全链路时，document_processor 和 file_extraction_agent 均完成；route_policy 因 API key 配置不匹配失败，但抽取结果和完整 actions trace 已保存，可被前端 replay。
- 当前抽取 trace 已能驱动前端显示：outline 定位、文档滚动、高亮、表格行 evidence、字段写入和 plan 进度。

### 验证

- `PYTHONPATH=agent python -m pytest agent/tests/file_extraction_agent/test_broad_new.py agent/tests/file_extraction_agent/test_html_index_new.py agent/tests/file_extraction_agent/test_html_tools_new.py agent/tests/file_extraction_agent/test_resolution_new.py -q`
- 真实任务 `task_fc1c4d34a48742c9b7785f13f497ced8` 产生 `52` 个 replay actions、完整 `display_html` 和 11 个字段结果。

### 遇到的问题

- 当前 broad plan 仍有轻微“过度计划/幻觉式描述”，但本次先只记录状态并提交，不调整 prompt。
- 大 PDF 中模型可能重复读取相邻 section；已通过 `read_section(depth)` 降低一次读取过多内容的风险，但后续 prompt 仍需要继续收敛行为。

### 下一步

- 后续单独调 prompt：让 plan 更克制，只描述查找策略；resolution 看到字段证据足够后立即 `set_field`，避免把所有字段拖到最后统一写入。

## 2026-04-30 20:42:20

### 已完成工作

- 将 agent 抽取链路收口到统一 `search_grep`：一次工具调用同时检索正文 paragraph 和表格 row，查询词固定使用 `term1 OR term2 OR term3`。
- 为 broad / resolution prompt 注入明确 `tool_contract`，让模型按工具描述理解 `search_grep`、候选写入、候选复制、候选计数和最终定案语义。
- route policy 输入扩展为 `field_outputs + refs_with_text + field_processes`，并让派生字段通过 `related_field_processes` 看到来源字段前序 agent 查过什么、写入过多少候选和如何定案。
- 将字段抽取和 route policy 的结构化输出策略都收口为 `tool_call`，不再保留 `json_schema/auto`。
- 候选写入工具收到未知 ref 时不再直接终止整单，runner 记录 `tool_error` 并把错误作为下一轮工具结果返回给模型修正。

### 验证

- `conda run -n agent-gate python -m pytest tests/file_extraction_agent tests/route_policy_agent tests/routes/test_route_policy_agent_route.py -q`，结果 `90 passed`。
- `conda run -n agent-gate python -m pytest backend/tests/test_task_flow.py -q`，结果 `10 passed`。
- `pnpm test -- task-detail.test.tsx --runInBand`，结果 `7 passed`。
- 真实前端全流程任务 `task_ff50dfeab89a4923bdc4cbbd257c0a25` 完成 `completed / done / accept`，抽取 `academic_paper_count=9` 和 9 个 `academic_paper_names`。

### 遇到的问题

- route policy 之前只看当前字段过程，导致 `academic_paper_count` 这类派生字段看不到 `academic_paper_names` broad 阶段实际查询词。
- 真实 E2E 中模型曾把不存在的表格行 ref 传给候选写入工具，旧逻辑会把整个 extraction 标记为 failed。

### 下一步

- 后续可继续优化 Paddle 表格行切分和 query 召回口径，减少模型从大表格中选择错误 ref 的概率。

## 2026-04-30 02:11:37

### 已完成工作

- 更新 `agent/docs/DESIGN.md`，记录 `file_extraction_agent` 下一版受约束 agentic workflow 设计：`Broad Agent Loop` 通过 `search_text`、`search_table_rows`、`add_candidate`、`finish_broad` 做候选证据召回。
- 明确 `resolution agent` 可以读取 broad 候选，并在候选不足时继续用文本/表格检索工具补查，最终定案必须引用候选或 block/row id。
- 明确表格检索是通用结构化检索能力，不硬编码具体业务词；当前内容类型先收敛为 heading/text/table，不处理 image。
- 明确 OCR/表格质量提示只用于 backend review handoff 的人工审核辅助，不影响 broad、resolution 或 route policy 自动判断。

### 验证

- 本次只更新设计文档，不涉及运行时代码或测试文件。

## 2026-04-29 20:32:22

### 已完成工作

- 同步 `agent/README.md` 和 `agent/docs/DESIGN.md`，把 agent service 明确为 `document_processor -> file_extraction_agent -> route_policy_agent` 三阶段服务。
- 修正 agent 与 backend 的交互描述：当前由 backend 通过 HTTP 传入文件 bytes、聚合 blocks、调用字段抽取和 route policy，agent 不直接拉取 backend 文件或访问 SQLite。
- 明确 `route_policy_agent` 已实现 `accept / review / reject` 字段级判断，不再描述为后续规划。

### 验证

- 本次只更新文档，不涉及运行时代码或测试文件。

## 2026-04-28 14:19:45

### 已完成工作

- 按 review 修正 `file_extraction_agent` 抽取端结构化输出策略：`auto` 只在 `json_schema` 明确不支持时切到 `tool_call`，已经进入 invoke 阶段的超时、鉴权、服务端错误或输出校验失败不再换协议重试。
- 收紧 resolution 证据绑定：模型返回 `status=resolved` 时必须声明非空 `used_block_ids`，避免最终 trace 沿用未被模型声明使用的 broad evidence。
- 清理 document processor route 边界：HTTP 层改为从公开 `service.document_processor.processor` 导入 `InvalidFileObjectError`，不再依赖 `impl.base`。
- 按你的决策保留 route policy 的 `json_schema -> tool_call` 结构化重试语义，但仍不解析裸 `model.invoke(...)` 响应。
- 同步更新相关设计/API 和测试说明文档。

### 当前进展

- review 中除 route policy 保留结构化 tool call 重试外，其余仍成立的设计偏差已修正。
- 在 `agent-gate` 环境中验证完整测试：`126 passed, 2 warnings`。

### 遇到的问题

- 抽取端之前把结构化 runnable 构造失败和 invoke 失败放在同一个 broad except 中，会把业务调用失败误判成协议不支持并重复请求模型。
- resolution 之前允许 resolved 字段缺少 `used_block_ids`，会削弱后续 route policy 基于 refs 做放行判断的审计语义。

### 下一步

- 后续如果继续调整结构化输出兼容策略，需要分别说明“协议选择失败”和“模型调用失败”的处理语义。

## 2026-04-28 13:32:31

### 已完成工作

- 修复 `/v1/ocr/capabilities` 依赖不存在 `docling_adapter` 的问题，改为从现有 PDF processor 读取 docling 模型目录。
- 将 `file_extraction_agent` 的 `RunOptions` 收敛为 `schemas.py` 中的公开全局契约，供 HTTP 入口、Python 入口和内部 graph 共用。
- 移除 `file_extraction_agent` 和 `route_policy_agent` 模型客户端中的裸 `model.invoke(...)` JSON / tool call 回退，只保留设计中的结构化输出策略回退。
- 同步更新相关设计/API/README 和测试说明文档，补齐 capabilities、run options 边界和结构化调用失败语义。

### 当前进展

- agent service 的 HTTP 能力查询、字段抽取公开参数边界和模型结构化调用行为已与当前设计一致。
- 使用真实文明寝室 PDF 完成三段业务端到端验证：`document_processor -> file_extraction_agent -> route_policy_agent`，结果为 `18栋`、12 个文明寝室房间号、数量 `12`，route policy 三个字段均 `accept`。
- 在 `agent-gate` 环境中验证完整测试：`122 passed, 2 warnings`。

### 遇到的问题

- review 发现 capabilities 路由、HTTP `run_options` 暴露内部对象、模型客户端裸 JSON 回退三处与设计或文档不一致。
- 当前 shell 未提供 `BASE_URL` / `OPENAI_API_KEY`，端到端验证使用确定性结构化 fake client 替代外部 LLM，但真实 PDF 解析、字段 graph、validation_rules 和 route policy 输入校验均走当前代码。
- 完整测试仍有 docling / RapidOCR 依赖自身的 deprecation warning，本次未改动第三方依赖行为。

### 下一步

- 后续如果继续调整运行参数，优先扩展公开 `RunOptions`，避免外部和内部维护两份同构配置。

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
