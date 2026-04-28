last updated: 2026-04-28 15:07:09 CST

## 2026-04-28 15:07:09

### 已完成工作

- 收紧 `broad_extraction.py` 的 evidence ref 校验：`evidence_refs[]` 必须携带来自输入 `blocks` 的 `block_id`，缺失或未知时在进入 resolution 前报错。
- 修复已跟踪文明寝室 E2E 脚本的旧导入路径，统一改为 `service.document_processor` 和 `service.file_extraction_agent`。
- 更新 broad extraction 和 packaging 回归测试，并同步对应 `tests/docs/` 测试说明文档。

### 当前进展

- broad 输出校验和包级 `service.*` 导入边界已与设计文档对齐。
- 完整 agent 测试已通过：`128 passed, 2 warnings`。

### 遇到的问题

- 旧 broad 校验会跳过没有 `block_id` 的 `evidence_refs`，可能让 trace 中出现无法稳定回查到输入 block 的证据位置。
- 已跟踪集成脚本仍使用旧顶层包导入路径，在干净安装环境下不符合当前打包和模块边界。

### 下一步

- 后续如果继续保留 `agent/output/` 下的可执行集成脚本，建议把它们纳入统一脚本目录或 CI smoke test，避免旧入口再次漂移。

## 2026-04-28 14:19:45

### 已完成工作

- 收紧 `extractor_client.py` 的 `auto` 结构化输出策略：只有 `json_schema` 明确不支持时才切到 `tool_call`。
- 调整结构化 runnable 调用失败语义：进入 `invoke(...)` 后的超时、鉴权、服务端错误或输出校验失败直接抛 `ExtractorClientInvocationError`，不再换协议重试。
- 收紧 `resolution.py` 的证据绑定：`status=resolved` 的模型定案必须声明非空 `used_block_ids`，系统再据此回查 `NormalizedBlock` 生成最终 evidence。
- 清理 `docs/DESIGN.md` 中 `RunOptions` 归属残留，统一说明它是公开契约，内部 graph 复用同一对象。
- 更新 extractor client、resolution 的回归测试和对应测试说明文档。

### 当前进展

- 抽取端结构化输出失败语义、resolved 字段证据绑定语义和设计文档已对齐。
- 相关测试已通过，完整 agent 测试结果为：`126 passed, 2 warnings`。

### 遇到的问题

- 旧实现会在 `json_schema` invoke 阶段失败后继续尝试 `tool_call`，可能导致同一次抽取字段模型调用被重复执行。
- 旧实现允许 resolved 字段不声明 `used_block_ids`，最终 trace 可能引用 broad evidence，而不是模型最终声明使用的证据。

### 下一步

- 后续如果要支持更复杂的结构化输出 provider 兼容逻辑，先补清楚“协议不支持”的错误识别测试，再扩展 fallback 条件。

## 2026-04-28 13:32:31

### 已完成工作

- 将 `RunOptions` 提升到 `schemas.py`，作为 HTTP 入口、Python 入口和内部 graph 共用的公开运行契约。
- 删除 `impl/schemas.py` 中重复的 `RunOptions` 定义，避免外部和内部维护两份同构配置。
- 移除 `extractor_client.py` 中结构化调用失败后的裸 `model.invoke(...)` JSON / tool call 回退，严格遵循 `json_schema -> tool_call` 的结构化输出策略。
- 同步更新 README、API、设计文档和测试说明文档，明确 `RunOptions` 是全局契约。

### 当前进展

- `file_extraction_agent` 的运行选项边界已与设计一致，不再从 route 层暴露 `impl` 对象。
- 真实文明寝室 PDF 三段端到端验证中，抽取结果为 `building_name=18栋`、12 个文明寝室房间号和 `civilized_dormitory_count=12`。
- `tests/file_extraction_agent` 与 file extraction route 相关测试已通过：`70 passed`。

### 遇到的问题

- review 发现之前的 HTTP `run_options` 直接引用 `impl.schemas.RunOptions`，边界不符合“schemas.py 承载稳定外部契约”的设计。
- 模型客户端曾在结构化 runnable 失败后解析裸模型响应，绕过了设计中的结构化输出协议边界。

### 下一步

- 后续新增运行参数时，直接扩展公开 `RunOptions`，并让内部 graph 复用同一对象。

## 2026-04-27 18:59:19

### 已完成工作

- 新增 `file_extraction_agent/docs/API.md`，补齐 Python `extract(...)`、HTTP `/v1/file-extraction-agent/extract`、`blocks`、显式 `task_spec`、`run_options`、`validation_rules`、返回结构和失败语义说明。
- 在 API 文档中明确 trace 对外稳定字段：`trace.fields[].evidence`、`related_fields`、`actions`、`reason/failure_reason`、`warnings` 和 `metadata`。
- 在 API 文档中明确当前 trace 边界：保留证据、工具动作、规则动作和失败原因，不对外保留 raw prompt、raw model response 或完整内部 broad 原始对象。
- 更新 `README.md`、`docs/DESIGN.md`、`agent/README.md` 和 `agent/docs/DESIGN.md` 的调用方 API 文档入口。

### 当前进展

- `file_extraction_agent` 的调用方文档已覆盖显式 `task_spec`、外部必传稳定唯一 `block_id`、HTTP `run_options` 和不支持 `task_spec_name` 的新契约。

### 下一步

- 后续如果 `keep_detailed_trace` 从预留开关变成真实返回扩展，需要同步更新 API 文档中的 trace 边界说明。

## 2026-04-27 18:41:14

### 已完成工作

