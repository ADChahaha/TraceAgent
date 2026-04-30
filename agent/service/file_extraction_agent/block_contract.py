"""file_extraction_agent 外层 blocks 契约校验。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from service.file_extraction_agent.schemas import NormalizedBlock


def validate_blocks_contract(blocks: Iterable[NormalizedBlock | dict[str, Any]]) -> None:
    """校验外部传入 blocks 是否满足抽取图的最小来源定位契约。"""

    if not isinstance(blocks, list) or not blocks:
        raise ValueError("blocks must be a non-empty list")

    seen_block_ids: set[str] = set()
    duplicated_block_ids: list[str] = []
    for index, block in enumerate(blocks):
        document_id = _read_value(block, "document_id")
        block_id = _read_value(block, "block_id")
        kind = _read_value(block, "kind") or "text"
        text = _read_value(block, "text")

        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError(f"document_id is required at index {index}")
        if not isinstance(block_id, str) or not block_id.strip():
            raise ValueError(f"block_id is required at index {index}")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f"kind is required at index {index}")
        if not isinstance(text, str):
            raise ValueError(f"text is required at index {index}")

        if block_id in seen_block_ids and block_id not in duplicated_block_ids:
            duplicated_block_ids.append(block_id)
        seen_block_ids.add(block_id)

        if kind == "table" and not _has_readable_table_row(text):
            raise ValueError(f"table block cannot be converted to row text at index {index}")

    if duplicated_block_ids:
        raise ValueError(f"duplicate block_id: {', '.join(duplicated_block_ids)}")


def _read_value(block: NormalizedBlock | dict[str, Any], key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key)


def _has_readable_table_row(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if len(lines) >= 2:
        rows = [_split_table_line(line) for line in lines]
        return any(row and not _is_separator_row(row) for row in rows[1:])

    cells = [cell.strip() for cell in text.split("|") if cell.strip()]
    separator_index = next(
        (index for index, cell in enumerate(cells) if _is_separator_cell(cell)),
        None,
    )
    if separator_index is None or separator_index == 0:
        return False
    column_count = separator_index
    data_cells = cells[separator_index + column_count :]
    return len(data_cells) >= column_count


def _split_table_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(_is_separator_cell(cell) for cell in cells)


def _is_separator_cell(cell: str) -> bool:
    return bool(cell) and set(cell) <= {"-", ":"}
