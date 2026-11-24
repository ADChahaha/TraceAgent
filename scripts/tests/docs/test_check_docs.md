# 文档门禁脚本测试

验证 [scripts/check_docs.py](../../check_docs.py) 对仓库公开知识文档的完整性校验：

- `test_clean_repo_passes_and_ignores_local_memory_directory`：构造最小合规仓库，并额外放入被本地忽略的 `memory/` 与 `.agents/` 目录，验证校验全过且不误扫本地目录中的 `DECISIONS.md`。
- `test_detects_all_doc_violations_and_exits_nonzero`：注入缺失必需文件、坏链、缺失中文锚点、超行数预算、禁用破折号/弯引号、未挂总目的模块 `DECISIONS.md` 以及未标注去向的归档 `Decision Log`，验证全部检出且 CLI 返回退出码 1。
- `test_real_repository_docs_pass_audit`：对当前真实仓库执行 `python3 scripts/check_docs.py`，锁定所有门禁项全部清零。

运行：`conda run -n agent-gate python -m pytest scripts/tests/test_check_docs.py -q`。
