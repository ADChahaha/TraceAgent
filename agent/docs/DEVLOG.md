last updated: 2026-09-05 13:23:11

## 2026-09-05 13:23:11

### 已完成工作

- 内部事件统一为字典，仅在 stream 输出边界编码 SSE。
- 删除 fake 专用循环，统一 LangGraph 执行路径。
- 同步设计和测试文档。

### 验证

- TDD red：三项目标测试失败。
- 重构后在 agent-gate 运行全套测试：151 passed。

### 当前进展

- 代码、测试及设计文档已同步。

## 2026-09-05 12:42:46

### 已完成工作

- completion_id 校验 → 独占创建工作目录 → 清理前检查所属父目录，拒绝路径越界及已有目录复用。
- HTML 表格展开 rowspan/colspan，按最大列数输出 Markdown 并转义竖线，避免合并表头导致金额丢列。
- 工具返回、异常和超时共用唯一结果收口；SSE 与模型 ToolMessage 使用相同结果和 tool_call_id，丢弃迟到结果。
- metadata.task_id → GraphState → 按任务及文档版本复用 embedding 缓存；缓存保存相对路径，命中后绑定当前 completion 的引用路径。
- SSE 终态仅按 event 字段精确判断，正文和注释中的终态字样不再影响生命周期。
- 同步设计文档和各测试文件对应的测试说明。

### 验证

- TDD red：相关测试 `28 failed, 58 passed`，失败对应上述目标行为。
- 激活 agent-gate，在 agent/ 执行 `python -X utf8 -m pytest tests -q -p no:cacheprovider --tb=short`，结果 `154 passed`；UTF-8 模式避免 Windows 默认编码影响源码读取测试。

### 下一步

- 按用户要求暂不修改 backend；其历史重建仍按工具名称配对，同名并行工具的 tool_call_id 配对适配留待后续。

## 2026-09-03 18:23:45

### 已完成工作

- `run_completion_graph_stream` 在 `should_stop` 触发时（外部取消），若最后产出的 provider 消息带尚未执行的 `tool_calls`，由新增 `_backfill_pending_tool_cancels` 为每个未配对 tool 补一条 `ok:false` / "tool execution cancelled" 的 `tool_completed` 回复，再以 `completion.cancelled` 收口，避免悬垂 tool_call；已跑成功的 tool 不被重复追加。
- 新增测试：`test_should_stop_backfills_cancel_tool_replies_for_pending_tool_calls`（补取消占位）、`test_should_stop_after_fulfilled_batch_does_not_duplicate_tool_replies`（不重复追加已成功 tool）。
- 同步 `service/file_extraction_agent/docs/DESIGN.md`、`agent_loop.md` 及 `tests/file_extraction_agent/docs/test_graph.md`。

### 当前进展

- `tests/file_extraction_agent` + `routes/test_file_extraction_agent_route.py` 全量 `88 passed`（agent/.venv）。

### 下一步

- 评估 backend 侧对「并行 tool_calls 事件顺序乱序」的适配（本轮未处理残缺 tool_calls）。

## 2026-09-03 17:54:48

### 已完成工作

- 把 `run_completion_graph_stream` 及其私有辅助（`_append_completion_event` / `_append_failure_event` / `_append_source_index_event` / `_file_tree_lines` / `_resolution_failed` / `_failure_reason` / `_sse` / `_plain`）从 `core/graph.py` 平移到 `manager.py`；`core/graph.py` 只保留 `GraphState` + `build_graph_state`，聚焦"状态定义与图构建"，不再做事件组装与 SSE 收口。
- cancel 外置：`run_completion_graph_stream` 新增可选 `should_stop` 回调，在每步之间检查外部取消信号并决定是否以 `completion.cancelled` 收口；从 `GraphState` 移除 `cancel_requested` 字段，`core/loop.py` 的 `should_continue` / `should_continue_after_tools` 不再读取消，loop 回归纯 model/tool 循环。取消判定收敛到 manager（`_produce` 注入 `should_stop=lambda: self.cancel_requested`，`terminate()` 不再写 `state.cancel_requested`）。
- 同步 `service/file_extraction_agent/docs/DESIGN.md`、`agent_loop.md`、`flowchart.md` 及测试文档（`test_graph.md`、`test_manager.md`）。

