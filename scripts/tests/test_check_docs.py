"""测试 scripts/check_docs.py 的文档骨架、链接锚点、模块 DECISIONS.md 收录、归档决策与忽略目录门禁。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_docs.py"


def load_check_docs():
    spec = importlib.util.spec_from_file_location("check_docs", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_minimal_repo(root: Path) -> None:
    (root / "docs" / "design-docs").mkdir(parents=True)
    (root / "docs" / "product-specs").mkdir(parents=True)
    (root / "docs" / "exec-plans" / "active").mkdir(parents=True)
    (root / "docs" / "exec-plans" / "completed").mkdir(parents=True)
    (root / "pkg" / "mod").mkdir(parents=True)

    (root / "AGENTS.md").write_text(
        "# 开发协作说明\n\n"
        "- [ARCHITECTURE.md](ARCHITECTURE.md)\n"
        "- [design-docs](docs/design-docs/index.md)\n"
        "- [product-specs](docs/product-specs/index.md)\n"
        "- [tech-debt](docs/exec-plans/tech-debt-tracker.md)\n",
        encoding="utf-8",
    )
    (root / "ARCHITECTURE.md").write_text(
        "# 架构\n\n见 [核心原则](docs/design-docs/core-beliefs.md#基本原则)。\n",
        encoding="utf-8",
    )
    (root / "docs" / "design-docs" / "index.md").write_text(
        "# 设计总目\n\n"
        "- [core-beliefs](core-beliefs.md)\n"
        "- [pkg/mod 决策](../../pkg/mod/DECISIONS.md)\n",
        encoding="utf-8",
    )
    (root / "docs" / "design-docs" / "core-beliefs.md").write_text(
        "# 核心原则\n\n## 基本原则\n\n保持简洁。\n",
        encoding="utf-8",
    )
    (root / "docs" / "product-specs" / "index.md").write_text("# 产品规格总目\n\n- 待补充\n", encoding="utf-8")
    (root / "docs" / "exec-plans" / "tech-debt-tracker.md").write_text("# 技术债台账\n\n无。\n", encoding="utf-8")
    (root / "docs" / "exec-plans" / "completed" / "done-plan.md").write_text(
        "# 已完结计划\n\n## Decision Log\n"
        "- 2026-11-25：采用方案 A；原因：简单；排除：方案 B -> [DECISIONS.md](../../../pkg/mod/DECISIONS.md)\n"
        "- 2026-11-25：拆两次提交；原因：易审阅；排除：单次大提交（仅本次临时有效）\n",
        encoding="utf-8",
    )
    (root / "pkg" / "mod" / "DECISIONS.md").write_text("# pkg/mod 关键决策\n\n- 决定：保持纯函数。\n", encoding="utf-8")


def test_clean_repo_passes_and_ignores_local_memory_directory(tmp_path: Path):
    mod = load_check_docs()
    create_minimal_repo(tmp_path)
    # 本地未提交的个人记忆目录即使含 DECISIONS.md 或坏链，也不应污染公开仓库门禁
    (tmp_path / "memory" / "docs").mkdir(parents=True)
    (tmp_path / "memory" / "docs" / "DECISIONS.md").write_text("# 本地记忆\n", encoding="utf-8")
    (tmp_path / ".agents" / "skills" / "dreaming").mkdir(parents=True)
    (tmp_path / ".agents" / "skills" / "dreaming" / "DECISIONS.md").write_text("# 本地技能\n", encoding="utf-8")

    report = mod.check_docs_integrity(tmp_path)

    assert not mod.has_violations(report)
    assert report["module_decisions"] == ["pkg/mod/DECISIONS.md"]


def test_detects_all_doc_violations_and_exits_nonzero(tmp_path: Path):
    mod = load_check_docs()
    create_minimal_repo(tmp_path)

    (tmp_path / "docs" / "product-specs" / "index.md").unlink()
    (tmp_path / "AGENTS.md").write_text(
        "# 开发协作说明\n\n"
        "- [缺失文件](docs/missing.md)\n"
        "- [缺失锚点](docs/design-docs/core-beliefs.md#不存在标题)\n"
        "- 含禁止破折号\u2014与弯引号\u201c示例\u201d\n"
        + "- 占位\n" * 80,
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "orphan").mkdir(parents=True)
    (tmp_path / "pkg" / "orphan" / "DECISIONS.md").write_text("# 孤岛决策\n", encoding="utf-8")
    (tmp_path / "docs" / "exec-plans" / "completed" / "bad-plan.md").write_text(
        "# 漏迁计划\n\n## Decision Log\n- 2026-11-25：方案 X；原因：快；排除：方案 Y\n",
        encoding="utf-8",
    )

    report = mod.check_docs_integrity(tmp_path)

    assert "docs/product-specs/index.md" in report["missing_required"]
    assert ("AGENTS.md", "docs/missing.md", "missing_file") in report["broken"]
    assert ("AGENTS.md", "docs/design-docs/core-beliefs.md#不存在标题", "missing_anchor") in report["broken"]
    assert report["unindexed_decisions"] == ["pkg/orphan/DECISIONS.md"]
    assert len(report["unmigrated_completed_decisions"]) == 1
    assert any(
        item["file"] == "AGENTS.md"
        and any("lines=" in reason for reason in item["reasons"])
        and any("forbidden_chars=" in reason for reason in item["reasons"])
        for item in report["budget_and_style_violations"]
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_real_repository_docs_pass_audit():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Missing required entries: []" in result.stdout
    assert "broken: []" in result.stdout
    assert "Unindexed `DECISIONS.md`: []" in result.stdout
    assert "Unmigrated completed decisions: []" in result.stdout
    assert "Budget & style violations: 0 []" in result.stdout
