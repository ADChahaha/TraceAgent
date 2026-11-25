"""仓库架构与代码质量机械门禁模块（文件行数上限、跨包/包内单向分层与依赖倒置检查）。"""

from scripts.arch_lint.rules import DEFAULT_MAX_LINES, Violation

__all__ = ["DEFAULT_MAX_LINES", "Violation"]