### 当前进展

- `tests/file_extraction_agent` + `routes/test_file_extraction_agent_route.py` 全量 `86 passed`（agent/.venv）。

### 下一步

- 评估 backend 侧对「并行 tool_calls 事件顺序乱序」的适配（本轮未处理残缺 tool_calls）。

## 2026-09-03 16:09:12

### 已完成工作

- `file_extraction_agent` QA completion 工具执行改为并行 + 超时：新增 `_execute_tools_parallel`（`core/loop.py`），单条 assistant 消息的多个 tool_calls 经 `ThreadPoolExecutor` 并发执行，各自带 `tool_execution_timeout`（`RunOptions` 新增，默认 60s）超时并返回 `tool execution timeout` 结果；保持返回顺序与 `tool_call_id` 匹配。
- 移除 `ToolNode` 串行执行，LangGraph `tools` 节点改为 `run_tools`，新增 `should_continue_after_tools`，并让 `should_continue` 认 `cancel_requested`；`recursion_limit` 改为固定 `RESOLUTION_RECURSION_LIMIT`；`max_tool_calls` 不再作为硬限（`_normalize_run_options` 去掉 `>0` 校验）。
- 线程安全：`GraphState` 新增 `events_lock`，`base.emit_event/record_action` 在锁内更新 `next_seq/events/actions`，保证并行写入 seq 唯一、不丢失。
- cancel 语义分场景：`ActiveCompletion.terminate()` 仅当无运行中工具批次时立即放 cancel sentinel；若正在执行工具批次则记 `_cancel_deferred`，等批次跑完/超时后由 producer 以 `completion.cancelled` 收口（新 `test_terminate_defers_cancel_until_active_tool_batch_settles`）。`commit_events/commit_terminal_event` 允许 deferred cancel 批次事件继续入队。
- 把「assistant 消息 + 整批 tool 执行」绑定为一个原子单元：模型产出带 tool_calls 的消息时（`core/loop.py` 的 `call_model` / fake loop）即置位 `tool_batch_active`，直到该批工具全部执行完（含各自超时产出的 timeout 占位结果，timeout 也是合法 tool 结果）才复位；从而让「产消息 → 批执行」整段时间内的 cancel 都走 deferred，保证 tool 结果不缺失。（新 `test_tool_batch_active_spans_message_and_tool_execution`）
- 同步 `service/file_extraction_agent/docs/DESIGN.md`、`agent/docs/API.md`、`README.md`、`agent_loop.md` 及 `tests/file_extraction_agent/docs/test_loop.md`、`test_manager.md`。

### 当前进展

- `tests/file_extraction_agent` 全量 `75 passed`（agent/.venv）；含 `routes/test_file_extraction_agent_route.py` 共 `83 passed`。既有 `tests/document_processor` 1 例因 Windows GBK 编码读取失败（与本次改动无关）。

### 下一步

- 评估 backend 侧对「并行 tool_calls 事件顺序乱序」的适配（本轮未处理残缺 tool_calls）。

## 2026-09-02 16:31:42

### 已完成工作

- 将 `impl/` 改为 `core/` 并按职责重命名：`html_index→documents`、`html_tools→tools`、`model_factory→model`、`resolution_new→loop`；`html_state` 的 `GraphState/build_graph_state` 并入 `graph.py`。
- 测试同步改名（`test_html_index_new→test_documents`、`test_html_tools_new→test_tools`、`test_resolution_new→test_loop`），import 全部迁到 `core.*`。
- 同步 `service/file_extraction_agent` 的 README/DESIGN/`__init__`、`core/__init__` 边界与父级 README/DESIGN/API，测试文档；清理 `_ACTIVE_COMPLETIONS` 引用；修复 documents.py 的 `\<` 转义警告。

### 当前进展

- `tests` 全量 `106 passed`（`agent/.venv`，UTF-8 模式）。

### 下一步

- 可选：整体同步 `file_extraction_agent/README.md` 其余过时描述。

## 2026-09-02 15:36:33

### 已完成工作

