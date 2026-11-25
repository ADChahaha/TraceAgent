"""Python AST 导入提取、顶层 7 包单向分层校验与包内规则调度。"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.arch_lint.python_package_rules import (
    check_agent_file,
    check_backend_file,
    check_document_service_file,
)
from scripts.arch_lint.rules import (
    CONCRETE_OBJECT_STORE_SYMBOLS,
    PACKAGE_ALLOWED_INTERNAL,
    REPO_TOP_MODULES,
    Violation,
)


def _resolve_relative_module(rel: str, level: int, module: str | None) -> str | None:
    parts = list(Path(rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    base = parts[:-level] if level <= len(parts) else []
    if not base:
        return None
    return ".".join([*base, *module.split(".")]) if module else ".".join(base)


def _extract_python_imports(path: Path, rel: str) -> tuple[list[tuple[int, str, list[str]]], list[tuple[int, str]]]:
    """提取 Python AST 中全部导入（含相对导入、from parent import submod 与局部导入）及具体对象存储引用。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[int, str, list[str]]] = []
    concrete_attrs: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name, []))
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            resolved = node.module if node.level == 0 else _resolve_relative_module(rel, node.level, node.module)
            if resolved:
                imports.append((node.lineno, resolved, names))
        elif isinstance(node, ast.Attribute) and node.attr in CONCRETE_OBJECT_STORE_SYMBOLS:
            concrete_attrs.append((node.lineno, node.attr))
    return imports, concrete_attrs


def check_python_architecture(repo_root: Path, files: list[Path]) -> list[Violation]:
    """执行 Python 跨包单向分层、包内分层与依赖倒置检查（仅作用于生产代码）。"""
    violations: list[Violation] = []
    for path in files:
        if path.suffix != ".py":
            continue
        rel = path.relative_to(repo_root).as_posix()
        parts = Path(rel).parts
        if "tests" in parts:
            continue
        top_pkg = parts[0] if parts else ""
        if top_pkg not in PACKAGE_ALLOWED_INTERNAL:
            continue
        imports, concrete_attrs = _extract_python_imports(path, rel)
        allowed = PACKAGE_ALLOWED_INTERNAL[top_pkg]
        for lineno, module, _ in imports:
            root_mod = module.split(".")[0]
            if root_mod in REPO_TOP_MODULES and root_mod not in allowed:
                violations.append(
                    Violation(
                        rule="PACKAGE_LAYER",
                        file=rel,
                        line=lineno,
                        message=f"top-level package '{top_pkg}' must not import '{module}'",
                        fix=f"严守 ARCHITECTURE.md 顶层单向分层：'{top_pkg}' 仅允许依赖 {sorted(allowed)}，跨服务协作请经 gRPC 契约或 ObjectStore 交接。",
                    )
                )
        if top_pkg == "backend":
            violations.extend(check_backend_file(rel, imports, concrete_attrs))
        elif top_pkg == "agent":
            violations.extend(check_agent_file(rel, imports))
        elif top_pkg == "document_service":
            violations.extend(check_document_service_file(rel, imports, concrete_attrs))
    return violations
