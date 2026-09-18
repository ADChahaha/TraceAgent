# 脚本开发日志

## 2026-09-18

安装脚本原先没有安装 storage 和 embeddings 扩展依赖，导致服务虽可探活，文档索引生成却缺少运行时。现统一安装 storage、agent[dev,embeddings] 和 document_service[dev,embeddings]。

启动脚本在未配置外部 S3 地址时，先通过 `storage.main:create_app --factory` 启动本地 storage，再向各服务导出同一 endpoint。显式配置外部 S3 时复用外部服务。子进程通过 exec 启动，清理前移除信号 trap，避免停止脚本时只终止外层 shell 或重复清理。

回归测试先复现依赖遗漏、storage 未启动及退出清理失败，再验证安装参数、本地与外部 storage 模式、环境传递和进程退出。

本机补齐依赖并缓存默认 embedding 模型。真实上传最初因隐式携带 Hugging Face token 返回 401，在本项目 `.env` 关闭隐式 token 后，DOCX 上传成功生成 documents/index/raw 资源，OpenVINO 查询编码器的三项真实模型测试也全部通过。该本机配置不提交凭据。

验证：相关测试共 382 通过、5 跳过；模型缓存就绪后，单独重跑此前跳过的 OpenVINO 三项测试，全部通过。五个服务实际启动、探活、storage 写入读回及退出后端口释放均通过。现有环境的 `pip check` 仍报告 marker-pdf、dedoc 等已安装包的依赖冲突，未为消除这些报告改动无关包。

使用实际启动脚本、临时数据库和 storage 目录完成端到端验证：创建会话、上传合成 DOCX、真实 embedding 生成索引、读取文档目录、真实模型调用文档工具并回答、收到 turn.completed、resume 恢复答案。模型期间出现缺少终止信号的响应，现有重试机制恢复后完成。测试服务和临时业务数据均已清理；PDF/MinerU 链路未在本次实测。
