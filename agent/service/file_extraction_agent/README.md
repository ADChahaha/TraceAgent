# file_extraction_agent

`file_extraction_agent` 当前是多文档 QA chat completion agent。它接收 backend 每轮传入的 `completion_id + documents(filename + html) + append-only messages`，把多份语义 HTML 落盘成真实文件树，让模型用 `ls / grep / read` 像 code agent 看项目一样浏览材料，并通过 SSE 持续输出带 evidence link 的过程消息。

包名仍沿用历史 `file_extraction_agent`，但本分支不再做 `task_spec` 字段抽取。

## 补充文档

本 README 记录当前模块职责和主要入口；更轻量的流程草稿见：

- [docs/flowchart.md](docs/flowchart.md)：用流程图描述 chat completions、cancel 和 agent loop 线程/队列关系。
- [docs/agent_loop.md](docs/agent_loop.md)：用伪代码描述 Iterable consumer 和 agent loop 的协作式 `cancel_flag` 检查模型。
- [docs/tools.md](docs/tools.md)：记录 `ls / grep / read` 三个模型工具表面。

## 工作链路

```text
completion_id + documents + messages + run_options
  -> completion_manager.create / manager.prepare_completion_state 校验 completion_id 非空
  -> manager.prepare_completion_state 校验 documents 非空、每个 document 有 filename/html
  -> manager.prepare_completion_state 校验 messages 非空、每条 message.content 非空
  -> manager.prepare_completion_state 归一化 run_options(max_tool_calls 不再作为硬限)
  -> documents.materialize_tree 解析 HTML，落盘真实文件树（DocumentFileTree）
  -> ActiveCompletion(completion_id, state, model) 注册进 CompletionManager
  -> graph 输出 completion.created 和 source_indexed(workspace_root + tree)
  -> loop 构建 QA prompt，并挂载 ls/grep/read
  -> 模型输出 model_message；如需继续阅读，就单轮调用一个工具
  -> tools 把工具调用写成 tool_started/tool_completed/tool_failed 事件
  -> model_message 在阅读过程中用 Markdown evidence link 说明事实和答案
  -> graph 输出 completion.completed 或 completion.failed
  -> manager 若检测到 cancel_requested，则输出 completion.cancelled
```

输出是 `text/event-stream` 字符串迭代器；backend 负责消费、入库和转发给前端。

## 真实文件树

多文档语料不会被做成虚拟树，而是落盘成真实文件树（`core/documents.py` 的 `materialize_tree`）。模型像 code agent 看项目一样，用真实 `.md` 路径浏览。

```text
/workspace/<completion_id>/
    └── 0001-contract-Agreement/
        └── 0001-Agreement/
            ├── 0001-Termination/
            │   ├── 0001-Either party may terminate.md
            │   └── 0002-Notice period.md
            └── 0002-Notices/
                └── 0001-Written notice must be sent.md
```

建树规则：

- 每个输入 HTML 是 workspace 根下的文档目录，编号按文档顺序递增。
- `h1` 到 `h6` 按层级生成 section 目录（`h1` 也会进入树，不因参与文档命名而被跳过）。
- paragraph / list / table 各写成一个 `.md` 文件（列表、表格整表一个文件）。
- 目录/文件排序靠数字前缀（`0001-` / `0002-`），不靠 `os.listdir`。
- 没有 `path_id` / `evidence://`；模型看到和引用的都是真实 `.md` 路径。
- `source_indexed` 事件暴露 `workspace_root` 和逐层 `tree` 清单。

## 工具

只暴露三个模型工具（`core/tools.py`）：

| Tool | 作用 |
| --- | --- |
| `ls(path="")` | 列出 root、文档目录或 section 的当前层，返回真实路径。 |
| `grep(query, scope="", max_results=20)` | 在 scope 目录（默认整个 workspace 根）跑 ripgrep，返回原样 stdout；只定位候选，不产生最终证据。 |
| `read(path)` | 读取一个 `.md` block 文件的 markdown 内容。 |

工具职责顺序通常是：

```text
用户问题
  -> ls 分层理解文档结构
  -> grep 定位候选 block
  -> read 打开上下文
  -> model_message 用真实 .md 路径回答或说明下一步
```

`grep` 只负责定位候选，不产生最终证据；`read` 负责理解上下文；模型最终引用真实文件路径。

## 证据规则

```text
检索策略、下一步行动说明
  -> 不需要 evidence

文档结构、section 主题、读了哪些 block
  -> 可以引用 section 或 block 文件路径

过程中首次陈述的文档事实（日期、金额、义务、条件等）
  -> 用 Markdown link 引用真实 .md 路径

最终回答正文里的文档事实
  -> 把 [1](/abs/path/xxx.md) 这类数字 citation 紧跟在被支撑句子后面，不汇总成总 Sources 区
```

## 公共入口

completion 生命周期由 `CompletionManager` 统一管理。公开入口是**进程内单例
`completion_manager`**：`create(...)` 校验强类型入参、落盘文件树、构造
`ActiveCompletion` 并注册，返回 SSE 迭代器；`terminate(completion_id)` 取消；
`get_status(completion_id)` 查询。HTTP 路由直接调用该单例。

```python
from service.file_extraction_agent.manager import completion_manager

stream = completion_manager.create(
    completion_id="cmp_001",
    documents=[
        {
            "filename": "company.html",
            "html": "<h1>公司资料</h1><h2>概况</h2><p>公司成立于2020年。</p>",
        }
    ],
    messages=[{"role": "user", "content": "公司什么时候成立？"}],
    model_config={
        "base_url": "https://example.com/v1",
        "api_key": "...",
        "model": "...",
        "api_transport": "responses",
    },
    run_options={"max_tool_calls": 40},
)

for event in stream:
    print(event)
```

HTTP 入口是 `POST /v1/document-qa/chat/completions`，返回 `text/event-stream`。

取消入口：

```python
from service.file_extraction_agent.manager import completion_manager

completion_manager.terminate("cmp_001")
# {"id": "cmp_001", "status": "cancelling"} 或 {"id": "cmp_001", "status": "not_found"}

completion_manager.get_status("cmp_001")
# {"id": "...", "status": "..."} 或 None
```

取消是本地 completion 级取消：SSE consumer 在 runtime 取消状态触发后立即输出
`completion.cancelled` 并关闭响应，不等待 provider 下一个 chunk。它不会强杀正在
进行中的同步 provider 请求；残留 producer 依赖有限 request timeout 回收，迟到
事件会被丢弃。第一版只支持单进程内存 runtime，不支持多 uvicorn worker 共享取消
状态。

## 已删除旧语义

本分支不再保留旧字段抽取兼容层：

- 不再接收 `task_spec`。
- 不再提供 `extract_stream(...)`。
- 不再暴露 `POST /v1/file-extraction-agent/extract/stream`。
- 不再输出 `result_completed(fields + trace)`。
- 不再暴露 `add_candidate_evidence / review_evidences / write_field / submit_result`。

更完整的实现边界和设计说明见 [docs/DESIGN.md](docs/DESIGN.md)。
