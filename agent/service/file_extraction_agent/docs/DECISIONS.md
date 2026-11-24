# file_extraction_agent 关键决策

归属 [文档问答执行设计](DESIGN.md)，记录问答内核、模型装配、提示词边界与工具子进程模块的长期取舍。

## 1. 无状态单轮执行，与 `document_service` 仅通过 `storage` 交接

- 决定：问答服务不导入 `document_resources`，只消费 `storage` 中已发布的 `documents.zip` 与 `index/`；不同 RPC 之间不共享可变状态，采用单轮 `ChatCompletion` 风格接口，多轮真值完全归属 `backend` SQLite，LangGraph 仅用于单轮图执行而不挂载持久化 checkpointer。
- 原因：支持 `agent` 与 `document_service` 独立部署及问答节点无状态水平扩展，避免两端重复持久化会话状态。
- 排除：在 agent 进程内维护会话与活动 completion 注册表；引入 LangGraph `checkpointer` 或服务端有状态会话协议；在问答侧重新解析文档与重建向量。

## 2. 统一标准 `ChatOpenAI`，显式配置与有限超时，移除厂商特化分支

- 决定：模型装配统一使用标准 `ChatOpenAI`，生产固定 `streaming=True`（不自动降级），SDK 内层 `max_retries=0`（重试统一由图内 5 次退避控制）；环境变量显式使用 `MODEL`、`OPENAI_API_KEY`、`BASE_URL`、`MODEL_API_TRANSPORT`（仅允许 `responses` 默认或 `chat_completions`，拒绝 `auto`）与 `MODEL_REQUEST_TIMEOUT`（默认 `8.0` 秒，不允许无限等待），优先级 `agent/.env` < 当前目录 `.env` < 进程 `os.environ`；已移除 DeepSeek 专用 `reasoning_content` / `thinking` 适配与多模型候选列表。
- 原因：防止内外层重试相乘、跨协议静默切换与上游卡死长期挂起协程，降低厂商特化分支维护成本。
- 排除：回退读取通用 `API_KEY` 或为 `MODEL` 设硬编码默认值；支持 `MODEL_API_TRANSPORT=auto`；允许无限请求超时；保留多模型自动回退候选列表或厂商定制补丁。

## 3. 每次工具调用走一次性子进程，检索端采用纯 OpenVINO 查询编码

- 决定：所有工具通过 `worker_client.run_operation` 启动一次性子进程执行；`search_embedding` 仅依赖 `openvino` + `tokenizers`（不导入 `torch`/`transformers`，冷启约 2.3s，对比 `sentence-transformers` 约 21s），取消或超时在 `finally` 直接 kill 子进程。
- 原因：以单次子进程开销换取可靠的强杀取消语义、隔离父进程内存与简化并发控制。
- 排除：在父进程加载查询模型，或首版引入复杂的常驻 worker 进程池。

## 4. 工具全异步化与原生取消传播

- 决定：工具仅保留异步 `ainvoke` 接口，取消沿 `asyncio.Task` 与 `aclosing` 自动关闭内层图与模型流；事件包装不维护 pending 配对字典。
- 原因：避免同步阻塞事件循环和手动传递停止标志漏清理子进程。
- 排除：保留 `SyncTool` 同步接口和 `should_stop`/`StopCheck` 回调轮询。

## 5. 只读文档树与 Append-Only 完整工具历史，不引入摘要树与 `memory` 机制

- 决定：坚持将文档投影为只读 Markdown 文档树并由工具查阅原文附真实路径引用；每轮由调用方按原序 append-only 全量回传历史消息（包含带 `tool_calls` 的过程 `assistant` 消息与对应 `role=tool` 结果），全链路彻底移除 `memory` 摘要机制，不做滑动窗口裁剪或前缀改写。
- 原因：RAPTOR 式 LLM 摘要树聚类不稳定且弱化可审计原文定位；仅回传纯文本会丢失查证轨迹引发重读，而动态重写 `memory` 或裁剪历史会破坏 Prompt Prefix Cache 推高输入成本。
- 排除：采用 RAPTOR 式 LLM 摘要聚类树；将工具历史压成纯文本 transcript；保留 `memory` 动态拼接字段或默认滑动窗口裁剪历史。

## 6. 不提供结束工具，以归一化终态信号与非空正文判定完成并透传 `is_final`

- 决定：不向模型提供 `submit_answer`/`finish_turn` 类结束工具，最终回答必须是普通文本消息；当无 `tool_calls` 时由 `core/messages.py` 归一化读取 provider 的 `finish_reason`/`stop_reason`/`status`，仅在命中合法终态信号且 `visible_text` 非空时自然完成并在 `model_message.done` 上标注 `is_final=true` 与 `stop_signal`；非终态（如 `length`/`incomplete`）、缺失终态或空正文抛错进入图内 5 次重试。
- 原因：防止过渡叙述、长度截断或空白回复被误存为最终回答，同时让 backend 解耦各厂商原始 `finish_reason` 语义。
- 排除：提供 `submit_answer`/`finish_turn` 结束工具；仅按 `tool_calls` 为空判定完成；让 backend 自行解析各厂商原始 `finish_reason`。

## 7. 废除计划工具与工具 `reason` 参数，过程叙述收口至非强制 `assistant content`

- 决定：不提供模型自编计划、阶段状态机或备忘录工具（如 `soft_plan`/`update_plan`/`start_stage`/`record_note`），所有工具及工具事件均不设 `reason` 字段；允许带 `tool_calls` 的消息输出空 `content`，系统提示词引导模型首次查文档前简述意图、后续合并多次探索为 1 至 3 句带可读行内链接的叙述，最终回答使用紧贴句末的纯数字链接（如 `[1]` 指向 `documents/...` 相对路径）并禁止尾随 `Sources` 节。
- 原因：模型自编计划易与真实调用脱节产生过程幻觉；工具 `reason` 与正文重复展示；逐次工具调用强制套模板汇报会造成阅读疲劳。
- 排除：引入计划/备忘类工具；在工具入参或事件中保留 `reason`；强制每轮工具调用输出非空 `content` 或在终稿末尾集中列 Sources。

## 8. 单层 `ls` 不预注入目录树、单块 `read`、开放并行工具与 Prompt/Docstring 分层

- 决定：`ls(path="")` 只列当前直接子项且初始消息不预注入整棵目录树；`read(path)` 单次只读一个 `.md` 块文件；开放同轮并行工具调用（不设 `parallel_tool_calls=False`），由 `executor` 并发执行并按原序回写历史；System Prompt 开头界定默认直答与查文档边界（不追加末尾合成调查 `HumanMessage`，不设独立 query router），各工具参数与返回细则下沉至各自 `@tool` docstring，不堆砌大段正反例 few-shot 或硬性读取次数预算。
- 原因：避免递归树注入和冗长提示词稀释核心规则、防止末尾合成指令诱发闲聊误查文档，并行工具调用减少多文档往返轮次。
- 排除：暴露递归 `tree` 工具或初始预注入目录树；给 `read` 加分页/范围参数；禁用并行工具调用；在历史末尾追加合成调查指令或引入独立意图分类器；把工具手册堆进 System Prompt。
