"""标准化 block id 的内部校验工具。"""

from __future__ import annotations

from file_extraction_agent.schemas import NormalizedBlock


def validate_block_ids(blocks: list[NormalizedBlock]) -> list[NormalizedBlock]:
    """校验 blocks 都带有外部传入的唯一 block_id。"""

    seen_block_ids: set[str] = set()
    duplicated_block_ids: list[str] = []
    for index, block in enumerate(blocks):
        block_id = require_block_id(block, index=index)
        if block_id in seen_block_ids and block_id not in duplicated_block_ids:
            duplicated_block_ids.append(block_id)
        seen_block_ids.add(block_id)

    if duplicated_block_ids:
        raise ValueError(f"duplicate block_id: {', '.join(duplicated_block_ids)}")
    return blocks


def require_block_id(block: NormalizedBlock, *, index: int | None = None) -> str:
    """读取外部传入的 block_id；缺失时直接报错。"""

    if block.block_id is None or not block.block_id.strip():
        suffix = f" at index {index}" if index is not None else ""
        raise ValueError(f"block_id is required{suffix}")
    return block.block_id