- 移除 `file_extraction_agent` 的本地 `task_specs/` / `task_spec_name` 加载入口，改为调用方必须显式传入 `task_spec`。
- 修复 `agent-service` wheel 漏打 `file_extraction_agent.impl` 的问题，并新增 packaging 回归测试。
- 将 `block_id` 契约收紧为 backend / session 聚合层必传：agent 只校验 `block.block_id` 存在且本次输入内唯一，缺失或重复时直接抛 `ValueError`。
- 删除 agent 内 block id 兜底生成逻辑，不再从 `meta_info.block_id` 兜底读取，也不再基于文本或 Python `hash(...)` 生成 fallback id。
- 为 resolution 增加字段约束后处理：`required`、`enum_values`、`money/date/boolean` 基础形状不满足时降级为 failed，并记录 `field_constraint` action。
- 为 broad / resolution prompt 增加 `RunOptions` prompt budget，限制 blocks / evidence 数量和文本长度。
- 修复 `validation_rules.table_rows` 的空目标列覆盖问题：命中行的 `target_column` 全为空时保留模型原始定案，不再覆盖成空字符串 resolved。
- 修复 validation 覆盖证据后的 lookup trace 语义：按最终 `FieldDecision.evidence` 重新计算 `LookupRecord.used_in_final_decision`。
- 为 HTTP `/v1/file-extraction-agent/extract` 暴露 `run_options`，让 prompt budget 和 lookup 开关能从 API 路径配置。
- 同步更新 `agent/docs/DESIGN.md`、`file_extraction_agent/docs/DESIGN.md`、README 和测试说明文档。

### 当前进展

- `tests/file_extraction_agent` 与 `tests/routes/test_file_extraction_agent_route.py` 已通过：`70 passed`。
- 本地 wheel 内容已确认包含 `file_extraction_agent/impl/block_ids.py`、`impl/validation.py`、`routes/file_extraction_agent.py`。

### 下一步

- 如后续接真实大文档，需要根据业务规模调整 prompt budget，或在外层增加检索 / 分页策略。

## 2026-04-27 02:18:08

### 已完成工作

- 修复 `resolution.py` 中 lookup trace 的使用标记：当模型在 `final_decision.used_block_ids` 中引用了 `lookup_blocks_for_field(...)` 返回的 block，系统会把对应 `LookupRecord.used_in_final_decision` 标记为 `True`。
- 更新 `tests/file_extraction_agent/test_resolution.py`，固定“lookup 返回证据被最终字段定案使用时 trace action 必须标记 used”的行为。

### 当前进展

- `global_lookup` trace 现在可以区分“补查证据返回给模型但未参与最终定案”和“补查证据确实支撑最终字段值”。
- `tests/file_extraction_agent` 当前全量通过：`56 passed`。

### 遇到的问题

- 原实现只记录 lookup 是否 `returned_to_model`，没有根据最终字段证据回填 `used_in_final_decision`，会削弱字段级 trace 的审计语义。

### 下一步

- 继续处理 review 中剩余问题：`table_rows` 空值覆盖、fallback block id 稳定性，以及 HTTP route 暴露 `run_options`。

## 2026-04-25 16:02:27

### 已完成工作

- 完善 `README.md`，补齐 `file_extraction_agent` 的职责边界、主处理链路、快速使用、输入输出契约、模型配置、运行选项、目录结构和测试入口。
- 更新 `docs/DESIGN.md`，把 `validation rule executor` 明确收敛为 `resolution.py::_apply_validation_rules(...)` 的字段级后处理。
- 明确当前不设置独立 `impl/validation.py`；规则校验、规则覆盖和跨字段一致性收口都放在 `resolution.py` 中。

### 当前进展

- 包级 README 已可作为调用方和维护者的第一入口。
- validation 文档口径已与源码一致：模型先完成字段定案，系统再在 resolution 内执行 `validation_rules` 后处理并记录 `validation_rule` action。

### 遇到的问题

- 原来的文档表达容易让人误以为 validation 是独立模块；实际代码中已经没有 `impl/validation.py`，只有 `resolution.py` 内部的规则后处理函数。

### 下一步

- 后续如果 `validation_rules` 类型明显增多、需要被多个节点复用，或 `resolution.py` 因规则实现变得难维护，再评估是否拆独立 validation 模块。

## 2026-04-25 07:54:02

### 已完成工作

- 为 `impl/graph.py` 增加统一失败收口：broad / resolution 中途出现模型调用、结构化输出或节点校验异常时，不再向外抛裸异常，而是返回 `ExtractionResult(status="failed")`。
- 在失败返回中保留失败前已有的 `field_decisions`、`evidence_collection` 和 `warnings`；未完成字段补 `status="failed"`，并写入 `model_call_error` trace action。
- 扩展对外 `ExtractionResult`，新增顶层 `status` 和 `failure_reason`，用于表达 agent 包级执行是否完整完成。
- 修复 `FieldResolutionAction` strict response schema：将 `FieldResolutionDecision.value` 从 `Any | None` 收紧为 `str | int | float | bool | list[str] | None`，避免生成 `anyOf: [{}]` 这类 provider 会拒绝的 schema。
- 同步更新 `docs/DESIGN.md`、`test_graph.py`、`test_schemas.py` 和对应 `tests/file_extraction_agent/docs/` 测试说明文档。

### 当前进展

- `tests/file_extraction_agent` 当前全量通过：`56 passed`。
- 直接使用 `output/integration_civilized_dormitory/` 中已有 md、normalized blocks 和 task spec 跑真实模型集成通过：4 次调用，输出 `building_name=18栋`、12 个文明寝室房间号和 `civilized_dormitory_count=12`。
- 专门验证 `FieldResolutionAction` 的 strict `json_schema` provider 调用已经可以正常返回，不再出现 `schema must have a type key` 的 400。

### 遇到的问题

- 原来的 `value: Any | None` 在 Pydantic JSON Schema 中会生成 `{}` 分支，strict response format 下 provider 会在请求进入模型推理前直接拒绝。
- 之前 broad / resolution 失败会直接中断调用方，不利于后续 backend route 和人工复核统一处理失败结果。

### 下一步

- 后续可继续处理 LangChain / Pydantic 的 serializer warning；当前 warning 不影响 provider schema 校验和最终抽取结果。
- backend 接入时可以直接根据顶层 `ExtractionResult.status` 判断是否进入正常 route，或转入人工兜底流程。

## 2026-04-25 07:06:20

### 已完成工作

