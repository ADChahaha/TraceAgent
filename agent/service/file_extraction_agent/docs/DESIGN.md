# File Extraction Agent Design

## Goal

`file_extraction_agent` extracts structured fields from HTML produced by
`document_processor`.

The HTML already contains stable ids. This package never creates, rewrites, or
repairs ids. It only validates the ids it needs and builds runtime indexes from
those existing ids.

```text
html with existing ids + task_spec
  -> html_index builds lookup indexes and overview tree
  -> broad plans how resolution should extract fields
  -> resolution uses LangGraph tool calling
  -> table_extraction returns row evidence plus quality diagnostics when tables are queried
  -> set_field records values and evidence ids
  -> finish validates required fields
  -> ExtractionResult
```

## File Tree

```text
service/file_extraction_agent/
├── processor.py
├── schemas.py
└── impl/
    ├── graph.py
    ├── html_index.py
    ├── model_factory.py
    ├── broad_new.py
    ├── resolution_new.py
    └── html_tools.py

tests/file_extraction_agent/
├── test_processor.py
├── test_html_index_new.py
├── test_graph.py
├── test_broad_new.py
└── test_html_tools_new.py
```

## Public API

`processor.extract(...)` is the public entrypoint.

```python
extract(
    *,
    html: str,
    task_spec: TaskSpec | dict,
    model_config: ModelConfig | dict | None = None,
    run_options: RunOptions | dict | None = None,
) -> ExtractionResult
```

Parameters:

- `html`: HTML fragment/string from `document_processor`. Required tracking
  elements must already have `id`.
- `task_spec`: fields to extract and optional global instructions.
- `model_config`: same provider for broad and resolution, with separate model
  names.
- `run_options`: runtime budget. First version only exposes `max_tool_calls`.

There is no `metadata` parameter in the extraction core.

## HTML Indexing

`html_index.py` parses the HTML and builds indexes from existing ids:

- `elements_by_id`: existing element id -> normalized element record.
- `tree`: model-facing document overview.
- `tables_by_id`: existing table id -> parsed table rows.
- `row_index`: existing row id -> table row location.

The indexer validates:

- required tags have ids: headings, `p`, `li`, `table`, `tr`, `caption`, `ul`,
  and `ol`;
- ids are unique;
- table rows used as evidence have ids.

The indexer does not:

- generate ids;
- mutate HTML;
- preserve full DOM noise in the overview tree.

## Document Tree

The final `document_processor` HTML keeps tags and ids, but not Docling label
attributes. The tree therefore infers semantic type from tags:

| HTML tag | Tree type |
|---|---|
| `h1` | `TITLE` |
| `h2`-`h6` | `SECTION_HEADER` |
| `p` | `TEXT` |
| `li` | `LIST_ITEM` |
| `table` | `TABLE` |
| `caption` | `CAPTION` |

Tree construction rules:

- headings form hierarchy by numeric level;
- only headings and tables appear in the overview tree;
- tables attach to the nearest active heading;
- if no heading exists, tables attach to root;
- table rows and cells do not appear in the overview tree;
- table nodes show table name, columns, and row count, never full rows.

## Tools

`tools.py` exposes resolution tools through `build_tools(state)`.

Internal implementations take `state`; public tool wrappers do not. The wrapper
docstrings are the model-facing function descriptions.

Tools:

- `update_plan(plan_index, status, reason)`: record replay plan progress. Plan
  status is a strict sequence:

```text
Broad plan[1..N]
  -> 只能把最早一个未完成项标记为 in_progress
  -> 该项完成证据读取、字段写入或失败决策
  -> 只能把当前 in_progress 的同一项标记为 completed
  -> 进入下一项
```

  这条规则同时写在 prompt 和工具校验里；如果模型直接跳到后面的
  `plan_index`，或者没有先 `in_progress` 就 `completed`，工具会返回
  `ok=false`，让模型按最早未完成项重试。
