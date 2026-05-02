"""Prepare Docling HTML for user display without stripping useful styling."""

from __future__ import annotations

import re

from service.document_processor.html_cleaner import ID_TAGS, id_counter_name
from service.document_processor.table_merger import (
    HtmlNode,
    HtmlTreeParser,
    serialize_node,
)


UNUSED_CSS_SELECTORS = {
    ".formula",
    ".formula-not-decoded",
    ".key-value-region",
    ".form-container",
    ".form-item",
    ".image-classification",
}

REPLAY_STYLE = """
.dp-evidence-highlight {
    outline: 3px solid #f59e0b;
    background-color: #fff7cc;
    transition: background-color 160ms ease, outline-color 160ms ease;
}
""".strip()


def build_display_html(html: str, *, id_prefix: str = "dp") -> str:
    """Return Docling HTML with stable ids and lightweight replay CSS.

    Unlike ``clean_semantic_html``, this keeps the original Docling page shell,
    CSS, class names, and inline styles for user-facing display. It only adds
    missing ids to the same semantic tags used by the extraction HTML and trims
    CSS blocks that are irrelevant to the current document.
    """

    parser = HtmlTreeParser()
    parser.feed(html)
    parser.close()
    assign_display_ids(parser.root.children, prefix=id_prefix)
    prune_unused_css(parser.root.children)
    append_replay_style(parser.root.children)
    return "".join(serialize_node(child) for child in parser.root.children)


def assign_display_ids(nodes: list[HtmlNode], *, prefix: str) -> None:
    counters: dict[str, int] = {}
    for node in walk_nodes(nodes):
        if node.tag is None or attr_value(node, "id") or node.tag not in ID_TAGS:
            continue
        id_name = id_counter_name(node.tag)
        counters[id_name] = counters.get(id_name, 0) + 1
        node.attrs.append(("id", f"{prefix}-{id_name}-{counters[id_name]}"))


def prune_unused_css(nodes: list[HtmlNode]) -> None:
    used_classes = collect_used_classes(nodes)
    for node in walk_nodes(nodes):
        if node.tag != "style":
            continue
        css = "".join(child.text for child in node.children if child.tag is None)
        pruned = prune_css_rules(css, used_classes)
        node.children = [HtmlNode(tag=None, text=pruned)] if pruned.strip() else []


def append_replay_style(nodes: list[HtmlNode]) -> None:
    head = first_node_by_tag(nodes, "head")
    target = head if head is not None else first_node_by_tag(nodes, "body")
    if target is None:
        nodes.append(HtmlNode(tag="style", children=[HtmlNode(tag=None, text=REPLAY_STYLE)]))
        return
    target.children.append(HtmlNode(tag="style", children=[HtmlNode(tag=None, text=REPLAY_STYLE)]))


def prune_css_rules(css: str, used_classes: set[str]) -> str:
    """Remove obvious unused class-only CSS blocks from Docling output."""

    if not css.strip():
        return ""
    chunks = re.findall(r"([^{}]+)\{([^{}]*)\}", css, flags=re.DOTALL)
    if not chunks:
        return css.strip()
    kept: list[str] = []
    for selector, body in chunks:
        selector_text = " ".join(selector.split())
        if should_keep_css_rule(selector_text, used_classes):
            kept.append(f"{selector_text} {{\n{body.strip()}\n}}")
    return "\n".join(kept)


def should_keep_css_rule(selector: str, used_classes: set[str]) -> bool:
    classes = set(re.findall(r"\.([A-Za-z0-9_-]+)", selector))
    if not classes:
        return True
    if any(f".{class_name}" in UNUSED_CSS_SELECTORS for class_name in classes):
        return bool(classes & used_classes)
    return bool(classes & used_classes)


def collect_used_classes(nodes: list[HtmlNode]) -> set[str]:
    classes: set[str] = set()
    for node in walk_nodes(nodes):
        raw = attr_value(node, "class") if node.tag is not None else None
        if raw:
            classes.update(item for item in raw.split() if item)
    return classes


def first_node_by_tag(nodes: list[HtmlNode], tag: str) -> HtmlNode | None:
    for node in walk_nodes(nodes):
        if node.tag == tag:
            return node
    return None


def walk_nodes(nodes: list[HtmlNode]):
    for node in nodes:
        yield node
        yield from walk_nodes(node.children)


def attr_value(node: HtmlNode, name: str) -> str | None:
    for attr_name, value in node.attrs:
        if attr_name == name:
            return value
    return None
