# file_extraction_agent

`file_extraction_agent` 当前是多文档 QA chat completion agent。它接收 backend 每轮传入的 `completion_id + documents(filename + html) + messages + memory`，把多份语义 HTML 虚拟成只读文档仓库，再让模型用 `tree / grep / read / inspect` 像 code agent 看项目一样浏览材料，并通过 SSE 持续输出带 evidence link 的过程消息。

包名仍沿用历史 `file_extraction_agent`，但本分支不再做 `task_spec` 字段抽取。

## 工作链路

```text
completion_id + documents + messages + memory + run_options
  -> input_adapter 校验 completion_id 非空
  -> input_adapter 校验 documents 非空、每个 document 有 filename/html
  -> input_adapter 校验 messages 非空、每条 message.content 非空
  -> input_adapter 归一化 memory 和 run_options(max_tool_calls > 0)
  -> html_index 解析 HTML，生成 HtmlDocument、path_id 索引和 source_selectors
  -> processor 创建 ActiveCompletion，写入 _ACTIVE_COMPLETIONS
  -> graph 输出 completion.created 和 source_indexed
  -> resolution_new 构建 QA prompt，并挂载 tree/grep/read/inspect
  -> 模型输出 model_message；如需继续阅读，就单轮调用一个工具
  -> html_tools 把工具调用写成 tool_started/tool_completed/tool_failed 事件
  -> inspect 把关键 block 展开成 Sxxx/Ixxx/Rxxx inline evidence
  -> model_message 在阅读过程中用 Markdown evidence link 说明事实和答案
  -> graph 输出 completion.completed 或 completion.failed
  -> processor 若检测到 cancel_requested，则输出 completion.cancelled
  -> processor 清理 _ACTIVE_COMPLETIONS[completion_id]
```

输出是 `text/event-stream` 字符串迭代器；backend 负责消费、入库和转发给前端。

## 虚拟文件树

虚拟树不会落盘。raw virtual path 只作为内部索引和调试信息使用；模型看到和提交的 locator 是 `evidence://0001.0000.0001` 这种 evidence link。根目录只在 `tree(path_id="", depth=...)` 或 `tree(path_id="/", depth=...)` 里表示。

建树规则：

- 根目录固定为 `/`。
- 每个输入文件是根目录下的文档目录，locator 如 `evidence://0001`。
- section header 是目录。
- paragraph 是 `.md` 文件。
- list 是 `.list` 文件，最终 inline item selector 为 `I001`。
- table 是 `.table` 文件，最终 inline row selector 为 `R001`。
- 同级节点按原文顺序编号，编号保证排序和消除同名冲突。

paragraph/list/table 文件名只是预览，不代表截断正文。完整正文由 `read(locator)` 返回；句子、列表项和表格行编号由 `inspect(locator)` 展开。

## 工具

| Tool | 作用 |
| --- | --- |
| `tree(path_id, depth)` | 展开 root、文档目录或 section，返回模型可复制的 `evidence://` locator。 |
| `grep(query, scope, kind, max_results)` | 在可读 block 中做候选搜索，返回 locator、document、section、preview 和 match_spans。 |
| `read(locator)` | 读取一个 paragraph/list/table block，或读取同一 section 下相邻 block range。 |
| `inspect(locator)` | 把一个可读 block 展开成 paragraph sentence、list item 或 table row 的 inline evidence link。 |

工具职责顺序通常是：

```text
用户问题
  -> tree 理解文档结构
  -> grep 定位候选 block
  -> read 打开上下文
  -> inspect 展开精确 evidence
  -> model_message 用 evidence link 回答或说明下一步
```

`grep` 只负责定位候选，不产生最终证据。`read` 负责理解上下文。`inspect` 负责把 block 升级成可以支撑具体事实的 `Sxxx/Ixxx/Rxxx` evidence。

## 读取与证据

paragraph：

```text
tree(path_id="", depth=2)
  -> 显示 evidence://0001.0001.0001 公司成立于2020年.md
read(locator="evidence://0001.0001.0001")
  -> 返回完整 paragraph 正文
inspect(locator="evidence://0001.0001.0001")
  -> 返回 evidence://0001.0001.0001/S001 等句子级链接
model_message
  -> “公司成立于 2020 年。[成立时间](evidence://0001.0001.0001/S001)”
```

list：

```text
read(locator="evidence://0001.0002.0001")
  -> 返回 Markdown list
inspect(locator="evidence://0001.0002.0001")
  -> 返回 evidence://0001.0002.0001/I001 等列表项链接
```

table：

```text
read(locator="evidence://0001.0003.0001")
  -> 返回 Markdown table
inspect(locator="evidence://0001.0003.0001")
  -> 返回 evidence://0001.0003.0001/R001 等表格行链接
```

证据规则：

```text
检索策略、下一步行动说明
  -> 不需要 evidence

文档结构、section 主题、读了哪些 block
  -> 可以引用 section 或 block evidence

日期、金额、义务、条件、例外、冲突、最终结论
  -> 应引用 inspect 后的 inline evidence
```

## 公共入口

Python 入口返回 SSE 字符串迭代器：

```python
from service.file_extraction_agent.processor import create_completion_stream

stream = create_completion_stream(
    completion_id="cmp_001",
    documents=[
        {
            "filename": "company.html",
            "html": "<h1>公司资料</h1><h2>概况</h2><p>公司成立于2020年。</p>",
        }
    ],
    messages=[{"role": "user", "content": "公司什么时候成立？"}],
    memory={"reading_history": [], "evidence_notes": [], "prior_answers": [], "open_threads": []},
    model_config={
        "base_url": "https://example.com/v1",
        "api_key": "...",
        "resolution_model_name": "...",
    },
    run_options={"max_tool_calls": 40},
)

for event in stream:
    print(event)
```

HTTP 入口是 `POST /v1/document-qa/chat/completions`，返回 `text/event-stream`。

取消入口：

```python
from service.file_extraction_agent.processor import cancel_completion

cancel_completion("cmp_001")
# {"id": "cmp_001", "status": "cancelling"} 或 {"id": "cmp_001", "status": "not_found"}
```

取消是本地 completion 级取消：`processor` 的 SSE consumer 看到 `cancel_requested` 后立即输出 `completion.cancelled` 并关闭响应，不等待 provider 下一个 chunk。它不会强杀正在进行中的同步 provider 请求；残留 producer 依赖有限 request timeout 回收，迟到事件会被丢弃。第一版只支持单进程内存 runtime，不支持多 uvicorn worker 共享取消状态。

## 已删除旧语义

本分支不再保留旧字段抽取兼容层：

- 不再接收 `task_spec`。
- 不再提供 `extract_stream(...)`。
- 不再暴露 `POST /v1/file-extraction-agent/extract/stream`。
- 不再输出 `result_completed(fields + trace)`。
- 不再暴露 `add_candidate_evidence / review_evidences / write_field / submit_result`。

更完整的实现边界和设计说明见 [docs/DESIGN.md](docs/DESIGN.md)。
