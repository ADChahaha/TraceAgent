# file_extraction_agent

`file_extraction_agent` 是只读语义 HTML 字段抽取器。它接收多个 `documents(filename + html)` 和用户给定 `task_spec`，把材料虚拟成文件树，再让模型通过工具事件完成阅读、证据绑定和字段提交。

## 工作链路

```text
documents + task_spec + run_options
  -> input_adapter 校验 documents 非空、每个 document 有 filename/html、task_spec.fields 非空
  -> html_index 解析 HTML，生成 /001-filename-title/... 内部虚拟树、path -> node 索引和模型可见 path_id
  -> paragraph/list/table 分别建成 .md/.list/.table 文件，section header 建成目录
  -> resolution_new 生成抽取提示并挂载 tree/read/bind_evidence/review_evidences/write_field/submit_result
  -> 模型按 schema 浏览材料；机械导航和连续相邻 read 可以不说话，完成语义块或小阶段时才在 assistant content 里给人类 reviewer 简短说明
  -> read 一次只打开一个 paragraph/list/table；需要继续看相邻内容时必须再次调用 read
  -> bind_evidence 用单个显式 evidence:// block link 把一个字段的一个可能相关对象保存为候选 block
  -> review_evidences 把字段候选 block 展开成 Sxxx/Ixxx/Rxxx inline selector 和 evidence_texts
  -> 模型判断 review 结果足够支撑字段决定后，write_field 基于同字段当前 review snapshot 覆盖写入字段值、状态和 final_evidence
  -> submit_result 校验必填字段、类型和最终 evidence selector
  -> graph 按顺序输出 NDJSON 工具事件，最后输出 result_completed
```

虚拟树不会落盘。raw virtual path 只作为内部索引和调试信息使用；模型看到和提交的 locator 是 `evidence://0000.0001` 这种 evidence link。旧方括号格式不是别名，工具参数会直接拒绝。内部仍通过 `HtmlDocument.nodes_by_path` / `nodes_by_path_id` 找回 paragraph 文本、list item 和 table row。

## 虚拟文件树

建树规则：

- 根目录固定为 `/`。
- 每个输入文件是根目录下的文档目录，目录名形如 `001-source-title`。
- section header 是目录。
- paragraph 是 `.md` 文件，文件名使用同级编号加段落前 `n` 个清洗后的可见字符，例如 `001-公司成立于2020年.md`。
- list 是 `.list` 文件，内部 item 编号为 `I001`、`I001.001`。
- table 是 `.table` 文件，内部 row 编号为 `R001`。
- 同级节点都先按原文顺序编号，用编号保持排序并消除同名冲突。

paragraph 文件名只是预览，不代表截断正文。完整正文由 `read(path_id)` 返回；句子编号会在字段候选证据进入 `review_evidences(field_id)` 后展开。

## 工具

| Tool | 作用 |
| --- | --- |
| `tree(path_id, depth)` | 展开虚拟目录，只返回子节点的 `path_id`、目录名和文件名。 |
| `read(path_id)` | 读取一个 `.md/.list/.table` 文件。 |
| `bind_evidence(field_id, path_id)` | 把一个显式 `evidence://` block link 指向的可读对象绑定到一个字段的候选 block evidence。 |
| `review_evidences(field_id)` | 只读复看字段描述、当前值、候选 block evidence，并展开成可用于最终提交的 inline selector。 |
| `write_field(field_id, value, final_evidence, status)` | 基于同字段当前 `review_evidences` snapshot，写入或覆盖一个 schema 字段的最终值和最终证据。 |
| `submit_result()` | 校验当前字段缓冲区，成功返回最终 `fields[]`，失败返回结构化错误。 |

工具参数不再包含 `reason`。assistant content 是可选的用户可见阶段性说明：机械 `tree`、连续相邻 `read`、常规候选绑定或普通 review 检查可以留空；读完一个语义块、收集完一组候选证据、从阅读切到 review/write、写字段结论，或修正失败工具时再输出一句短说明。它会被 trace 记录为用户可见说明，并兼容填入工具 action/event 的 `reason` 字段；没有 content 时 `reason` 为空字符串。如果 content 使用了文档原文或原文语义，就必须写成 Markdown evidence link，并解释为什么这段文字支持当前动作。可以引用 inline selector，例如 `["only in connection"](evidence://0000.0001.0014/S002)`；必要时也可以引用整个 paragraph/list/table block，例如 `["strictest of confidence"](evidence://0000.0001.0012)`。`write_field` 的可见引用也可以链到 inline selector 或它所在的 paragraph/list/table block；工具参数和 `final_evidence` 都使用 `evidence://` 链接。