- 把单 completion 的完整运行收进 `ActiveCompletion`：构造时注入 state（GraphState）与 resolution_model，由它自行保有 queue + 锁、stream()（起 producer 线程 + 消费队列产 SSE + finally 清理 workspace）、_produce()（跑 impl/graph.run_completion_graph_stream 投事件）、terminate()/get_status()。
- `CompletionManager` 退化为薄协调者：只做多 completion 的注册表 + create 装配（state+model -> ActiveCompletion -> 注册 -> 返回 stream）+ terminate/status 转发 + _managed_stream 收尾移除注册表。
- 新增 `test_active_completion_owns_terminate_get_status_and_terminal_uniqueness`；同步 `service/file_extraction_agent/docs/DESIGN.md` 与测试文档。

### 当前进展

- `tests` 全量 `106 passed`（`agent/.venv`，UTF-8 模式）。

### 下一步

- 可选：整体同步 `file_extraction_agent/README.md` 其余过时的 `inspect` / `evidence://` / 虚拟树描述。

## 2026-09-02 15:15:43

### 已完成工作

- 将 `processor.py` 改名为 `manager.py` 并重整职责：`CompletionManager` 类统一管理 completion 生命周期（create/terminate/get_status + 注册表 + producer/consumer + 取消清理），`prepare_completion_state` 入参准备保留在同一模块；`_produce` 直接调 `impl/graph.run_completion_graph_stream`，去除原先的模块级 passthrough。
- 删除 `processor.py`；公开 API `create_completion_stream` / `cancel_completion` 移到 `manager`，`routes` 与测试的 import / monkeypatch 目标同步改为 `manager`。
- 测试 `test_processor.py` 改名 `test_manager.py`，校验测试与 `CompletionManager` 测试一并迁入；同步 `service/file_extraction_agent/docs/DESIGN.md`、README、`__init__/impl` 边界、父级 `agent/README.md` / `agent/docs/DESIGN.md` / `agent/docs/API.md` 与 route 测试文档。

### 当前进展

- `tests` 全量 `105 passed`（`agent/.venv`，UTF-8 模式）。

### 下一步

- 可选：整体同步 `file_extraction_agent/README.md` 其余过时的 `inspect` / `evidence://` / 虚拟树描述。

## 2026-09-02 14:53:24

### 已完成工作

- 把 document-QA chat completion 生命周期收进 `processor.CompletionManager` 类，提供 `create(...)`（校验强类型入参、落盘文件树、注册 runtime、启动 producer、返回 SSE 流）、`terminate(completion_id)`（取消）、`get_status(completion_id)`（查询状态）三个方法，内部持有本进程注册表 + 锁；替换掉原先散落的模块级 `_ACTIVE_COMPLETIONS` 注册表。
- 模块级 `create_completion_stream` / `cancel_completion` 变为到进程内单例 `completion_manager` 的薄委托，HTTP 路由与既有调用方不变。
- 新增 `test_completion_manager_*`（create 返回 SSE、create 先注册再 terminate 收口、terminate not_found、get_status None）并同步 `test_manager.md`；全量 `105 passed`。

### 当前进展

- `tests` 全量 `105 passed`（`agent/.venv`，UTF-8 模式）。

### 下一步

- 可选：整体同步 `file_extraction_agent/README.md` 其余过时的 `inspect` / `evidence://` / 虚拟树描述。

## 2026-09-02 14:46:02

### 已完成工作

- 移除 `DocumentQaCompletionInput` 包装对象与 `input_adapter.py`，把入口校验、workspace 派生和 `materialize_tree` 落盘折叠进 `processor.prepare_completion_state(...)`，由它直接构建 `GraphState`（校验失败抛 `ValueError`，HTTP 映射 422）。
- `impl/html_state.py` 只保留 `GraphState`，去掉 `completion_input` 字段；`impl/graph.py` 的 `run_completion_graph_stream` 改为直接接收 `GraphState`。
- `processor` 生命周期/取消改为传递 `state: GraphState`，`_cleanup_workspace` 从 `state.document` 清理；`create_completion_stream` / `_produce_completion_events` / `run_completion_graph_stream` 一并收紧。
- 折叠 `test_input_adapter` 的校验测试进 `test_processor`（改用 `prepare_completion_state`），删除 `test_input_adapter.py` 及其文档；`test_graph` / `test_resolution_new` / `test_html_tools_new` 改用 `prepare_completion_state` 直接产出状态。
- 同步 `service/file_extraction_agent/docs/DESIGN.md`、`impl/__init__.py`、`file_extraction_agent/README.md` 与父级 `agent/README.md` / `agent/docs/DESIGN.md` / `agent/docs/API.md` 中的 `input_adapter` 引用。

