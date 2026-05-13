# file_extraction_agent

`file_extraction_agent` 是只读语义 HTML 字段抽取器。它接收多个 `documents(filename + html)` 和用户给定 `task_spec`，把材料虚拟成文件树，再让模型通过工具事件完成阅读、证据绑定和字段提交。

## 工作链路

```text
documents + task_spec + run_options
  -> input_adapter 校验 documents 非空、每个 document 有 filename/html、task_spec.fields 非空
  -> html_index 解析 HTML，生成 /001-filename-title/... 虚拟树和 path -> node 索引
  -> paragraph/list/table 分别建成 .md/.list/.table 文件，section header 建成目录
  -> resolution_new 生成抽取提示并挂载 tree/read/anchors/query_table/write_field/submit_result
  -> 模型按 schema 浏览材料、读取文件、查询表格，并用 reason 说明每次用户可见动作
  -> write_field 覆盖写入字段值、状态和 evidence selector
  -> submit_result 校验必填字段、类型和 evidence selector
  -> graph 按顺序输出 NDJSON 工具事件，最后输出 result_completed
```

虚拟树不会落盘。路径是给模型导航和给证据反查用的稳定界面；内部仍通过 `HtmlDocument.nodes_by_path` 找回 paragraph 文本、list item 和 table row。

## 虚拟文件树

建树规则：

- 根目录固定为 `/`。
- 每个输入文件是根目录下的文档目录，目录名形如 `001-source-title`。
- section header 是目录。
- paragraph 是 `.md` 文件，文件名使用同级编号加段落前 `n` 个清洗后的可见字符，例如 `001-公司成立于2020年.md`。
- list 是 `.list` 文件，内部 item 编号为 `I001`、`I001.001`。
- table 是 `.table` 文件，内部 row 编号为 `R001`。
- 同级节点都先按原文顺序编号，用编号保持排序并消除同名冲突。

paragraph 文件名只是预览，不代表截断正文。完整正文由 `read(path)` 返回，句子编号由 `anchors(path)` 返回。

## 工具

| Tool | 作用 |
| --- | --- |
| `tree(path, depth, reason)` | 展开虚拟目录，只返回目录和文件名。 |
| `read(path, offset, limit, reason)` | 读取 `.md/.list/.table` 文件；paragraph 返回纯正文，list/table 返回 Markdown。 |
| `anchors(path, reason)` | 只用于 `.md`，返回 `Sxxx` 句子编号和短 preview。 |
| `query_table(path, sql, offset, limit, reason)` | 只用于 `.table`，在内存表 `data` 上执行单条安全 SELECT。 |
| `write_field(field_id, value, evidence, status, reason)` | 写入或覆盖一个 schema 字段的最终值。 |
| `submit_result(reason)` | 校验当前字段缓冲区，成功返回最终 `fields[]`，失败返回结构化错误。 |

`reason` 是用户可见动作说明，不是证据，也不是模型推理链。工具 wrapper 会为每次调用写入 `tool_started`、`tool_completed` 或 `tool_failed`，字段写入另有 `field_written`，最终提交另有 `result_completed`。

## 读取与证据

paragraph：

```text
read("/001-file/001-概况/001-公司成立于2020年.md")
  -> 返回完整 paragraph 正文，不带句子号
anchors("/001-file/001-概况/001-公司成立于2020年.md")
  -> [{"id": "S001", "preview": "..."}]
write_field(..., evidence=[{"path": "...md", "sentences": ["S001"]}])
```

list：

```text
read("/001-file/002-条款/001-服务范围.list")
  -> frontmatter metadata + Markdown list
  -> - [I001] ...
write_field(..., evidence=[{"path": "...list", "items": ["I001"]}])
```

table：

```text
read("/001-file/003-费用/001-费用明细.table", offset=0, limit=30)
  -> frontmatter metadata + Markdown table
  -> | R001 | ... |
query_table("/001-file/003-费用/001-费用明细.table", "SELECT * FROM data WHERE ...")
  -> 查询结果仍保留原始 Rxxx 行号
write_field(..., evidence=[{"path": "...table", "rows": ["R001"]}])
```

`submit_result` 会校验 selector 类型和编号是否存在：`.md` 只能用 `sentences`，`.list` 只能用 `items`，`.table` 只能用 `rows`。

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
