from __future__ import annotations

from service.file_extraction_agent.impl.schemas import ExtractionInput
from service.file_extraction_agent.schemas import (
    FieldDefinition,
    NormalizedBlock,
    RunOptions,
    TaskSpec,
)


def test_build_graph_input_uses_explicit_task_spec():
    from service.file_extraction_agent import input_adapter

    extraction_input = input_adapter.build_graph_input(
        blocks=[NormalizedBlock(document_id="doc-1", block_id="b-1", text="内容")],
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
    assert isinstance(extraction_input.options, RunOptions)
    assert extraction_input.blocks[0].document_id == "doc-1"
    assert extraction_input.blocks[0].block_id == "b-1"
    assert extraction_input.markdown == "内容"
    assert extraction_input.task_spec.task_name == "invoice"
    assert extraction_input.options.keep_detailed_trace is True
    assert extraction_input.metadata == {"source": "backend"}


def test_build_graph_input_requires_explicit_task_spec():
    from service.file_extraction_agent import input_adapter

    try:
        input_adapter.build_graph_input(
            blocks=[NormalizedBlock(document_id="doc-2", text="空白")],
        )
    except ValueError as exc:
        assert "task_spec is required" in str(exc)
    else:
        raise AssertionError("缺少显式 task_spec 时应拒绝进入抽取图")


def test_build_graph_input_calls_block_contract_before_internal_graph(monkeypatch):
    from service.file_extraction_agent import input_adapter

    calls: list[list[NormalizedBlock]] = []

    def fake_validate_blocks_contract(blocks):
        calls.append(blocks)

    monkeypatch.setattr(input_adapter, "validate_blocks_contract", fake_validate_blocks_contract)
    task_spec = TaskSpec(
        task_name="invoice",
        fields=[FieldDefinition(field_name="invoice_no", display_name="发票号", type="string")],
    )
    blocks = [NormalizedBlock(document_id="doc-2", block_id="b-1", text="内容", page_no=1)]

    extraction_input = input_adapter.build_graph_input(
        blocks=blocks,
        task_spec=task_spec,
    )

    assert calls == [blocks]
    assert extraction_input.blocks[0].block_id == "b-1"


def test_build_graph_input_requires_block_ids_from_upstream():
    from service.file_extraction_agent import input_adapter

    task_spec = TaskSpec(
        task_name="invoice",
        fields=[FieldDefinition(field_name="invoice_no", display_name="发票号", type="string")],
    )

    try:
        input_adapter.build_graph_input(
            blocks=[NormalizedBlock(document_id="doc-2", text="缺少 id", page_no=1)],
            task_spec=task_spec,
        )
    except ValueError as exc:
        assert "block_id is required" in str(exc)
    else:
        raise AssertionError("缺少 block_id 的 block 应被拒绝")


def test_build_graph_input_rejects_duplicate_block_ids():
    from service.file_extraction_agent import input_adapter

    task_spec = TaskSpec(
        task_name="invoice",
        fields=[FieldDefinition(field_name="invoice_no", display_name="发票号", type="string")],
    )

    try:
        input_adapter.build_graph_input(
            blocks=[
                NormalizedBlock(document_id="doc-2", block_id="b-dup", text="内容 A"),
                NormalizedBlock(document_id="doc-2", block_id="b-dup", text="内容 B"),
            ],
            task_spec=task_spec,
        )
    except ValueError as exc:
        assert "duplicate block_id: b-dup" in str(exc)
    else:
        raise AssertionError("重复 block_id 的 blocks 应被拒绝")


def test_build_graph_input_preserves_valid_upstream_block_ids():
    from service.file_extraction_agent import input_adapter

    task_spec = TaskSpec(
        task_name="invoice",
        fields=[FieldDefinition(field_name="invoice_no", display_name="发票号", type="string")],
    )

    extraction_input = input_adapter.build_graph_input(
        blocks=[
            NormalizedBlock(document_id="doc-2", block_id="b-1", text="内容 A", page_no=1),
            NormalizedBlock(document_id="doc-2", block_id="b-2", text="内容 B", page_no=1),
        ],
        task_spec=task_spec,
    )

    assert [block.block_id for block in extraction_input.blocks] == ["b-1", "b-2"]