- 先扩展 `docs/DESIGN.md` 为更具体的 agent 施工图，按处理单元写清 `input_adapter -> broad model -> resolution model -> tools -> validation rule -> graph mapper` 的输入、输出、失败条件和 trace 语义。
- 为 broad 阶段增加输出校验：必须覆盖 `TaskSpec.fields`，不能返回重复字段、schema 外字段，也不能引用不存在的 `block_id`。
- 将 resolution 模型输出收窄为轻量 `FieldResolutionDecision`：模型只负责 `status/value/used_block_ids/related_fields/reason` 等语义判断，系统再按 `used_block_ids` 回查 `NormalizedBlock` 绑定 evidence 与 refs。
- 拆分 lookup 配置为 `max_lookup_calls_per_field` 和 `lookup_top_k`，避免把“调用次数”和“每次返回条数”混在一个字段里。
- 增加 `field_reference / global_lookup / validation_rule` 三类 trace action，并区分 `returned_to_model` 与 `used_in_final_decision`。
- 同步更新 `test_broad_extraction.py`、`test_resolution.py`、`test_schemas.py` 及对应 `tests/docs/` 说明文档。
- 复用 `output/integration_civilized_dormitory/` 中已有 md、normalized blocks 和 task spec 跑真实 agent 集成，并生成 `direct_md_integration_call_trace.json` 记录模型调用过程。

### 当前进展

- `tests/file_extraction_agent` 当前全量通过：`52 passed`。
- 直接基于 md/blocks 的真实集成通过，输出 `building_name=18栋`、12 个文明寝室房间号和 `civilized_dormitory_count=12`。
- 新的调用记录显示最小调用链为 4 次：1 次 broad，全字段预选；3 次逐字段 resolution。

### 遇到的问题

- 原来的 resolution 模型需要直接生成内部 `FieldDecision.evidence`，schema 太重，真实调用中容易出现漏填嵌套字段的问题。
- 直接让模型填系统内部 trace 对象会模糊职责边界；更合理的是模型只声明语义判断和 `used_block_ids`，由系统绑定可追踪证据。

### 下一步

- 后续可把 `keep_detailed_trace=True` 正式接入运行选项，让模型调用记录进入稳定 trace，而不是只依赖集成脚本产物。
- 可以继续收口 structured output 的 warning，评估默认使用 `function_calling` 或更简单的 schema 生成策略。

## 2026-04-25 05:59:48

### 已完成工作

- 收紧 resolution prompt 的输入边界：字段定案阶段不再直接携带原始 `blocks`，只接收目标字段 evidence、全字段 evidence 摘要、`tool_evidence` 和 `tool_records`。
- 保留 `lookup_blocks_for_field(...)` 作为唯一能按需访问全量 `blocks` 的补查入口，避免模型绕过 lookup trace 直接回查全文。
- 更新 `test_prompts.py` 和对应测试说明文档，固定 resolution payload 不包含原始 `blocks` 的行为。
- 同步更新 `file_extraction_agent/docs/DESIGN.md`，明确 resolution 默认只能看 broad 压缩证据和工具返回证据。

### 当前进展

- `tests/file_extraction_agent` 当前全量通过。
- broad 阶段仍负责从全量 `blocks` 预选字段级 evidence，resolution 阶段只在模型显式请求 lookup 时获得补充证据。

### 遇到的问题

- 之前 resolution prompt 同时带入了全字段 evidence 和原始 `blocks`，会削弱 lookup trace 的治理意义。

### 下一步

- 后续可继续补强 lookup 次数限制、字段参考 trace 和 broad 输出字段集合校验，让 Agent 执行层的治理边界更硬。

## 2026-04-24 13:31:58

### 已完成工作

- 为 resolution 增加通用 `validation_rules` 后处理：支持 `source_type=table_rows` 按 `columns`、`filter`、`exclude`、`target_column` 从标准化表格行筛选最小证据片段，并覆盖模型混入的无关行。
- 增加通用 `operation=count_items` 规则，允许数量字段按 `source_field` 的条目数生成，保证列表字段和计数字段一致。
- 同步收紧 broad / resolution prompt，要求模型在 evidence 预选和字段定案时遵守 `validation_rules`，并排除 `exclude` 命中的证据。
- 新增泛化测试，使用 `selected/rejected` 表格状态验证规则引擎，不在代码中硬编码“文明寝室/模范寝室”等业务词。
- 更新文明寝室真实 PDF 集成脚本，把业务条件放入 task spec 的 `validation_rules`，并重新生成 `output/integration_civilized_dormitory/` 下的集成产物。

### 当前进展

- `tests/file_extraction_agent` 当前全量通过。
- 真实 PDF 集成测试已通过，`summary.json` 中 `passed=true`，抽取结果为 `18栋`、12 个文明寝室房间号和数量 `12`。
- 规则执行保持通用：代码只识别 `validation_rules` 结构，不识别具体业务词。

### 遇到的问题

- 两步抽取里 broad 阶段会把“模范/文明”混合表格块一起作为证据传给 resolution；如果 resolution 完全信模型，模型可能把排除项混入最终结果。
- 单靠 prompt 不能稳定保证列表字段和计数字段一致，因此需要在通用规则层增加结构化校验和覆盖。

### 下一步

- 后续可继续把 `validation_rules` 的支持范围扩展到更多通用规则，例如数值范围、日期归一化、枚举映射和多字段组合校验。

## 2026-04-24 12:33:50

### 已完成工作

- 修复 `extractor_client.py` 的运行配置读取：显式参数缺省时会读取 `BASE_URL`、`OPENAI_API_KEY`、`MODEL` 环境变量。
- 为 `MODEL` 增加代码内默认值 `DEFAULT_MODEL`，支持 `.env` 只提供 `BASE_URL` 和 `OPENAI_API_KEY` 时直接构造模型客户端。
- 补充 `tests/file_extraction_agent/test_extractor_client.py` 覆盖环境变量读取和默认模型行为，并同步更新对应测试说明文档。
- 同步更新 `agent/docs/DESIGN.md` 和 `file_extraction_agent/docs/DESIGN.md`，把模型配置口径改成“显式参数优先，环境变量兜底，MODEL 可选”。

### 当前进展

- 真实 PDF 联调暴露的“`.env` 没有 `MODEL` 就无法跑”问题已收敛到单元测试和实现里。
- `extractor_client` 仍保留显式参数优先级，测试环境和上层调用方可以继续覆盖默认环境变量。

### 遇到的问题

- 之前 `_validate_runtime_config(...)` 只检查入参本身，不读取环境变量，导致用户已经配置 `.env` 后仍必须在代码里额外传 `model`。

### 下一步

- 后续如果需要支持项目内自动加载 `.env` 文件，可单独评估放在 CLI/入口层还是 `extractor_client` 层，避免库函数隐式读取文件路径。

## 2026-04-24 12:13:35

