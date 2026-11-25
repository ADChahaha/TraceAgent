"""前端分层边界、循环依赖与跨服务直连端口静态门禁。"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.arch_lint.rules import FRONTEND_FORBIDDEN_DIRECT_PORTS, Violation

# 显式区分副作用导入与带 from 的 import/export，不跨分号吞并后续语句，并使用 MULTILINE 精确定位行号。
IMPORT_RE = re.compile(
    r"""^[ \t]*(?:"""
    r"""import[ \t]+["']([^"'\n]+)["']"""
    r"""|(?:import|export)(?:[ \t]+type)?[ \t]+[^;'"`]+?\bfrom[ \t]+["']([^"'\n]+)["']"""
    r""")""",
    re.MULTILINE,
)


def _frontend_layer(rel: str) -> str | None:
    if not rel.startswith("frontend/src/"):
        return None
    if rel == "frontend/src/lib/session-types.ts":
        return "types"
    if rel.startswith("frontend/src/lib/"):
        return "lib"
    if rel.startswith("frontend/src/components/ui/"):
        return "ui"
    if rel.startswith("frontend/src/components/"):
        return "components"
    if rel.startswith("frontend/src/app/"):
        return "app"
    return None


def _resolve_ts_target(repo_root: Path, source_file: Path, specifier: str) -> str | None:
    if specifier.startswith("@/"):
        base = (repo_root / "frontend" / "src" / specifier[2:]).resolve()
    elif specifier.startswith("."):
        base = (source_file.parent / specifier).resolve()
    else:
        return None

    for candidate in (
        base,
        Path(f"{base}.ts"),
        Path(f"{base}.tsx"),
        base / "index.ts",
        base / "index.tsx",
    ):
        if candidate.is_file():
            try:
                return candidate.relative_to(repo_root).as_posix()
            except ValueError:
                return None
    return None


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    visited: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()

    def dfs(node: str) -> None:
        visited[node] = 1
        stack.append(node)
        for neighbor in graph.get(node, ()):
            state = visited.get(neighbor, 0)
            if state == 1:
                cycle = stack[stack.index(neighbor) :] + [neighbor]
                canon = tuple(sorted(cycle[:-1]))
                if canon not in seen_keys:
                    seen_keys.add(canon)
                    cycles.append(cycle)
            elif state == 0 and neighbor in graph:
                dfs(neighbor)
        stack.pop()
        visited[node] = 2

    for node in sorted(graph):
        if visited.get(node, 0) == 0:
            dfs(node)
    return cycles


def check_frontend_architecture(repo_root: Path, files: list[Path]) -> list[Violation]:
    """校验前端单向分层（types -> lib -> ui -> components -> app）、无循环依赖与代理边界。"""
    violations: list[Violation] = []
    graph: dict[str, list[str]] = {}

    ts_files = [
        p for p in files
        if p.suffix in {".ts", ".tsx"} and p.relative_to(repo_root).as_posix().startswith("frontend/src/")
    ]

    for path in ts_files:
        rel = path.relative_to(repo_root).as_posix()
        src_layer = _frontend_layer(rel)
        text = path.read_text(encoding="utf-8")
        edges: list[str] = []

        for lineno, line in enumerate(text.splitlines(), 1):
            for forbidden in FRONTEND_FORBIDDEN_DIRECT_PORTS:
                if forbidden in line:
                    violations.append(
                        Violation(
                            rule="FRONTEND_BOUNDARY",
                            file=rel,
                            line=lineno,
                            message=f"frontend must not connect directly to internal service '{forbidden}'",
                            fix="前端只经 Next.js /api/backend/* 代理访问 backend，禁止直连 agent/document_service/storage（见 ARCHITECTURE.md）。",
                        )
                    )

        for match in IMPORT_RE.finditer(text):
            specifier = match.group(1) or match.group(2)
            if not specifier:
                continue
            lineno = text.count("\n", 0, match.start()) + 1
            target_rel = _resolve_ts_target(repo_root, path, specifier)
            if target_rel is None:
                continue
            if target_rel.endswith((".ts", ".tsx")):
                edges.append(target_rel)
            target_layer = _frontend_layer(target_rel)
            if src_layer is None or target_layer is None:
                continue

            if src_layer == "types":
                violations.append(
                    Violation(
                        rule="FRONTEND_LAYER",
                        file=rel,
                        line=lineno,
                        message=f"types layer must not import '{target_rel}'",
                        fix="保持 session-types.ts 零内部依赖，只定义纯数据结构契约。",
                    )
                )
            elif src_layer == "lib" and target_layer in {"ui", "components", "app"}:
                violations.append(
                    Violation(
                        rule="FRONTEND_LAYER",
                        file=rel,
                        line=lineno,
                        message=f"lib layer '{rel}' must not depend on higher layer '{target_rel}'",
                        fix="保持单向流 types -> lib -> components -> app；共享状态/逻辑留在 lib，不要反向导入组件。",
                    )
                )
            elif src_layer == "ui" and target_rel != "frontend/src/lib/utils.ts" and target_layer != "ui":
                violations.append(
                    Violation(
                        rule="FRONTEND_LAYER",
                        file=rel,
                        line=lineno,
                        message=f"UI primitive '{rel}' must not depend on domain module '{target_rel}'",
                        fix="components/ui 仅承载通用基础组件，只允许依赖 @/lib/utils 或同层 ui 组件。",
                    )
                )
            elif src_layer == "components" and target_layer == "app":
                violations.append(
                    Violation(
                        rule="FRONTEND_LAYER",
                        file=rel,
                        line=lineno,
                        message=f"component '{rel}' must not import app router entry '{target_rel}'",
                        fix="通过 props 或 @/lib/* 传递数据，不要从 components 反向导入 src/app。",
                    )
                )

        graph[rel] = sorted(set(edges))

    for cycle in _find_cycles(graph):
        chain = " -> ".join(cycle)
        violations.append(
            Violation(
                rule="FRONTEND_CYCLE",
                file=cycle[0],
                line=None,
                message=f"circular import detected: {chain}",
                fix="将共享类型或纯辅助函数抽到下层 @/lib/session-types.ts 或独立无环模块，打破循环依赖。",
            )
        )
    return violations