### 当前进展

- `tests` 全量 `101 passed`（`agent/.venv`，UTF-8 模式）。

### 下一步

- 可选：整体同步 `file_extraction_agent/README.md` 中其余过时的 `inspect` / `evidence://` / 虚拟树描述。

## 2026-09-02 14:21:12

### 已完成工作

- 将 `file_extraction_agent` 与 `routes/file_extraction_agent` 的公开输入边界全部强类型化：`create_completion_stream` 只接收 `list[InputDocument]` / `list[DocumentQaMessage]` / `ModelConfig | None` / `RunOptions | None`；`build_completion_input` 同构收紧。
- 移除 `input_adapter` / `html_index` / `model_factory` 中对 dict / duck-typed object 的归一化接受，错误输入在 Pydantic 构造或语义校验时即被拒收。
- `html_index.materialize_tree` 改为接受 `list[InputDocument]`；`model_factory` 的 `build_resolution_model` / `build_chat_model` / `normalize_model_config` 与 `graph` / `resolution_new` 的 resolution model 类型收口到 `ChatModelFallbackChain`。
- HTTP 层 `_model_config` 改为构造 `ModelConfig` 对象（不再返回 dict）；`ChatCompletionRequest.run_options` / `model_config` 收紧为强类型。
- 同步更新受影响的测试与各 `tests/docs/*.md`、`docs/DESIGN.md`，测试全部改用强类型构造。

### 当前进展

- `tests` 全量 `101 passed`（`agent/.venv`，UTF-8 模式）。
- 目标系统无 conda，使用项目自带 `.venv`。

### 下一步

- 可选：同步 `file_extraction_agent/README.md` 中过时的 `inspect` / `evidence://` / dict 输入示例。

## 2026-09-02 17:30:00

### 已完成工作

- 删除 agent routes 的专用 DOCX 端点 `POST /v1/document-processor/docx/process`，并移除了旧兼容路径 `POST /v1/ocr/process`；现在文档标准化只暴露单一 `POST /v1/document-processor/process`，由 `file_type`（可选，缺省看文件名后缀）分流 PDF/DOCX。
- 同步更新 route 测试（DOCX 改走通用端点、新增「docx 专用端点已移除」和「旧 ocr 兼容端点已移除」两个 404 断言）、对应测试说明文档，以及 agent 顶层 README/API/DESIGN 和 `service/document_processor` 的 README/API 文档；`GET /v1/ocr/capabilities` 保留。

### 当前进展

- `tests/routes` 与 `tests/document_processor` 全量通过。

### 下一步

- backend `services/agent_client.py` 仍把 docx 路由到已移除的 `/v1/document-processor/docx/process`（本次按用户要求只改 agent 侧，backend 未同步）；需在 backend 侧把 docx 指向 `/v1/document-processor/process` 才能恢复 DOCX 处理。

## 2026-09-01 12:00:00

### 已完成工作

- 将 `file_extraction_agent` 的「虚拟文件树」重构为「真实文件树」：`html_index.materialize_tree` 把文档落盘成 `DocumentFileTree`（每个 paragraph/list/table 写成一个 `.md`，表格整表一个文件），目录/文件按数字前缀保序。
- 删除 `path_id` / `evidence://` / `inspect` 及句(sentence)/列表项/表格行级 selector；工具收敛为 `ls` / `grep`(调用真实 ripgrep，stdout 原样返回) / `read`；引证直接用真实 `.md` 文件路径。
- `source_indexed` 事件不再携带 `document_tree` + `source_selectors`，改为暴露 `workspace_root` 和逐层 `tree` 清单。
- workspace 根默认 `agent/data/qa_workspace`（可用 `FILE_EXTRACTION_AGENT_WORKSPACE_ROOT` 覆盖）；每 completion 一个子目录，completion 结束清理。
- 重写 `test_html_index_new` / `test_html_tools_new` / `test_graph` / `test_input_adapter` / `test_resolution_new` 等测试及对应 test 文档、`tools.md`、`agent_loop.md`、DESIGN/API 文档。