### 已完成工作

- 修正了 `impl/graph.py` 与设计不一致的问题：graph 现在会把同一个 `extractor_client` 继续传给 resolution 阶段，而不是只让 broad 阶段使用模型客户端。
- 修正了 `impl/resolution.py` 的未完成链路：收到 `extractor_client` 时会按 `task_spec.fields` 逐字段请求 `FieldDecision` 结构化输出。
- 新增了 `impl/tools.py`，落地 `get_field_bundle(...)` 与 `lookup_blocks_for_field(...)`，支持 resolution 按字段读取 broad evidence，并在证据缺失时按 `lookup_hints` 从全量 blocks 补查。
- 为补查链路新增 `LookupResult` 内部对象，并让补查成功时把 `LookupRecord` 挂到 `FieldDecision.lookup_records`，最终可映射到对外 trace actions。
- 为 `NormalizedBlock` 补充可选 `block_id`，让补查 trace 能稳定记录命中的 block 来源。
- 更新了 `test_graph.py`、`test_resolution.py`、新增 `test_tools.py` 及对应 `tests/file_extraction_agent/docs/` 测试说明文档。

### 当前进展

- `file_extraction_agent` 当前主链路已经更贴近设计文档：`broad extraction -> FieldEvidence[] -> resolution -> FieldDecision[] -> ExtractionResult(result + trace)`。
- resolution 仍保留 deterministic 兜底逻辑：没有传入模型客户端时，会基于已有 evidence 或一次补查结果做最小定案。
- `tests/file_extraction_agent` 全量通过。

### 遇到的问题

- 之前 graph 只把模型客户端交给 broad，导致 resolution 实际没有按设计通过结构化模型调用完成字段定案。
- 之前缺少 `impl/tools.py`，设计里要求的 field bundle tool 和 global lookup tool 没有代码落点。

### 下一步

- 后续可继续把 resolution 的 tool 使用从 deterministic 兜底推进到真正的 agent/tool 调用策略，并细化 lookup scoring 规则。

## 2026-04-23 11:08:00

### 已完成工作

- 重写了 `file_extraction_agent/docs/DESIGN.md` 中关于 schema 分层的设计说明，明确把外部稳定契约与内部流程契约拆开描述。
- 将设计中的内部契约文件名从 `impl/contracts.py` 收口为更常见的 `impl/schemas.py`，避免把“边界协议”语义误用到单纯字段对象文件上。
- 调整了 `extractor_client.py` 的职责表述，明确它的职责是返回一个可直接 `invoke(...)` 的结构化模型调用器，而不是负责 graph 编排。
- 收紧了 `impl/graph.py` 的职责描述，明确 broad / resolution 的节点串联顺序由 graph 决定，节点内部再通过 `ExtractorClient` 访问模型。
- 把内部流程对象的推荐命名统一改成更通用的方向：`RunOptions`、`ExtractionInput`、`FieldEvidence`、`EvidenceCollection`、`FieldDecision`、`LookupRecord`。

### 当前进展

- `file_extraction_agent` 当前设计文档已经不再把 `BroadTrace`、`ResolvedFieldResult`、`LookupTraceRecord` 这类强实现阶段名视为长期稳定的外部契约名。
- 当前设计口径已经收口成两层：
  - `schemas.py` 负责外部稳定输入输出
  - `impl/schemas.py` 负责内部流程对象
- 当前这轮变更仍停留在设计文档层，尚未开始同步代码与测试实现。

### 遇到的问题

- 之前设计文档里一度把内部流程对象也放进全局 `schemas.py`，导致“对外返回结构”和“当前实现细节”边界不清。
- `contracts.py` 这个命名也会误导读者，以为该文件承载的是跨模块稳定协议，而不是内部字段对象。
- `extractor_client.py` 的表述如果不写清楚，容易让人误解成“graph builder”或“LangGraph 装配器”。

### 下一步

- 下一步如果继续落代码，优先把 `file_extraction_agent/schemas.py` 与 `file_extraction_agent/impl/schemas.py` 的真实边界按这版设计拆开。
- 同步按 TDD 更新对应测试与 `tests/file_extraction_agent/docs/` 下的一一对应测试文档，确保文档、代码和测试口径一致。

## 2026-04-22 15:33:33

### 已完成工作

- 重构了 `file_extraction_agent/schemas.py`，移除旧的 broad candidate 契约，不再定义 `candidate_values`，改为用 `FieldEvidenceBundle` 表达 broad 阶段的字段级证据预选结果。
- 将最终返回对象收口成 `ExtractionResult(result + trace)`：`result` 只保存纯字段结果，`trace` 保存 broad 证据、字段参考、补查痕迹和定案原因。
- 同步重构了 `impl/state.py`、`impl/graph.py`、`impl/resolution.py` 和 `impl/prompts.py`，让内部状态从旧的 `resolved_fields/run_trace` 迁移为 `result_fields/trace_fields`。
- 更新了 `tests/file_extraction_agent/test_schemas.py`、`test_graph.py`、`test_resolution.py`、`test_state.py`、`test_processor.py`、`test_prompts.py` 以及对应测试说明文档，固定新的 result/trace 契约。
- 同步更新了 `file_extraction_agent/docs/DESIGN.md`，明确 broad 只选证据，resolution 负责定案，最终由 backend 持久化 `result` 与 `trace`。

### 当前进展

- `file_extraction_agent` 当前 schema 主线已经变成：
  - `GraphInput` 承载 blocks 主输入
  - `BroadExtractionOutput.fields` 承载 `FieldEvidenceBundle`
  - `ExtractionResult.result.fields` 承载 `ResolvedFieldResult`
  - `ExtractionResult.trace.fields` 承载 `FieldTraceRecord`
- 当前 `resolution.py` 仍是最小 deterministic 占位实现：有 `evidence_texts` 时先用第一条 evidence text 作为占位 final value，后续需要替换为真正的 resolution agent + tools。
- 当前 `tests/file_extraction_agent` 全量通过。

### 遇到的问题

- 旧实现把 broad 的候选值、resolution 的定案结果和运行 trace 混在一起，导致“结果是什么”和“为什么得到这个结果”边界不清楚。
- 这次按你的要求没有做旧结构兼容，而是直接重构，因此同步改了依赖旧 schema 的 graph/state/resolution/prompt 和测试。

