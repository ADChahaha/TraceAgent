# file_extraction_agent

`file_extraction_agent` 是只读语义 HTML 字段抽取器。它接收多个 `documents(filename + html)` 和用户给定 `task_spec`，把材料虚拟成文件树，再让模型通过工具事件完成阅读、证据绑定和字段提交。

## 工作链路

```text
documents + task_spec + run_options
  -> input_adapter 校验 documents 非空、每个 document 有 filename/html、task_spec.fields 非空
  -> html_index 解析 HTML，生成 /001-filename-title/... 内部虚拟树、path -> node 索引和模型可见 path_id
  -> paragraph/list/table 分别建成 .md/.list/.table 文件，section header 建成目录
  -> resolution_new 生成抽取提示并挂载 tree/read/bind_evidence/skip_read/review_evidences/write_field/submit_result
  -> 模型按 schema 浏览材料、读取一个 paragraph/list/table，并用 reason 说明每次用户可见动作
  -> 每次 read 成功后必须立刻 bind_evidence 绑定当前对象为候选 block，或 skip_read 标记无关
  -> review_evidences 把字段候选 block 展开成 Sxxx/Ixxx/Rxxx inline selector 和 evidence_texts
  -> 紧跟 write_field 覆盖写入字段值、状态和从刚刚 review 复制的 final_evidence
  -> submit_result 校验必填字段、类型和最终 evidence selector
  -> graph 按顺序输出 NDJSON 工具事件，最后输出 result_completed
```

虚拟树不会落盘。raw virtual path 只作为内部索引和调试信息使用；模型看到和提交的 locator 是 `[0000.0001]` 这种 `path_id`。内部仍通过 `HtmlDocument.nodes_by_path` / `nodes_by_path_id` 找回 paragraph 文本、list item 和 table row。

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
paragraph 文件名只是预览，不代表截断正文。完整正文由 `read(path_id)` 返回；句子编号会在字段候选证据进入 `review_evidences(field_id)` 后展开。

## 工具

| Tool | 作用 |
| --- | --- |
| `tree(path_id, depth, reason)` | 展开虚拟目录，只返回子节点的 `path_id`、目录名和文件名。 |
| `read(path_id, offset, limit, reason)` | 读取 `.md/.list/.table` 文件；成功后必须先判断绑定或跳过。 |
| `bind_evidence(field_id, bindings, reason)` | 把当前 pending read 对象绑定到一个或多个字段的候选 block evidence，不接受模型手写 `path_id` 或 inline selector。 |
| `skip_read(reason)` | 把当前 pending read 对象标记为无关，关闭 read judgement。 |
| `review_evidences(field_id, reason)` | 只读复看字段描述、当前值、候选 block evidence，并展开成可用于最终提交的 inline selector。 |
| `write_field(field_id, value, final_evidence, status, reason)` | 紧跟同字段 `review_evidences` 后，写入或覆盖一个 schema 字段的最终值和最终证据。 |
| `submit_result(reason)` | 校验当前字段缓冲区，成功返回最终 `fields[]`，失败返回结构化错误。 |

`reason` 是用户可见动作说明，不是证据，也不是模型推理链。工具 wrapper 会为每次调用写入 `tool_started`、`tool_completed` 或 `tool_failed`，证据绑定另有 `evidence_bound`，字段写入另有 `field_written`，最终提交另有 `result_completed`。

## 读取与证据

paragraph：

```text
tree("[0000]", depth=2)
  -> 显示 [0000.0001.0001.0001] 001-公司成立于2020年.md
read("[0000.0001.0001.0001]")
  -> 返回完整 paragraph 正文，不带句子号
bind_evidence(field_id="founded_year")
  -> 保存候选 block evidence: {"path_id": "[0000.0001.0001.0001]"}
review_evidences(field_id="founded_year")
  -> 展开 inline evidence: {"path_id": "[0000.0001.0001.0001]", "sentences": ["S001", ...]}
```

list：

```text
read("[0000.0001.0002.0001]")
  -> frontmatter metadata + Markdown list
  -> - [I001] ...
bind_evidence(field_id="service_items")
  -> 保存候选 block evidence: {"path_id": "[0000.0001.0002.0001]"}
review_evidences(field_id="service_items")
  -> 展开 inline evidence: {"path_id": "[0000.0001.0002.0001]", "items": ["I001", ...]}
```

table：

```text
read("[0000.0001.0003.0001]", offset=0, limit=30)
  -> frontmatter metadata + Markdown table
  -> | R001 | ... |
bind_evidence(field_id="fees")
  -> 保存候选 block evidence: {"path_id": "[0000.0001.0003.0001]"}
review_evidences(field_id="fees")
  -> 展开 inline evidence: {"path_id": "[0000.0001.0003.0001]", "rows": ["R001", ...]}
```

`write_field(final_evidence=...)` 必须紧跟同字段 `review_evidences`，并复制这次 `review_evidences.evidence` 里的 inline selector；如果中间插入任何其他工具调用，需要重新 review 再写。这个规则也适用于 `status="missing"` 和 null enum variant。最终证据不能使用只有 `path_id` 的 block selector，也不能手写 raw virtual path。`submit_result` 会校验 selector 类型和编号是否存在：`.md` 只能用 `sentences`，`.list` 只能用 `items`，`.table` 只能用 `rows`。

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
