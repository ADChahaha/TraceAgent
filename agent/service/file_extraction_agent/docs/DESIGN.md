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

- `read_element(element_id)`: read one element. Tables return columns/header
  metadata only.
- `table_extraction(table_id, sql)`: run a single `SELECT` against one table as
  SQL table `data`.
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

## Resolution

`resolution.py` builds a LangGraph tool-calling loop:

```text
agent -> tools -> agent
          |
          finish ok / max_tool_calls -> END
```

The resolution model receives a compact built-in text outline, not raw
`str(document.tree)` JSON. It sees only the five public tool wrappers and never
sees `GraphState`.

## Evidence

Evidence ids are existing HTML ids. For table values, evidence should include
the `table_id` and matching `row_id`; column names are kept in trace when useful.

Cell ids are not required because `document_processor` does not automatically
assign ids to `td`/`th`.
