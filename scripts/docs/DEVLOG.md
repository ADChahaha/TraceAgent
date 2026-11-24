# 脚本开发日志

## 2026-11-25

全仓配置从 `.env` 切换为单文件 `config.toml`：根目录新增模板 [config.example.toml](../../config.example.toml) 并在 `.gitignore` 忽略 `config.toml`；在 `shared/traceagent_shared/config.py` 新增基于 Python 3.11 标准库 `tomllib` 的统一配置读取器与 `--shell-exports` CLI；`scripts/start.sh`、`storage`、`shared`、`document_service`、`agent`、`backend` 与 `.github/workflows/ci.yml` 统一接入 `config.toml` 并移除运行态对 `.env` 的读取，保留显式进程环境变量覆盖能力。

拆离公开仓库文档门禁与个人本地记忆：新增 [scripts/check_docs.py](../check_docs.py) 与 [scripts/tests/test_check_docs.py](../tests/test_check_docs.py) 承接仓库级文档骨架、断链与中文锚点、全仓模块 `DECISIONS.md` 总目收录、归档计划决策迁出与文风预算检查（扫描时显式忽略 `.gitignore` 里的 `memory/`、`.agents/`、`experiments/` 与 `storage/data/`）；将 `memory/` 与 `.agents/` 加入 `.gitignore` 并以 `git rm -r --cached` 退出 Git 追踪，本地个人文件完好保留。

验证：`python3 scripts/check_docs.py` 清零（22 份知识文档、14 份模块 `DECISIONS.md`、111 条链接 0 断链）；`scripts/tests` 与 `.github/tests` 共 11 项全部通过。

## 2026-09-18

安装脚本原先没有安装 storage 和 embeddings 扩展依赖，导致服务虽可探活，文档索引生成却缺少运行时。现统一安装 storage、agent[dev,embeddings] 和 document_service[dev,embeddings]。

启动脚本在未配置外部 S3 地址时，先通过 `storage.main:create_app --factory` 启动本地 storage，再向各服务导出同一 endpoint。显式配置外部 S3 时复用外部服务。子进程通过 exec 启动，清理前移除信号 trap，避免停止脚本时只终止外层 shell 或重复清理。

回归测试先复现依赖遗漏、storage 未启动及退出清理失败，再验证安装参数、本地与外部 storage 模式、环境传递和进程退出。

本机补齐依赖并缓存默认 embedding 模型。真实上传最初因隐式携带 Hugging Face token 返回 401，在本项目 `.env` 关闭隐式 token 后，DOCX 上传成功生成 documents/index/raw 资源，OpenVINO 查询编码器的三项真实模型测试也全部通过。该本机配置不提交凭据。

验证：相关测试共 382 通过、5 跳过；模型缓存就绪后，单独重跑此前跳过的 OpenVINO 三项测试，全部通过。五个服务实际启动、探活、storage 写入读回及退出后端口释放均通过。现有环境的 `pip check` 仍报告 marker-pdf、dedoc 等已安装包的依赖冲突，未为消除这些报告改动无关包。

使用实际启动脚本、临时数据库和 storage 目录完成端到端验证：创建会话、上传合成 DOCX、真实 embedding 生成索引、读取文档目录、真实模型调用文档工具并回答、收到 turn.completed、resume 恢复答案。模型期间出现缺少终止信号的响应，现有重试机制恢复后完成。测试服务和临时业务数据均已清理；PDF/MinerU 链路未在本次实测。