### 当前进展

- `tests/file_extraction_agent` 全量通过；`tests/document_processor` 全量通过。
- 跨仓库的 backend/前端 replay 高亮契约因 `source_selectors` 删除而改变，需另起任务在 backend/前端同步。

### 下一步

- 对接 backend/前端按新的 `source_indexed(workspace_root + tree)` 和真实文件路径 evidence 做 replay 高亮。

## 2026-05-23 00:00:00

### 已完成工作

- 将 `file_extraction_agent` 从字段抽取重构为多文档 QA chat completion agent，输入改为 `completion_id + documents + messages + memory`。
- HTTP 入口改为 `POST /v1/document-qa/chat/completions` 和 `POST /v1/document-qa/chat/completions/{completion_id}/cancel`，旧 `/v1/file-extraction-agent/extract/stream` 不再暴露。
- 模型工具集收口为 `tree / grep / read / inspect`，证据通过 `model_message` 中的 Markdown `evidence://` link 在过程里呈现。
- agent 仅保存 active completion 的内存取消状态；多轮 messages、memory 和事件持久化由 backend 负责。
- 同步更新 agent 顶层 README/API/DESIGN、`file_extraction_agent` README/DESIGN、backend QA 草案设计，以及对应测试说明文档。

### 验证

- `conda run -n agent-gate python -m pytest tests -q`，结果 `91 passed`。

## 2026-05-13 21:12:49

### 已完成工作

- `file_extraction_agent` 的 resolution prompt 现在会展开 enum variants，并提示 `write_field` 使用 tagged enum object，例如 `{"variant": "Entailment", "value": null}`。
- `write_field` 字段结果新增系统反查的 `evidence_texts`，由 evidence selector 映射回 paragraph sentence、list item 或 table row 文本，用于前端回放和实验 scorer。
- ContractNLI hard5 OCR runner 默认切到 `enum_decision + agent_only`，enum schema 不再使用旧 `set_field/evidence_ids` 文案。

### 验证

- `conda run -n agent-gate python -m pytest tests/file_extraction_agent tests/routes/test_file_extraction_agent_route.py ../experiments/contract_nli/tests/test_run_contract_nli_20.py ../experiments/contract_nli/tests/test_run_contract_nli_hard5_ocr.py ../experiments/contract_nli/tests/test_run_contract_nli_hard11.py ../experiments/contract_nli/tests/test_run_contract_nli_pdf38_ocr.py -q`，结果 `61 passed`。
- `CONTRACT_NLI_RERUN=1 CONTRACT_NLI_RUN_TARGET=agent_only conda run -n agent-gate python experiments/contract_nli/scripts/run_contract_nli_hard5_ocr.py`，结果 `5/5 completed`，choice accuracy `0.7412`，evidence F1 `0.5746`。

### 遇到的问题

- enum schema 将字段数从 34 降到 17，但本轮 hard5 trace 仍主要表现为先读取较多内容再按 schema 顺序写字段。

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

### 验证

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
- 候选写入工具收到未知 ref 时不再直接终止整单，runner 记录 `tool_error` 并把错误作为下一轮工具结果返回给模型修正。

### 验证

- `conda run -n agent-gate python -m pytest backend/tests/test_task_flow.py -q`，结果 `10 passed`。
- `pnpm test -- task-detail.test.tsx --runInBand`，结果 `7 passed`。
- 真实前端全流程任务 `task_ff50dfeab89a4923bdc4cbbd257c0a25` 完成 `completed / done / accept`，抽取 `academic_paper_count=9` 和 9 个 `academic_paper_names`。

### 遇到的问题

- 真实 E2E 中模型曾把不存在的表格行 ref 传给候选写入工具，旧逻辑会把整个 extraction 标记为 failed。

### 下一步

- 后续可继续优化 Paddle 表格行切分和 query 召回口径，减少模型从大表格中选择错误 ref 的概率。

## 2026-04-30 02:11:37

### 已完成工作

