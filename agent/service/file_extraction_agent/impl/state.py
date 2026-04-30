"""file_extraction_agent 图内部执行态。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from service.file_extraction_agent.impl.schemas import (
    BroadFinishRecord,
    Candidate,
    ExtractionInput,
    FieldDecision,
    ToolActionRecord,
)
from service.file_extraction_agent.schemas import NormalizedBlock


TEXT_BLOCK_KINDS = {"section_header", "heading", "text", "text_line"}


class IndexedSource(BaseModel):
    """内部 ref 到原始 block 位置和文本的回查记录。"""

    ref: str
    block_id: str
    document_id: str
    page_no: int | None = None
    locator: str
    text: str


class GraphState(BaseModel):
    """图运行过程中的共享状态容器。"""

    extraction_input: ExtractionInput
    blocks_by_id: dict[str, NormalizedBlock] = Field(default_factory=dict)
    paragraph_index: dict[str, IndexedSource] = Field(default_factory=dict)
    table_row_index: dict[str, IndexedSource] = Field(default_factory=dict)
    candidates: dict[str, list[Candidate]] = Field(default_factory=dict)
    broad_finishes: dict[str, BroadFinishRecord] = Field(default_factory=dict)
    field_decisions: dict[str, FieldDecision] = Field(default_factory=dict)
    actions: dict[str, list[ToolActionRecord]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def build_graph_state(extraction_input: ExtractionInput) -> GraphState:
    """基于入口 `ExtractionInput` 创建索引和空执行态。"""

    blocks_by_id = {
        block.block_id: block
        for block in extraction_input.blocks
        if block.block_id
    }
    state = GraphState(
        extraction_input=extraction_input,
        blocks_by_id=blocks_by_id,
        paragraph_index=_build_paragraph_index(extraction_input.blocks),
        table_row_index=_build_table_row_index(extraction_input.blocks),
    )
    return state


def record_action(
    state: GraphState,
    *,
    field_name: str,
    action: ToolActionRecord,
) -> None:
    """按字段保留系统可证明动作顺序。"""

    state.actions.setdefault(field_name, []).append(action)


def _build_paragraph_index(blocks: list[NormalizedBlock]) -> dict[str, IndexedSource]:
    index: dict[str, IndexedSource] = {}
    for block in blocks:
        if not block.block_id or block.kind == "table":
            continue
        if block.kind not in TEXT_BLOCK_KINDS and block.kind:
            paragraphs = _split_paragraphs(block.text)
        else:
            paragraphs = _split_paragraphs(block.text)
        for paragraph_index, paragraph in enumerate(paragraphs, start=1):
            paragraph_id = f"p{paragraph_index}"
            ref = f"{block.block_id}:p:{paragraph_id}"
            index[ref] = IndexedSource(
                ref=ref,
                block_id=block.block_id,
                document_id=block.document_id,
                page_no=block.page_no,
                locator=f"p:{paragraph_id}",
                text=paragraph,
            )
    return index


def _build_table_row_index(blocks: list[NormalizedBlock]) -> dict[str, IndexedSource]:
    index: dict[str, IndexedSource] = {}
    current_header: list[str] | None = None
    for block in blocks:
        if block.kind != "table" or not block.block_id:
            continue
        row_texts, current_header = _extract_table_row_texts(
            block.text,
            fallback_header=current_header,
        )
        for row_index, row_text in enumerate(row_texts, start=1):
            row_id = f"r{row_index}"
            ref = f"{block.block_id}:r:{row_id}"
            index[ref] = IndexedSource(
                ref=ref,
                block_id=block.block_id,
                document_id=block.document_id,
                page_no=block.page_no,
                locator=f"r:{row_id}",
                text=row_text,
            )
    return index


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if paragraphs:
        return paragraphs
    stripped = text.strip()
    return [stripped] if stripped else []


def _extract_table_row_texts(
    text: str,
    *,
    fallback_header: list[str] | None = None,
) -> tuple[list[str], list[str] | None]:
    header_or_first_row, data_rows = _extract_table_parts(text)
    if not header_or_first_row:
        return [], fallback_header

    if _looks_like_header(header_or_first_row):
        header = header_or_first_row
        next_header = header
    else:
        header = fallback_header
        next_header = fallback_header
        data_rows = [header_or_first_row, *data_rows]

    row_texts: list[str] = []
    for row in data_rows:
        if not row or _is_separator_row(row):
            continue
        if header and len(header) == len(row):
            row_texts.append(" | ".join(f"{column}={value}" for column, value in zip(header, row)))
        else:
            row_texts.append("| " + " | ".join(row) + " |")
    return row_texts, next_header


def _extract_table_parts(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) >= 2:
        rows = [_split_table_line(line) for line in lines if _split_table_line(line)]
        if not rows:
            return [], []
        header = rows[0]
        data_rows = rows[1:]
        if data_rows and _is_separator_row(data_rows[0]):
            data_rows = data_rows[1:]
        return header, data_rows

    return _extract_flattened_table_parts(text)


def _extract_flattened_table_parts(text: str) -> tuple[list[str], list[list[str]]]:
    cells = [cell.strip() for cell in text.split("|")]
    separator_start = next(
        (index for index, cell in enumerate(cells) if _is_separator_cell(cell)),
        None,
    )
    if separator_start is None:
        return [], []

    separator_end = separator_start
    while separator_end < len(cells) and _is_separator_cell(cells[separator_end]):
        separator_end += 1
    column_count = separator_end - separator_start
    if column_count <= 0:
        return [], []

    leading_rows = _read_flattened_rows(cells[:separator_start], column_count=column_count)
    data_rows = _read_flattened_rows(cells[separator_end:], column_count=column_count)
    if not leading_rows:
        return [], data_rows
    return leading_rows[0], [*leading_rows[1:], *data_rows]


def _read_flattened_rows(cells: list[str], *, column_count: int) -> list[list[str]]:
    rows: list[list[str]] = []
    index = 0
    while index < len(cells):
        if cells[index] == "":
            index += 1
        row = cells[index : index + column_count]
        if len(row) < column_count:
            break
        rows.append(row)
        index += column_count
        if index < len(cells) and cells[index] == "":
            index += 1
    return rows


def _split_table_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(_is_separator_cell(cell) for cell in cells)


def _is_separator_cell(cell: str) -> bool:
    return bool(cell) and set(cell) <= {"-", ":"}


def _looks_like_header(cells: list[str]) -> bool:
    non_empty_cells = [cell for cell in cells if cell]
    if not non_empty_cells:
        return False
    value_like_count = sum(1 for cell in non_empty_cells if _looks_like_table_value(cell))
    return value_like_count < len(non_empty_cells) / 2


def _looks_like_table_value(cell: str) -> bool:
    return any(character.isdigit() for character in cell)
