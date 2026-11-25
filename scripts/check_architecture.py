#!/usr/bin/env python3
"""TraceAgent 架构与单文件行数上限机械门禁（参考 OpenAI Harness Engineering）。

检查项：
1. 全仓手写代码文件（.py/.ts/.tsx/.js/.jsx/.css，含测试，仅豁免自动生成 *_pb2*.py）<= 300 行；
2. 顶层 7 包单向分层（与 ARCHITECTURE.md 一致）；
3. 各包内固定分层与依赖倒置原则（DIP：核心业务与路由只依赖抽象 Protocol，具体适配只在装配根注入）；
4. 前端单向分层（types -> lib -> ui -> components -> app）、无循环依赖与代理边界。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.arch_lint.file_limits import check_file_line_limits, collect_code_files
from scripts.arch_lint.frontend_checks import check_frontend_architecture
from scripts.arch_lint.python_checks import check_python_architecture
from scripts.arch_lint.rules import DEFAULT_MAX_LINES, Violation


def check_architecture(repo_root: Path | None = None, *, max_lines: int = DEFAULT_MAX_LINES) -> dict:
    """对目标仓库执行完整架构与行数审计，返回结构化结果。"""
    root = (repo_root or REPO_ROOT).resolve()
    files = collect_code_files(root)
    line_violations = check_file_line_limits(root, files, max_lines=max_lines)
    python_violations = check_python_architecture(root, files)
    frontend_violations = check_frontend_architecture(root, files)
    all_violations = [*line_violations, *python_violations, *frontend_violations]
    return {
        "repo_root": str(root),
        "max_lines": max_lines,
        "files_checked": len(files),
        "line_violations": line_violations,
        "python_violations": python_violations,
        "frontend_violations": frontend_violations,
        "violations": all_violations,
    }


def has_violations(report: dict) -> bool:
    return bool(report["violations"])


def print_report(report: dict) -> None:
    print("# Repository Architecture & Line-Limit Audit")
    print(f"- Files checked: {report['files_checked']} (max lines: {report['max_lines']})")
    print(f"- Line-limit violations: {len(report['line_violations'])}")
    print(f"- Python layer & DIP violations: {len(report['python_violations'])}")
    print(f"- Frontend layer & cycle violations: {len(report['frontend_violations'])}")
    violations: list[Violation] = report["violations"]
    if not violations:
        print("- Status: PASS (0 violations)")
        return
    print("- Violations:")
    for item in violations:
        for line in item.format_line().splitlines():
            print(f"  {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查单文件 300 行上限、单向分层与依赖倒置架构边界。")
    parser.add_argument("--repo-root", type=Path, default=None, help="覆盖待检查仓库根目录")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES, help="单文件最大允许行数（默认 300）")
    args = parser.parse_args(argv)
    report = check_architecture(args.repo_root, max_lines=args.max_lines)
    print_report(report)
    return 1 if has_violations(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
