"""校验仓库顶层 Harness 文档骨架、全仓 DECISIONS.md 总目收录与归档计划决策迁出。"""

from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORED_DIR_PARTS = {".git", "node_modules", "build", ".next", ".pytest_cache", "__pycache__"}
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FORBIDDEN_STYLE_CHARS = ("\u2014", "\u201c", "\u201d", "\u2018", "\u2019")


def _iter_repo_decisions(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("DECISIONS.md") if not (IGNORED_DIR_PARTS & set(p.parts))
    )


def _iter_harness_markdown(root: Path) -> list[Path]:
    files = [root / "AGENTS.md", root / "ARCHITECTURE.md"]
    docs_dir = root / "docs"
    if docs_dir.exists():
        files.extend(
            p for p in docs_dir.rglob("*.md") if not (IGNORED_DIR_PARTS & set(p.parts))
        )
    files.extend(_iter_repo_decisions(root))
    return sorted(set(files))


def find_unmigrated_completed_decisions(completed_dir: Path) -> list[str]:
    """检查已归档执行计划中的 Decision Log 条目是否均标明迁移去向或临时有效。"""
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


def test_required_harness_files_and_agents_budget():
    required_files = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "ARCHITECTURE.md",
        REPO_ROOT / "docs" / "design-docs" / "index.md",
        REPO_ROOT / "docs" / "design-docs" / "core-beliefs.md",
        REPO_ROOT / "docs" / "product-specs" / "index.md",
        REPO_ROOT / "docs" / "product-specs" / "document-qa-workbench.md",
        REPO_ROOT / "docs" / "exec-plans" / "tech-debt-tracker.md",
    ]
    for path in required_files:
        assert path.is_file(), f"缺少必需的 Harness 文档: {path.relative_to(REPO_ROOT)}"
    assert (REPO_ROOT / "docs" / "exec-plans" / "active").is_dir()
    assert (REPO_ROOT / "docs" / "exec-plans" / "completed").is_dir()

    agents_lines = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    assert len(agents_lines) <= 80, f"AGENTS.md 应保持精简总目录，当前 {len(agents_lines)} 行"


def test_harness_docs_and_decisions_links_and_style():
    broken: list[str] = []
    style_issues: list[str] = []
    for path in _iter_harness_markdown(REPO_ROOT):
        text = path.read_text(encoding="utf-8")
        hits = [ch for ch in FORBIDDEN_STYLE_CHARS if ch in text]
        if hits:
            style_issues.append(f"{path.relative_to(REPO_ROOT)}: {hits}")
        for match in LINK_RE.finditer(text):
            href = match.group(1).strip().split("#", 1)[0]
            if not href or href.startswith(("http://", "https://", "mailto:")):
                continue
            target = (path.parent / href).resolve()
            if not target.exists():
                broken.append(f"{path.relative_to(REPO_ROOT)} -> {href}")
    assert not broken, f"发现断链: {broken}"
    assert not style_issues, f"发现禁止标点（破折号/弯引号）: {style_issues}"


def test_all_module_decisions_indexed_in_design_index():
    design_index = REPO_ROOT / "docs" / "design-docs" / "index.md"
    index_text = design_index.read_text(encoding="utf-8")
    indexed_targets: set[Path] = set()
    for match in LINK_RE.finditer(index_text):
        href = match.group(1).strip().split("#", 1)[0]
        if not href or href.startswith(("http://", "https://", "mailto:")):
            continue
        indexed_targets.add((design_index.parent / href).resolve())

    all_decisions = _iter_repo_decisions(REPO_ROOT)
    assert all_decisions, "全仓应至少存在模块 DECISIONS.md"
    missing = [
        str(p.relative_to(REPO_ROOT))
        for p in all_decisions
        if p.resolve() not in indexed_targets
    ]
    assert not missing, f"以下模块 DECISIONS.md 未挂入 docs/design-docs/index.md: {missing}"


def test_completed_exec_plans_decision_graduation_gate(tmp_path: Path):
    completed = tmp_path / "completed"
    completed.mkdir()
    (completed / "good.md").write_text(
        "# 已完结计划\n\n## Decision Log\n"
        "- 2026-11-24：方案 A；原因：简单；排除：方案 B -> 已沉淀至 [DECISIONS.md](DECISIONS.md)\n"
        "- 2026-11-24：本次拆两次提交；原因：便于审阅；排除：单次大提交（仅本次施工临时有效）\n",
        encoding="utf-8",
    )
    assert find_unmigrated_completed_decisions(completed) == []

    (completed / "bad.md").write_text(
        "# 漏迁计划\n\n## Decision Log\n"
        "- 2026-11-24：方案 X；原因：快；排除：方案 Y\n",
        encoding="utf-8",
    )
    violations = find_unmigrated_completed_decisions(completed)
    assert len(violations) == 1
    assert violations[0].startswith("bad.md:4:")

    # 校验当前真实仓库的归档执行计划目录
    assert find_unmigrated_completed_decisions(REPO_ROOT / "docs" / "exec-plans" / "completed") == []