### 下一步

- 下一步优先实现 `impl/tools.py`，把 `get_field_bundle(...)` 和 `lookup_blocks_for_field(...)` 作为 resolution 的内部工具落地。
- 后续再把 `resolution.py` 的占位定案逻辑替换成真正的 resolution agent 调用，并把 tool 调用写入 `FieldTraceRecord.lookup_trace`。

## 2026-04-21 20:28:34

### 已完成工作

- 修改了 `file_extraction_agent` 的主输入契约：当前 `GraphInput` 以 `blocks + task_spec` 作为主输入，不再强制要求 `session_id`，并把 `document_id` 固定下沉到每个 `NormalizedBlock` 上。
- 修改了 `file_extraction_agent/input_adapter.py`、`processor.py` 和 `impl/prompts.py`，让入口适配、prompt 组装和后续流程都直接围绕 blocks 主输入工作，不再按 `documents` 列表或 session 级包装组织主链路。
- 保留了 `markdown` / `md_list` 作为备用字段，但明确降级成非主处理链路输入；当前 broad extraction / resolution 的主上下文已经切到 blocks。
- 更新了 `tests/file_extraction_agent/test_schemas.py`、`test_input_adapter.py`、`test_prompts.py`、`test_state.py`、`test_broad_extraction.py`、`test_resolution.py`、`test_graph.py`、`test_processor.py` 以及对应的测试说明文档，覆盖新的 blocks 主输入边界。
- 同步更新了 `file_extraction_agent/docs/DESIGN.md`，把模块设计改写成“all_blocks + task_spec”主链路，并说明 `markdown` / `md_list` 仅作备用。

### 当前进展

- `file_extraction_agent` 当前抽取入口已经收口成：
  - `blocks` 是主输入
  - `task_spec` 定义抽取目标字段
  - `document_id` 在 block 上承担跨文档来源标识
  - `markdown` / `md_list` 只在必要时作为备用文本保留
- 当前相关测试已经全部通过，说明 schema、适配层、prompt、graph 和 processor 这条链路在新契约下是一致的。

### 遇到的问题

- 中间实现阶段仍有不少旧的 `session_id + documents` 假设散落在 schema、prompt、processor 和测试里，需要一轮集中清理才能把 blocks 主输入真正落干净。

### 下一步

- 如果后续继续联调真实模型代理，优先把联调脚本也切到新的 `blocks + task_spec + 显式连接参数` 接口，避免脚本继续沿用旧输入形状。
- 如果后续要进一步简化契约，可以再评估是否保留 `NormalizedDocument` 这个备用文档级结构，还是继续收口到纯 blocks 视图。

## 2026-04-21 19:39:18

### 已完成工作

- 修改了 `file_extraction_agent/processor.py`，把结构化输出策略显式收口到 `extract(..., structured_output_strategy=...)` 接口中，不再让调用方通过配置文件间接指定 `json_schema` / `tool_call` / `auto`。
- 修改了 `file_extraction_agent/extractor_client.py`，让运行时只依赖 `BASE_URL`、`OPENAI_API_KEY`、`MODEL` 这三个环境变量，再配合代码内默认 `temperature=0` 构造客户端；不再读取 `model_client_config.json`，也不再保留旧入口兼容层。
- 按你的删除意图收口了 `model_client_config.json`：当前提交链路把这个文件视为已删除状态，不再让代码对它存在运行时依赖。
- 更新 `tests/file_extraction_agent/test_extractor_client.py` 和 `tests/file_extraction_agent/test_processor.py`，把测试目标改成“结构化输出策略由 processor / extractor_client 显式参数决定”，并删掉旧兼容入口相关测试。
- 同步更新 `tests/file_extraction_agent/docs/test_extractor_client.md`、`tests/file_extraction_agent/docs/test_processor.md` 和 `file_extraction_agent/docs/DESIGN.md`，让文档与当前接口边界一致。

### 当前进展

- `file_extraction_agent` 当前调用边界已经收口成：
  - `processor.extract(...)` 显式决定 structured output strategy
  - `extractor_client.py` 只负责环境变量连接配置和结构化调用封装
  - `graph.py` 继续负责 broad extraction 与 resolution 编排
- 当前 `extractor_client` 运行时不再依赖仓库内本地 JSON 配置文件。

### 遇到的问题

- 中间有一轮改动只把“结构化输出策略”从配置文件里挪走了，但仍残留了对 `model_client_config.json` 的请求参数读取依赖；在你明确指出“那个 json 被我删掉了”后，才继续把这层残留依赖彻底删干净。

### 下一步

- 如果后续需要继续清理历史提交记录，再单独处理已经写进 git 历史里的中间态提交，避免让“短暂依赖过已删除文件”的记录继续留在分支线上。
- 如果要继续联调真实模型代理，再优先围绕当前显式 `structured_output_strategy` 接口去定位代理兼容性问题。

## 2026-04-21 19:04:05

### 已完成工作

- 修改了 `file_extraction_agent/processor.py`，让 `extract(...)` 继续负责外部输入适配和 `ExtractorClient` 准备，但不再自己直接调用模型或手工收口字段结果，而是把 `GraphInput + ExtractorClient` 统一交给 `impl/graph.py`。
- 更新 `tests/file_extraction_agent/test_processor.py`，把入口测试改成校验 `processor` 必须委托 `run_extraction_graph(...)`，并确认它不会自己重复做字段补齐或结果重算。
- 同步更新 `tests/file_extraction_agent/docs/test_processor.md`，把当前入口 pipeline、职责边界和各测试函数说明改成“input_adapter + extractor_client + graph”这条真实链路。

### 当前进展

- `file_extraction_agent` 当前入口边界已经收口成三段：
  - `input_adapter.py` 负责 session 输入校验、task spec 解析和 `GraphInput` 组装
  - `extractor_client.py` 负责模型连接配置、structured output 策略和统一 `invoke(...)` 封装
  - `impl/graph.py` 负责 broad extraction 与 resolution 的内部节点编排
- `processor.py` 现在只负责把这三层串起来，不再自己承担内部节点执行细节。

### 遇到的问题

- 之前 `processor.py` 一边负责入口参数适配，一边直接调用 extractor client、拼 broad extraction prompt、再自己做 resolution 收口，导致“入口层”“模型调用封装层”和“内部图编排层”三者边界混在一起。