- 更新 `agent/docs/DESIGN.md`，记录 `file_extraction_agent` 下一版受约束 agentic workflow 设计：`Broad Agent Loop` 通过 `search_text`、`search_table_rows`、`add_candidate`、`finish_broad` 做候选证据召回。
- 明确 `resolution agent` 可以读取 broad 候选，并在候选不足时继续用文本/表格检索工具补查，最终定案必须引用候选或 block/row id。
- 明确表格检索是通用结构化检索能力，不硬编码具体业务词；当前内容类型先收敛为 heading/text/table，不处理 image。

### 验证

- 本次只更新设计文档，不涉及运行时代码或测试文件。

## 2026-04-29 20:32:22

### 已完成工作


### 验证

- 本次只更新文档，不涉及运行时代码或测试文件。

## 2026-04-28 14:19:45

### 已完成工作

- 按 review 修正 `file_extraction_agent` 抽取端结构化输出策略：`auto` 只在 `json_schema` 明确不支持时切到 `tool_call`，已经进入 invoke 阶段的超时、鉴权、服务端错误或输出校验失败不再换协议重试。
- 收紧 resolution 证据绑定：模型返回 `status=resolved` 时必须声明非空 `used_block_ids`，避免最终 trace 沿用未被模型声明使用的 broad evidence。
- 清理 document processor route 边界：HTTP 层改为从公开 `service.document_processor.processor` 导入 `InvalidFileObjectError`，不再依赖 `impl.base`。
- 同步更新相关设计/API 和测试说明文档。

### 当前进展

- 在 `agent-gate` 环境中验证完整测试：`126 passed, 2 warnings`。

### 遇到的问题

- 抽取端之前把结构化 runnable 构造失败和 invoke 失败放在同一个 broad except 中，会把业务调用失败误判成协议不支持并重复请求模型。

### 下一步

- 后续如果继续调整结构化输出兼容策略，需要分别说明“协议选择失败”和“模型调用失败”的处理语义。

## 2026-04-28 13:32:31

### 已完成工作

- 修复 `/v1/ocr/capabilities` 依赖不存在 `docling_adapter` 的问题，改为从现有 PDF processor 读取 docling 模型目录。
- 将 `file_extraction_agent` 的 `RunOptions` 收敛为 `schemas.py` 中的公开全局契约，供 HTTP 入口、Python 入口和内部 graph 共用。
- 同步更新相关设计/API/README 和测试说明文档，补齐 capabilities、run options 边界和结构化调用失败语义。

### 当前进展

- agent service 的 HTTP 能力查询、字段抽取公开参数边界和模型结构化调用行为已与当前设计一致。
- 在 `agent-gate` 环境中验证完整测试：`122 passed, 2 warnings`。

### 遇到的问题

- review 发现 capabilities 路由、HTTP `run_options` 暴露内部对象、模型客户端裸 JSON 回退三处与设计或文档不一致。
- 完整测试仍有 docling / RapidOCR 依赖自身的 deprecation warning，本次未改动第三方依赖行为。

### 下一步

- 后续如果继续调整运行参数，优先扩展公开 `RunOptions`，避免外部和内部维护两份同构配置。

## 2026-04-28 12:51:12

### 已完成工作

- 记录 backend 在两段接口之间需要完成的组装职责：为 blocks 补齐 `document_id/block_id`，并从抽取 trace 组装 `refs_with_text`。
- 使用真实 PDF `18【本科生】2025-2026学年第一学期 文明模范寝室.pdf` 走 HTTP 全流程并验证三段接口均返回 200。

### 当前进展

- 真实 HTTP 全流程结果可用：模范寝室为 `106、218、413、521、603`，文明寝室为 `212、214、302、324、401、518、519、523、614、618、620、621`，楼宇平均分为 `85.1`。

### 遇到的问题

- RapidOCR 日志提示 `ppocr_keys_v1.txt` 不存在，但本次 OCR 和接口返回未受阻断。
- 模型结构化输出阶段出现 Pydantic serializer warning，但 HTTP 链路和业务结果正常返回。

### 下一步


## 2026-04-28 10:56:45

### 已完成工作

- 明确 `file_extraction_agent` 只产出 `ExtractionResult(result + trace)`，不内置 `accept / review / reject` 判断。

### 当前进展


### 下一步

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