- `read_element(element_id)`: read one element. Tables return `table-ref`
  metadata only: table id, optional label, row count, header row id, and
  columns. They never return table data rows.
- `table_extraction(table_id, sql)`: run a single `SELECT` against one table as
  SQL table `data`. Small tables may use `SELECT *`. Large tables reject
  unbounded `SELECT *`; the model should select explicit columns with `WHERE`
  when possible, or use `SELECT * FROM data LIMIT 50 OFFSET n` as a bounded
  fallback for messy tables. Explicit-column queries are not truncated by row
  count. The tool also returns lightweight audit observations:
  `table_audit` describes table-level structure facts, while `query_audit`
  describes facts tied to this SQL result. The model-facing tool description
  includes query audit few-shot guidance: blank filter cells must be judged from
  table context, not from the fact that `WHERE` did not select them.
- `paragraph_extraction(element_id, pattern)`: regex search one text-like
  element and return all matches.
- `set_field(name, value, evidence_ids, status, failure_reason)`: record one
  field value or failure.
- `finish()`: validate required fields, value types, and evidence ids.

## Broad

`broad.py` is a planner only. It receives task spec, overview context, and the
full HTML document, then uses a single bound function tool:

```python
return_broad_plan(summary: str, plan: list[str], risks: list[str])
```

The model must return its plan by function call. Do not use `json_schema` or
response-format structured output.

For table-heavy fields, broad does not see `query_audit` yet, but it must plan
for resolution to explain `query_audit.summary` in the later `set_field.reason`.
It should not turn blank filter cells into a risk conclusion by itself.

## Resolution

`resolution.py` builds a LangGraph tool-calling loop:

```text
agent -> tools -> agent
          |
          finish ok / max_tool_calls -> END
```

The resolution model receives a compact built-in text outline, not raw
`str(document.tree)` JSON. It sees only the five public tool wrappers and never
sees `GraphState`. Its system prompt includes query audit few-shot guidance:

```text
query_audit.summary says a filter column has blanks
  -> inspect table headers, notes, grouping, adjacent columns, selected output
     cells, and the field goal
  -> if context proves blank rows are outside the target category
  -> write set_field(reason=...) explaining that context

query_audit.summary shows blank filter cells / near_match_rows / empty outputs
  -> if headers, notes, grouping, adjacent columns, or refs do not prove the
     unselected rows are irrelevant
  -> continue checking or write failed for human review
```

## Evidence

Evidence ids are existing HTML ids. For table values, evidence should include
the `table_id` and matching `row_id`; column names are kept in trace when useful.

Cell ids are not required because `document_processor` does not automatically
assign ids to `td`/`th`.

## Table Audit Observations

Table audit observations are generated inside `html_tools._table_extraction(...)`
because this is the first point where the system knows both the parsed table
structure and the model's concrete SQL.

```text
table_id + SQL
  -> read parsed HtmlTable from html_index
  -> reject unsafe SQL or unbounded large SELECT *
  -> compute table_audit from the whole parsed table
  -> execute SQL against in-memory SQLite table data
  -> compute query_audit from selected rows, selected columns, and WHERE equality predicates
  -> return rows + evidence_ids + table_audit + query_audit
  -> record the same audit summaries in the action trace for route policy and frontend replay
```

`table_audit` is table-level and factual. It reports row/column counts, columns,
blank-cell distribution, and structure signals such as repeated header-looking
rows. It does not include a `status` and does not decide whether a field is
wrong.

`query_audit` is field/query-specific and factual. It reports returned row
count, WHERE equality predicate columns, blank counts in filter columns,
non-empty distributions, near matches, selected output-column empty counts, and
evidence integrity. It also includes a short `summary` that can be shown in the
frontend and passed to route policy.

Route policy does not hard-review on a diagnostic status flag because audit
observations do not carry one. The policy model receives `query_audit.summary`
plus `field_resolution.reason`, then decides whether observations such as blank
filter cells are harmless context or require manual review.
