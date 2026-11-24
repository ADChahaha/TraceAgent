#!/usr/bin/env python3
"""仓库知识文档机械门禁：校验顶层骨架、链接锚点、模块 DECISIONS.md 收录、归档决策迁出与文风预算。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIR_PARTS = {
    ".git",
    ".agents",
    "memory",
    "experiments",
    "node_modules",
    "build",
    ".next",
    ".pytest_cache",
    "__pycache__",
    "dist",
}
FORBIDDEN_STYLE_CHARS = ("\u2014", "\u201c", "\u201d", "\u2018", "\u2019")
AGENTS_MAX_LINES = 80
AGENTS_MAX_CHARS = 4000
REQUIRED_FILES = (
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/design-docs/index.md",
    "docs/design-docs/core-beliefs.md",
    "docs/product-specs/index.md",
    "docs/exec-plans/tech-debt-tracker.md",
)
REQUIRED_DIRS = (
    "docs/exec-plans/active",
    "docs/exec-plans/completed",
)
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")


def _is_ignored(path: Path, repo_root: Path) -> bool:
    rel_parts = path.relative_to(repo_root).parts
    if IGNORED_DIR_PARTS & set(rel_parts):
        return True
    return len(rel_parts) >= 2 and rel_parts[0] == "storage" and rel_parts[1] == "data"


def gfm_slug(text: str) -> str:
    out: list[str] = []
    for ch in text.strip().lower():
        if ch in (" ", "-"):
            out.append("-")
        elif ch.isalnum() or ch == "_":
            out.append(ch)
    return "".join(out)


def list_rel_md(subdir: Path) -> list[str]:
    return [p.relative_to(subdir).as_posix() for p in sorted(subdir.rglob("*.md"))] if subdir.exists() else []


def iter_module_decisions(repo_root: Path) -> list[Path]:
    return sorted(p for p in repo_root.rglob("DECISIONS.md") if not _is_ignored(p, repo_root))


def find_unmigrated_completed_decisions(completed_dir: Path) -> list[str]:
    """检查 docs/exec-plans/completed/ 中归档计划的决策记录是否均标注去向或临时有效。"""
    violations: list[str] = []
    if not completed_dir.exists():
        return violations
    for plan in sorted(completed_dir.glob("*.md")):
        in_decision_log = False
        for lineno, raw_line in enumerate(plan.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw_line.strip()
            if stripped.startswith("## "):
                in_decision_log = stripped.lower() in {"## decision log", "## 决策记录"}
                continue
            if not in_decision_log or not stripped.startswith("- "):
                continue
            has_disposition = (
                "->" in stripped
                or bool(LINK_RE.search(stripped))
                or "临时有效" in stripped
                or "无需沉淀" in stripped
            )
            if not has_disposition:
                violations.append(f"{plan.name}:{lineno}: {stripped}")
    return violations


def check_docs_integrity(repo_root: Path | None = None) -> dict:
    """校验仓库公开知识文档完整性，不依赖任何本地忽略目录。"""
    root = (repo_root or REPO_ROOT).resolve()
    docs_dir = root / "docs"
    design_index = docs_dir / "design-docs" / "index.md"
    active_plans_dir = docs_dir / "exec-plans" / "active"
    completed_plans_dir = docs_dir / "exec-plans" / "completed"

    missing_required: list[str] = []
    for rel in REQUIRED_FILES:
        if not (root / rel).is_file():
            missing_required.append(rel)
    for rel in REQUIRED_DIRS:
        if not (root / rel).is_dir():
            missing_required.append(rel + "/")

    module_decisions_paths = iter_module_decisions(root)
    module_decisions = [p.relative_to(root).as_posix() for p in module_decisions_paths]

    md_set: set[Path] = set()
    for fixed in (root / "AGENTS.md", root / "ARCHITECTURE.md"):
        if fixed.is_file():
            md_set.add(fixed)
    if docs_dir.exists():
        for p in docs_dir.rglob("*.md"):
            if not _is_ignored(p, root):
                md_set.add(p)
    md_set.update(module_decisions_paths)
    md_files = sorted(md_set)

    total_links = 0
    broken: list[tuple[str, str, str]] = []
    budget_and_style_violations: list[dict] = []

    for f in md_files:
        rel = f.relative_to(root).as_posix()
        txt = f.read_text(encoding="utf-8")
        lines = txt.splitlines()

        reasons: list[str] = []
        if rel == "AGENTS.md":
            if len(lines) > AGENTS_MAX_LINES:
                reasons.append(f"lines={len(lines)}>{AGENTS_MAX_LINES}")
            if len(txt) > AGENTS_MAX_CHARS:
                reasons.append(f"chars={len(txt)}>{AGENTS_MAX_CHARS}")
        bad_chars = [ch for ch in FORBIDDEN_STYLE_CHARS if ch in txt]
        if bad_chars:
            reasons.append(f"forbidden_chars={''.join(bad_chars)}")
        if reasons:
            budget_and_style_violations.append({"file": rel, "reasons": reasons})

        for line in lines:
            for m in LINK_RE.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                total_links += 1
                if target.startswith("/"):
                    if not Path(target).exists():
                        broken.append((rel, target, "missing_abs"))
                    continue
                path_part, _, frag = target.partition("#")
                target_path = (f.parent / urllib.parse.unquote(path_part)).resolve() if path_part else f.resolve()
                if not target_path.exists():
                    broken.append((rel, target, "missing_file"))
                    continue
                if frag:
                    target_text = target_path.read_text(encoding="utf-8", errors="ignore")
                    slugs = {gfm_slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", target_text, flags=re.M)}
                    if urllib.parse.unquote(frag) not in slugs:
                        broken.append((rel, target, "missing_anchor"))

    unindexed_decisions: list[str] = []
    if design_index.is_file():
        indexed_targets: set[Path] = set()
        for m in LINK_RE.finditer(design_index.read_text(encoding="utf-8")):
            href = m.group(1).split("#", 1)[0]
            if not href or href.startswith(("http://", "https://", "mailto:", "/")):
                continue
            indexed_targets.add((design_index.parent / urllib.parse.unquote(href)).resolve())
        unindexed_decisions = [
            p.relative_to(root).as_posix()
            for p in module_decisions_paths
            if p.resolve() not in indexed_targets
        ]
    else:
        unindexed_decisions = list(module_decisions)

    unmigrated_completed_decisions = find_unmigrated_completed_decisions(completed_plans_dir)

    agents_path = root / "AGENTS.md"
    if agents_path.is_file():
        agents_txt = agents_path.read_text(encoding="utf-8")
        agents_lines = len(agents_txt.splitlines())
        agents_chars = len(agents_txt)
    else:
        agents_lines = 0
        agents_chars = 0

    return {
        "agents_md_lines": agents_lines,
        "agents_md_chars": agents_chars,
        "docs_checked": len(md_files),
        "module_decisions": module_decisions,
        "active_exec_plans": list_rel_md(active_plans_dir),
        "completed_exec_plans": list_rel_md(completed_plans_dir),
        "total_links": total_links,
        "missing_required": missing_required,
        "broken": broken,
        "unindexed_decisions": unindexed_decisions,
        "unmigrated_completed_decisions": unmigrated_completed_decisions,
        "budget_and_style_violations": budget_and_style_violations,
    }


def has_violations(report: dict) -> bool:
    return any(
        report[key]
        for key in (
            "missing_required",
            "broken",
            "unindexed_decisions",
            "unmigrated_completed_decisions",
            "budget_and_style_violations",
        )
    )


def print_report(report: dict) -> None:
    print("# Repository Docs Audit")
    print(f"- `AGENTS.md`: {report['agents_md_lines']} lines, {report['agents_md_chars']} chars")
    print(
        f"- Knowledge docs checked: {report['docs_checked']} files "
        f"(module `DECISIONS.md`: {len(report['module_decisions'])})"
    )
    print(f"- Active exec plans (`docs/exec-plans/active/`): {report['active_exec_plans']}")
    print(f"- Completed exec plans (`docs/exec-plans/completed/`): {report['completed_exec_plans']}")
    print(f"- Missing required entries: {report['missing_required']}")
    print(f"- Links checked: {report['total_links']}, broken: {report['broken']}")
    print(f"- Unindexed `DECISIONS.md`: {report['unindexed_decisions']}")
    print(f"- Unmigrated completed decisions: {report['unmigrated_completed_decisions']}")
    print(
        f"- Budget & style violations: {len(report['budget_and_style_violations'])}"
        + (" []" if not report["budget_and_style_violations"] else "")
    )
    for item in report["budget_and_style_violations"]:
        print(f"  - `{item['file']}`: {', '.join(item['reasons'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查仓库顶层知识文档、链接、模块 DECISIONS.md 收录与文风门禁。")
    parser.add_argument("--repo-root", type=Path, default=None, help="覆盖待检查仓库根目录")
    args = parser.parse_args()

    report = check_docs_integrity(args.repo_root)
    print_report(report)
    return 1 if has_violations(report) else 0


if __name__ == "__main__":
    sys.exit(main())