### 下一步

- 后续如果继续扩展 `file_extraction_agent`，优先把行为落到 `impl/graph.py` 或内部节点中，不再把阶段逻辑回灌到 `processor.py`。
- 如果需要补更多入口回归，优先围绕“processor 是否只负责组装和委托”这个边界继续加测试。

## 2026-04-21 18:42:35

### 已完成工作

- 新增了 `file_extraction_agent/impl/resolution.py`，把 field resolution 第二阶段落成独立内部节点，并提供按 `task_spec.fields` 顺序收口 broad output 的实现。
- 修改 `file_extraction_agent/processor.py`，不再内联维护字段定案逻辑，改为复用 `impl/resolution.py` 的收口函数。
- 新增 `tests/file_extraction_agent/test_resolution.py`，覆盖缺失字段补失败、重复候选去重、多候选冲突失败，以及 `run_resolution(...)` 写回 `GraphState` 的行为。
- 同步补齐 `tests/file_extraction_agent/docs/test_resolution.md`，说明 resolution 节点的处理链路和每个测试函数的验证目标。

### 当前进展

- `file_extraction_agent` 的两阶段内部节点现在已经同时具备：
  - `impl/broad_extraction.py` 负责第一阶段候选抽取
  - `impl/resolution.py` 负责第二阶段字段定案
- 当前 `processor.py` 已经改为直接复用这两个阶段中的 resolution 收口逻辑，后续如果继续落地 `impl/graph.py`，可以在不改定案规则的前提下把编排进一步迁移到图节点层。

### 遇到的问题

- 当前工作区里还有本次任务之外的未提交改动和未跟踪目录，因此提交时需要只 stage resolution 相关文件，避免把不相关内容混入本次提交。

### 下一步

- 继续落地 `impl/graph.py`，把 broad extraction 和 resolution 通过统一 graph state 串起来。
- 等 graph 落地后，再评估 `processor.py` 是否进一步收口成只负责输入适配、client 准备和 graph 调用。

## 2026-04-21 11:07:00

### 已完成工作

- 新增了 `file_extraction_agent/impl/broad_extraction.py`，把 broad extraction 第一阶段落成独立内部节点。
- 新增 `tests/file_extraction_agent/test_broad_extraction.py`，覆盖 broad extraction 节点调用客户端、请求 `BroadExtractionOutput` 并写回状态的行为。
- 同步补齐 `tests/file_extraction_agent/docs/test_broad_extraction.md`，说明该测试文件对应的节点链路和覆盖点。

### 当前进展

- broad extraction 内部节点已先落地，但 `processor.py` 仍按当前入口边界直接持有 extractor client 并调用结构化抽取。
- 后续 `impl/graph.py` 落地后，可以再评估是否把 `processor.py` 的 broad extraction 调用迁移到图节点编排中。
- 当前 `tests/file_extraction_agent` 全量通过。

### 遇到的问题

- 当前 `processor.py` 仍保留直接 broad extraction 调用和最小字段收口逻辑，真正的 `impl/graph.py` / `impl/resolution.py` 尚未落地。

### 下一步

- 继续按同一模式落地 `impl/graph.py` 和 `impl/resolution.py`，再决定是否由 graph 统一接管 broad extraction 与 resolution 编排。

## 2026-04-21 10:33:03

### 已完成工作

- 新增了 `file_extraction_agent/input_adapter.py`，把 `session_id`、`documents`、`task_spec` / `task_spec_name`、`run_config`、`metadata` 收敛成统一的 `GraphInput`。
- 修改了 `file_extraction_agent/processor.py`，让 `extract(...)` 先委托 `input_adapter.build_graph_input(...)`，再继续执行 broad extraction 和字段收口。
- 新增 `tests/file_extraction_agent/test_input_adapter.py`，覆盖“显式 `task_spec`”和“按 `task_spec_name` 加载”的两条输入适配路径。
- 更新 `tests/file_extraction_agent/test_processor.py`，补充 `processor` 必须通过 `input_adapter` 组装图输入的回归测试。
- 同步更新 `file_extraction_agent/docs/DESIGN.md`，把当前已落地的输入适配层、`processor` 职责边界和 `GraphInput` 组装链路写回设计文档。
- 同步补齐 `tests/file_extraction_agent/docs/test_input_adapter.md` 与 `tests/file_extraction_agent/docs/test_processor.md`，让测试说明和当前实现保持一致。

### 当前进展

- `file_extraction_agent` 当前入口边界已经落地成两层：
  - `input_adapter.py` 负责 session 输入校验、task spec 解析和 `GraphInput` 组装
  - `processor.py` 负责接住外部调用参数、调用适配层并继续抽取流程
- 相关测试已经覆盖了输入适配与入口委托这两个关键边界，当前 `tests/file_extraction_agent` 全量通过。

### 遇到的问题

- 现有 `processor` 测试里原本直接依赖 `TASK_SPECS_DIR` 挂在 `processor.py` 上；拆出 `input_adapter.py` 后，为了兼容现有测试与调用方式，需要在 `processor.py` 保留一个向后兼容别名。
- 当前工作区里还有这次任务之外的未提交改动，因此提交时需要只 stage 本次相关文件，避免把别的内容混进来。

### 下一步

- 后续如果继续落地 `impl/graph.py`、`impl/broad_extraction.py` 和 `impl/resolution.py`，可以直接复用这次固定下来的 `GraphInput` 入口。
- 如果后面要再收紧外部调用面，可以评估是否逐步减少 `processor.py` 对旧符号别名的兼容暴露范围。

## 2026-04-21 10:16:36

### 已完成工作

- 更新了 `file_extraction_agent/docs/DESIGN.md`，删掉模块内部的 `impl/normalization.py` 设计层，不再保留“内层再做一次 GraphInput 归一化”的职责表述。
- 在设计里新增外层 `input_adapter.py`，明确由外部输入适配层负责 session 输入校验、协议适配和 `GraphInput` 一次性组装。
- 收紧 `processor.py` 的职责表述，改成消费已收敛的 `GraphInput`、加载 task spec 并编排 graph，不再和输入归一化层重复分工。

### 当前进展

