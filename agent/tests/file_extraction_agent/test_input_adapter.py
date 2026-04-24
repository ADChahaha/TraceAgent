from __future__ import annotations

import json

from file_extraction_agent.impl.schemas import ExtractionInput, RunOptions
from file_extraction_agent.schemas import (
    FieldDefinition,
    NormalizedBlock,
    TaskSpec,
)


def test_build_graph_input_uses_explicit_task_spec():
    from file_extraction_agent import input_adapter

    extraction_input = input_adapter.build_graph_input(
        blocks=[NormalizedBlock(document_id="doc-1", text="内容")],
        markdown="内容",
        task_spec=TaskSpec(
            task_name="invoice",
            fields=[
                FieldDefinition(
                    field_name="invoice_no",
                    display_name="发票号",
                    type="string",
                )
            ],
        ),
        run_options=RunOptions(keep_detailed_trace=True),
        metadata={"source": "backend"},
    )

    assert isinstance(extraction_input, ExtractionInput)
    assert extraction_input.blocks[0].document_id == "doc-1"
    assert extraction_input.markdown == "内容"
    assert extraction_input.task_spec.task_name == "invoice"
    assert extraction_input.options.keep_detailed_trace is True
    assert extraction_input.metadata == {"source": "backend"}


def test_build_graph_input_loads_task_spec_from_name(monkeypatch, tmp_path):
    from file_extraction_agent import input_adapter

    task_spec_dir = tmp_path / "task_specs"
    task_spec_dir.mkdir()
    (task_spec_dir / "invoice.json").write_text(
        json.dumps(
            {
                "task_name": "invoice",
                "fields": [
                    {
                        "field_name": "invoice_no",
                        "display_name": "发票号",
                        "type": "string",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(input_adapter, "TASK_SPECS_DIR", task_spec_dir)

    extraction_input = input_adapter.build_graph_input(
        blocks=[NormalizedBlock(document_id="doc-2", text="空白")],
        task_spec_name="invoice",
    )

    assert extraction_input.task_spec.task_name == "invoice"
    assert extraction_input.task_spec.fields[0].field_name == "invoice_no"

