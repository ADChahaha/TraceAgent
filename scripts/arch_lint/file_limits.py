"""仓库手写代码文件收集与单文件行数上限门禁。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.arch_lint.rules import CODE_EXTENSIONS, DEFAULT_MAX_LINES, IGNORED_DIR_PARTS, Violation

GENERATED_PROTO_SUFFIXES = ("_pb2.py", "_pb2_grpc.py", "_pb2.pyi")


def _is_ignored_path(rel_parts: tuple[str, ...]) -> bool:
    if IGNORED_DIR_PARTS & set(rel_parts):
        return True
    return len(rel_parts) >= 2 and rel_parts[0] == "storage" and rel_parts[1] == "data"


def _is_generated_proto(filename: str) -> bool:
    return filename.endswith(GENERATED_PROTO_SUFFIXES)


def collect_code_files(repo_root: Path) -> list[Path]:
    """收集仓库内非忽略的手写代码文件（优先遵循 .gitignore，无 git 目录时退回剪枝遍历）。"""
    root = repo_root.resolve()
    candidates: list[Path] = []
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            for rel in result.stdout.splitlines():
                path = root / rel
                if not path.is_file():
                    continue
                if _is_ignored_path(path.relative_to(root).parts):
                    continue
                if path.suffix in CODE_EXTENSIONS and not _is_generated_proto(path.name):
                    candidates.append(path)
            return sorted(candidates)

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORED_DIR_PARTS and not (rel_dir.parts == ("storage",) and d == "data")
        )
        for fname in sorted(filenames):
            path = Path(dirpath) / fname
            if path.suffix in CODE_EXTENSIONS and not _is_generated_proto(fname):
                candidates.append(path)
    return sorted(candidates)


def check_file_line_limits(repo_root: Path, files: list[Path], max_lines: int = DEFAULT_MAX_LINES) -> list[Violation]:
    """检查每个手写代码文件（含源码、CSS、测试）不超过指定行数上限。"""
    violations: list[Violation] = []
    for path in files:
        line_count = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        if line_count > max_lines:
            rel = path.relative_to(repo_root).as_posix()
            violations.append(
                Violation(
                    rule="FILE_MAX_LINES",
                    file=rel,
                    line=max_lines + 1,
                    message=f"file has {line_count} lines (limit {max_lines})",
                    fix="按单一职责拆分为更小的内聚子模块或测试文件，确保每个手写文件不超过 300 行（见 docs/design-docs/core-beliefs.md）。",
                )
            )
    return violations