- `file_extraction_agent` 当前的推荐边界已经收敛成：
  - 外部 `input_adapter.py` 负责输入校验、协议适配、`GraphInput` 组装
  - `processor.py` 负责 task spec 加载和流程编排
  - `impl/graph.py` 从 `GraphInput` 直接开始 broad extraction / resolution
- `GraphInput` 现在在设计上只允许组装一次，避免外层和模块内部重复归一化。

### 遇到的问题

- 之前设计里同时写了“`processor.py` 组装 `GraphInput`”和“`impl/normalization.py` 继续组装 `GraphInput`”，职责边界互相冲突。
- 如果不把 `GraphInput` 的生产者固定到外层适配层，后续实现时很容易出现双重归一化和多处兜底。

### 下一步

- 后续实现时按这版边界补 `input_adapter.py`，让它成为 `GraphInput` 的唯一入口。
- 再继续收敛 `processor.py` 的真实签名和 `impl/graph.py` 的调用方式，确保代码实现和当前设计一致。

## 2026-04-20 16:45:20

## todo
DESIGN.md有雷，
- `impl/normalization.py`
  接收 `processor.py` 已经收拢好的 session 级输入和 task spec，继续做进入 graph 前的内部归一化，产出 `schemas.py` 中定义的 `GraphInput`。
- 曾误设独立 validation 模块
  原设想是做候选清洗、字段类型归一化、局部规则校验和状态归类；当前已经收敛为 `resolution.py::_apply_validation_rules(...)` 的字段定案后处理。
这条职责不再单独拆文件。
没有将processor.py的数据核验单开一个input_adapter.py来做

### 已完成工作

- 更新了 `file_extraction_agent/docs/DESIGN.md`，把 `input_adapter.py` 的职责从“校验 + task spec 加载 + GraphInput 组装”收紧成“只负责输入校验和协议适配”。
- 明确 `processor.py` 继续负责 `task spec` 加载和流程编排，不把这部分职责前移到独立输入适配文件。
- 明确 `impl/normalization.py` 的输入改成“已校验输入 + task spec”，它负责内部归一化并组装 `GraphInput`，而不是承担第一层外部输入适配。

### 当前进展

- `file_extraction_agent` 入口前的职责现在拆成了三段：
  - `input_adapter.py` 负责外部 payload 校验和协议适配
  - `processor.py` 负责 `task spec` 加载和流程编排
  - `impl/normalization.py` 负责把已收敛输入组装成 `GraphInput`
- 这样后续实现时，外部边界问题和模块内部编排问题不会继续混在同一个文件里。

### 遇到的问题

- 之前把 `input_adapter.py` 写得过宽，连 `task spec` 加载都放了进去，会让“外部输入适配”和“业务流程编排”再次耦合。
- 如果不把这层职责及时收紧，后续实现 `processor.py` 时容易出现入口文件和编排入口之间的职责争抢。

### 下一步

- 后续写 `input_adapter.py` 时，只围绕输入校验、协议适配和类型收敛建模，不再把 `task spec` 加载塞进去。
- 再按这条边界继续落地 `processor.py` 与 `impl/normalization.py` 的实现和测试。

## 2026-04-20 16:35:46

### 已完成工作

- 更新了 `agent/docs/DESIGN.md` 和 `file_extraction_agent/docs/DESIGN.md`，把 `processor.py` 的职责从“负责输入校验”收口成“只接收外部已校验输入并做流程编排”。
- 明确 `file_extraction_agent` 不负责对外部原始 payload 做第一层必填校验或协议兜底，这一步应由外部层先完成。
- 同步把 `impl/normalization.py` 的职责改写成“处理已校验输入的内部归一化”，避免后续实现时把坏输入兜底逻辑重新塞回模块内部。

### 当前进展

- `file_extraction_agent` 的边界现在更清楚了：
  - 外部层负责 session 输入校验和协议适配
  - `processor.py` 负责 task spec 加载、`GraphInput` 组装和 graph 编排
  - `normalization.py` 负责已校验输入到内部契约的转换
- 这样后续真正写 `processor.py` 时，可以直接围绕“已校验 typed input”建模，而不是一边编排一边做原始 payload 防御式校验。

### 遇到的问题

- 之前文档把 `processor.py` 写成“对外统一入口并负责输入校验”，容易把外部协议校验职责和模块内部编排职责混在一起。
- 如果不先把这个边界写死，后续实现时很容易出现 route、backend 聚合层、`processor.py` 三处重复校验同一份输入的问题。

### 下一步

- 后续实现 `processor.py` 时，直接按“输入已经在外部校验完成”的前提设计入口签名和内部流程。
- 再根据这条边界继续收敛 `normalization.py`、`graph.py` 和对应测试的输入模型。

## 2026-04-20 16:25:47

### 已完成工作

- 补齐了 `file_extraction_agent/extractor_client.py`，现在会从环境变量读取 `BASE_URL`、`OPENAI_API_KEY`、`MODEL`，并构造真正可调用的结构化抽取客户端。
- 新增了 `file_extraction_agent/model_client_config.json`，把结构化输出策略从连接配置中拆开，单独管理 `json_schema`、`tool_call`、`auto` 和 fallback 顺序。
- 在 `extractor_client.py` 中加入结构化输出协议回退逻辑：优先尝试 `json_schema`，兼容接口不支持时再退到 `tool_call`；内部把 `tool_call` 映射到 LangChain 的 `function_calling`。
- 补齐了 `tests/file_extraction_agent/test_extractor_client.py` 和对应的 `tests/file_extraction_agent/docs/test_extractor_client.md`。
- 同步更新了 `agent/docs/DESIGN.md` 和 `file_extraction_agent/docs/DESIGN.md`，把连接配置与策略配置的分工、以及结构化输出 fallback pipeline 写清楚。

### 当前进展

- `file_extraction_agent` 这一层现在已经有了可直接复用的模型客户端入口，后续 `processor.py`、`broad_extraction.py` 和 `resolution.py` 可以直接依赖这个 client，而不用各自关心 OpenAI 兼容接口的差异。
- 模型配置职责已经拆开：
  - 环境变量负责服务地址、密钥和模型名
  - `model_client_config.json` 负责结构化输出协议和请求参数
- 新增的客户端测试已经覆盖固定 `json_schema`、固定 `tool_call`、以及 `auto` 回退三种主要路径。

### 遇到的问题

