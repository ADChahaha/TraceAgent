# file_extraction_agent

HTML-based document field extraction agent.

Input is semantic HTML produced by `document_processor`; all trackable elements must already have ids. The package builds a lightweight HTML index, runs a broad planning stage, and then runs a LangGraph resolution agent with document tools.

Public entrypoint:

```python
from service.file_extraction_agent.processor import extract

result = extract(
    html='<p id="dp-p-1">正文</p>',
    task_spec={"fields": [{"name": "title", "type": "string", "required": True}]},
    model_config={
        "base_url": "https://example.com/v1",
        "api_key": "...",
        "broad_model_name": "...",
        "resolution_model_name": "...",
    },
    run_options={"max_tool_calls": 40},
)
```

See `docs/DESIGN.md` for the current architecture.
