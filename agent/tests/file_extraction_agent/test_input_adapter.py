from __future__ import annotations

import json

from file_extraction_agent.schemas import (
    FieldDefinition,
    GraphInput,
    NormalizedDocument,
    RunConfig,
    TaskSpec,
)


def test_build_graph_input_uses_explicit_task_spec():
    from file_extraction_agent import input_adapter

    graph_input = input_adapter.build_graph_input(
        session_id="session-1",
        documents=[NormalizedDocument(document_id="doc-1", markdown="内容")],
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
        run_config=RunConfig(keep_detailed_trace=True),
        metadata={"source": "backend"},
    )

    assert isinstance(graph_input, GraphInput)
    assert graph_input.session_id == "session-1"
    assert graph_input.documents[0].document_id == "doc-1"
    assert graph_input.task_spec.task_name == "invoice"
    assert graph_input.run_config.keep_detailed_trace is True
    assert graph_input.metadata == {"source": "backend"}


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

    graph_input = input_adapter.build_graph_input(
        session_id="session-2",
        documents=[NormalizedDocument(document_id="doc-2")],
        task_spec_name="invoice",
    )

    assert graph_input.task_spec.task_name == "invoice"
    assert graph_input.task_spec.fields[0].field_name == "invoice_no"