- 一开始把结构化输出固定写死成 `json_schema`，但 OpenAI 兼容接口对这一协议的支持并不稳定，容易在切换供应商或代理层时直接失败。
- LangChain 真实接口里对应的方法名不是仓库内部更直观的 `tool_call`，而是 `function_calling`，因此需要在 `extractor_client.py` 里做一层映射，避免配置语义和底层 SDK 术语耦合。
- 顺手回归时发现 `tests/file_extraction_agent/test_schemas.py` 当前依赖一个现存不一致：它导入了 `NormalizedBlock`，但当前 `schemas.py` 里没有这个符号；这不是这次 client 改动引入的问题。

### 下一步

- 在 `processor.py` 或后续 graph 节点实现中接入 `build_extractor_client_from_env(...)`，把这层客户端真正串进 broad extraction 和 field resolution 流程。
- 等 `schemas.py` 与 `test_schemas.py` 的现存不一致单独收敛后，再做更完整的 file extraction agent 回归验证。

## 2026-04-20 16:15:33

### 已完成工作

- 新增了 `file_extraction_agent/schemas.py` 第一版数据契约，实现了 `TaskSpec`、`GraphInput`、`BroadExtractionOutput`、`ResolvedFieldOutput`、`ExtractionResult` 等基础结构。
- 明确 `GraphInput` 接受的是 backend 聚合后的 session 级输入，顶层必须带 `session_id`，文档级输入必须带 `document_id`。
- 把 `NormalizedDocument.blocks` 从裸 `dict` 列表收紧成结构化的 `NormalizedBlock` / `NormalizedBoundingBox`，明确块级文本、页码、bbox、类型和块级元信息字段。
- 补齐了 `tests/file_extraction_agent/test_schemas.py` 与对应的 `tests/file_extraction_agent/docs/test_schemas.md`，并完成通过验证。

### 当前进展

- `file_extraction_agent` 这一层已经有了可执行的第一版 schema 契约，后续可以直接围绕这些对象继续实现 `processor.py`、`normalization.py` 和 `graph.py`。
- 入口输入的层级已经收敛清楚：这一层不再按“直接吃 document_processor 原始返回值”建模，而是按“backend 补齐业务标识后的 session 级输入”建模。
- 文档块输入也已经从宽松字典收敛成明确对象，后续不需要在实现里长期依赖裸字典字段访问。

### 遇到的问题

- 一开始把 schema 顶部说明写成了流程描述，和这个文件“只定义接受什么、产出什么”的职责不完全匹配，后续已经改成契约导向表述。
- `blocks` 最初用 `list[dict[str, Any]]` 占位虽然快，但会让块结构含义不清楚，也不利于后续 normalization 和 validation 层复用。

### 下一步

- 继续按 TDD 补 `processor.py`，把 session 级输入校验和 task spec 加载落到真正入口。
- 再补 `impl/normalization.py`，把外部 session 输入整理成稳定的 `GraphInput`。
- 然后继续落地 `impl/graph.py` 和后续 broad extraction / resolution 骨架。

## 2026-04-20 13:28:33

### 已完成工作

- 更新了 `file_extraction_agent/docs/DESIGN.md` 中关于 `GraphInput`、`normalization.py` 和 `graph.py` 的职责划分。
- 明确 `GraphInput` 属于 `schemas.py` 中定义的数据契约，不再把它视为 `graph.py` 的内部模板。
- 明确 `impl/normalization.py` 是 graph 外的预处理步骤，由 `processor.py` 先调用，把外部输入整理成 `GraphInput` 后再交给 `impl/graph.py`。

### 当前进展

- 当前设计已经把“数据契约”和“流程内部状态”拆开：
  - `schemas.py` 负责 `GraphInput` 等静态输入输出结构
  - `impl/state.py` 负责流程运行中的中间状态
- 当前设计已经把“输入整形”和“两阶段处理流程”拆开：
  - `impl/normalization.py` 负责外部输入归一化
  - `impl/graph.py` 从 `GraphInput` 开始执行 broad extraction 和 field resolution

### 遇到的问题

- 之前的设计表述里，`normalization.py` 虽然放在 `impl/`，但它处于 graph 内还是 graph 外不够明确，容易让后续实现时把输入整形逻辑混进 `graph.py`。
- `GraphInput` 如果写进 `graph.py`，会让数据契约和流程实现耦合，不利于 `normalization.py` 和 `graph.py` 分层。

### 下一步

- 在真正开始实现前，先按这版设计补 `schemas.py`，明确 `NormalizedDocument`、`GraphInput`、`ExtractionResult` 等结构。
- 再按 TDD 顺序补 `processor.py`、`impl/normalization.py`、`impl/graph.py` 和对应测试。

## 2026-04-19 23:44:10

### 已完成工作

- 补齐了 `file_extraction_agent` 第一版 `docs/DESIGN.md`。
- 明确了模块职责边界：这一层只负责标准化文档上的字段抽取与字段定案，不负责原始文件解析、写库或外层路由判定。
- 收敛了目录结构和分层方案，确定 `state.py`、`prompts.py` 放在 `impl/` 下，作为内部执行细节管理。
- 对设计文档做了一轮表述收敛，去掉了不必要的 AI 相关措辞，改成偏工程实现的描述方式。

### 当前进展

- 已确定第一版主链路为：输入归一化 -> broad extraction -> broad output 校验与标准化 -> field resolution -> `ExtractionResult`。
- 已确定 `graph.py` 的入口应接收归一化后的 `GraphInput` 和抽取执行客户端，而不是大量松散参数。
- 已明确 `task_specs/*.json`、结构化输出对象以及两阶段处理之间的职责边界。

### 遇到的问题

- `file_extraction_agent` 目录当前只有空白的 `docs/DESIGN.md` 和 `docs/DEVLOG.md`，设计边界、目录职责和执行流程都需要先补文档才能支撑后续实现。
- 文档初稿中带有偏背景化、工具化的表达，需要收敛成更稳定的模块设计语言。

### 下一步

- 按 TDD 顺序补 `schemas.py`、`processor.py`、`extractor_client.py` 和 `impl/` 下的执行骨架。
- 同步建立 `tests/file_extraction_agent/` 及其 `tests/docs/` 一一对应测试文档。
- 在实现过程中继续评估 `docs/DESIGN.md` 是否需要随代码落地补充细节。
