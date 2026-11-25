"""HTML 文档 -> 解析标题和段落/列表/表格 -> 编号目录与 Markdown 文件 -> 返回 Path。

本模块只生成文件，不提供问答目录浏览和读取接口。非法 filename/html 抛 ValueError；
文件访问由 file_extraction_agent 的工具层负责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from document_service.document_resources.html_tree import (
    BLOCK_TAGS,
    HEADING_TAGS,
    HtmlNode,
    block_nodes,
    collect_list_item,
    direct_text_without_nested_lists,
    document_title_node,
    list_items,
    node_text,
    parse_html,
    parse_table,
    render_list_markdown,
    render_table_markdown,
    walk,
)
from document_service.document_resources.schemas import InputDocument

DEFAULT_SNIPPET_CHARS = 24


@dataclass
class SourceDocument:
    filename: str
    html: str


def materialize_tree(documents: list[InputDocument], workspace_root: Path) -> Path:
    """校验 HTML 文档 -> 按标题与内容块落盘 -> 返回目录路径。"""
    source_documents = normalize_documents(documents)
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    used_root_names: dict[str, int] = {}

    for document_index, source in enumerate(source_documents, start=1):
        parsed_root = parse_html(source.html)
        title_node = document_title_node(parsed_root)
        title = node_text(title_node) if title_node is not None else ""
        basename = slug_text(Path(source.filename).stem or "document")
        title_slug = slug_text(title) if title else ""
        base_name = f"{document_index:03d}-{basename}" + (f"-{title_slug}" if title_slug else "")
        doc_name = unique_name(base_name, used_root_names)
        doc_dir = root / doc_name
        doc_dir.mkdir(parents=True, exist_ok=True)
        write_document_children(doc_dir, parsed_root, document_index)

    return root


def normalize_documents(documents: list[InputDocument]) -> list[SourceDocument]:
    if not documents:
        raise ValueError("documents must be a non-empty list")
    normalized: list[SourceDocument] = []
    for index, document in enumerate(documents, start=1):
        if not document.filename.strip():
            raise ValueError(f"documents[{index}].filename is required")
        if not document.html.strip():
            raise ValueError(f"documents[{index}].html must be a non-empty string")
        normalized.append(SourceDocument(filename=document.filename.strip(), html=document.html))
    return normalized


def write_document_children(doc_dir: Path, parsed_root: HtmlNode, document_index: int) -> None:
    """按解析后的 HTML 块顺序写入章节目录与编号 Markdown 文件。"""
    section_stack: list[tuple[int, Path]] = [(0, doc_dir)]
    sibling_counters: dict[Path, dict[str, int]] = {doc_dir: {}}

    for node in block_nodes(parsed_root):
        if node.tag in HEADING_TAGS:
            level = int(node.tag[1])
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            parent_dir = section_stack[-1][1] if section_stack else doc_dir
            name = numbered_name(parent_dir, slug_text(node_text(node)) or "section", sibling_counters, suffix="")
            section_dir = parent_dir / name
            section_dir.mkdir(parents=True, exist_ok=True)
            sibling_counters[section_dir] = {}
            section_stack.append((level, section_dir))
            continue

        parent_dir = section_stack[-1][1] if section_stack else doc_dir
        if node.tag == "p":
            text = node_text(node)
            name = numbered_name(parent_dir, paragraph_slug(text), sibling_counters, suffix=".md")
            write_markdown_file(parent_dir / name, text)
        elif node.tag in {"ul", "ol"}:
            items = list_items(node)
            title = slug_text(items[0]["text"][:DEFAULT_SNIPPET_CHARS]) if items else "list"
            name = numbered_name(parent_dir, title or "list", sibling_counters, suffix=".md")
            write_markdown_file(parent_dir / name, render_list_markdown(items))
        elif node.tag == "table":
            table = parse_table(node)
            title = slug_text(table.get("label") or " ".join(table["columns"][:3]) or "table")
            name = numbered_name(parent_dir, title or "table", sibling_counters, suffix=".md")
            write_markdown_file(parent_dir / name, render_table_markdown(table))


def write_markdown_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def numbered_name(parent: Path, slug: str, counters: dict[Path, dict[str, int]], *, suffix: str) -> str:
    bucket = counters.setdefault(parent, {})
    ordinal = sum(bucket.values()) + 1
    base = f"{ordinal:03d}-{slug}{suffix}"
    bucket[base] = bucket.get(base, 0) + 1
    if bucket[base] == 1:
        return base
    stem = base[: -len(suffix)] if suffix else base
    return f"{stem}-{bucket[base]}{suffix}"


def unique_name(base: str, used: dict[str, int]) -> str:
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else f"{base}-{used[base]}"


def order_key(name: str) -> int:
    digits = ""
    for char in name:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits) if digits else 0


def slug_text(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    normalized = re.sub(r'[\\/:*?"<>|#]+', "-", normalized)
    normalized = normalized.strip(" .-_。；;，,、")
    return normalized[:60] or "empty"


def paragraph_slug(text: str) -> str:
    return slug_text(str(text or "")[:DEFAULT_SNIPPET_CHARS])


__all__ = [
    "BLOCK_TAGS",
    "HEADING_TAGS",
    "HtmlNode",
    "SourceDocument",
    "block_nodes",
    "collect_list_item",
    "direct_text_without_nested_lists",
    "document_title_node",
    "list_items",
    "materialize_tree",
    "node_text",
    "order_key",
    "parse_html",
    "parse_table",
    "render_list_markdown",
    "render_table_markdown",
    "walk",
]