resolution 关闭并发工具调用：prompt 要求每轮只调用一个工具，`bind_tools` 会请求 provider 侧 `parallel_tool_calls=False`，运行时如果仍收到多个 tool call，只保留并执行第一个。这样模型必须等待每次 `read/review/write` 的结果再继续下一步，避免批量读取或批量写入破坏证据反馈链。

## 读取与证据

`read` 一次只返回一个 paragraph/list/table block。模型需要继续看相邻内容时，必须根据 tree 里的下一个 evidence link 再调用一次 `read`，让 trace 保持逐块阅读。

paragraph：

```text
tree("evidence://0000", depth=2)
  -> 显示 evidence://0000.0001.0001.0001 公司成立于2020年.md
read("evidence://0000.0001.0001.0001")
  -> 返回完整 paragraph 正文，不带句子号
bind_evidence(field_id="founded_year", path_id="evidence://0000.0001.0001.0001")
  -> 保存候选 block evidence: {"path_id": "0000.0001.0001.0001"}
review_evidences(field_id="founded_year")
  -> 展开 inline evidence: {"path_id": "0000.0001.0001.0001", "sentences": ["S001", ...]}
```

list：

```text
read("evidence://0000.0001.0002.0001")
  -> frontmatter metadata + Markdown list
  -> - [I001] ...
bind_evidence(field_id="service_items", path_id="evidence://0000.0001.0002.0001")
  -> 保存候选 block evidence: {"path_id": "0000.0001.0002.0001"}
review_evidences(field_id="service_items")
  -> 展开 inline evidence: {"path_id": "0000.0001.0002.0001", "items": ["I001", ...]}
```

table：

```text
read("evidence://0000.0001.0003.0001")
  -> frontmatter metadata + Markdown table
  -> | R001 | ... |
bind_evidence(field_id="fees", path_id="evidence://0000.0001.0003.0001")
  -> 保存候选 block evidence: {"path_id": "0000.0001.0003.0001"}
review_evidences(field_id="fees")
  -> 展开 inline evidence: {"path_id": "0000.0001.0003.0001", "rows": ["R001", ...]}
```

`write_field(final_evidence=...)` 必须复制同字段当前 `review_evidences.evidence` 里的 inline selector；模型应在 review 后判断证据足够支撑字段决定，或者足够判断 missing/null，才写字段。如果 review 后又给该字段 `bind_evidence` 新候选，当前 review snapshot 会失效，需要重新 review 再写。prompt 会建议模型 review 后尽快 write，不要隔很远才使用旧 review。这个规则也适用于 `status="missing"` 和 null enum variant，不过它们可以在有同字段 review snapshot 后使用空 `final_evidence`。最终证据不能使用只有 `path_id` 的 block selector，也不能手写 raw virtual path。`submit_result` 会校验 selector 类型和编号是否存在：`.md` 只能用 `sentences`，`.list` 只能用 `items`，`.table` 只能用 `rows`。

## 公共入口

Python 入口返回 NDJSON 字符串迭代器：

```python
from service.file_extraction_agent.processor import extract_stream

stream = extract_stream(
    documents=[
        {
            "filename": "company.html",
            "html": "<h1>公司资料</h1><h2>概况</h2><p>公司成立于2020年。</p>",
        }
    ],
    task_spec={
        "fields": [
            {"name": "founded_year", "type": "number", "required": True}
        ]
    },
    model_config={
        "base_url": "https://example.com/v1",
        "api_key": "...",
        "resolution_model_name": "...",
    },
    run_options={"max_tool_calls": 40},
)

for line in stream:
    ...
```

HTTP 入口是 `POST /v1/file-extraction-agent/extract/stream`，返回 `application/x-ndjson`。更完整的实现边界和设计说明见 [docs/DESIGN.md](docs/DESIGN.md)。
