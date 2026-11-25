# 本地开发、测试与环境参考

归属 [AGENTS.md](../../AGENTS.md)，记录本仓库跨会话复用的本地启停、测试命令、环境避坑与文档审计入口。

## 安装、启停与探活

- Python 环境统一使用 Conda `agent-gate`（Python 3.11）；安装依赖并构建前端运行 [scripts/install.sh](../../scripts/install.sh)，一键启停 5 个本地服务运行 [scripts/start.sh](../../scripts/start.sh)（CI 见 [.github/workflows/ci.yml](../../.github/workflows/ci.yml) 与 [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)）。
- [scripts/start.sh](../../scripts/start.sh) 默认以生产模式启动（无 `--reload`，避免 watcher 高 CPU 引发卡顿）：修改 `backend`/`agent`/`document_service` Python 代码后须重启对应进程才生效；修改前端代码后须先重跑 `pnpm --dir frontend build` 再重启。
- `start.sh` 仅等待 1 秒校验进程存活，不阻塞等待服务就绪；打印 running 时 `document_service` 可能仍在后台预热 OpenVINO embedding 模型，需等探活通过后再发起上传。
- 探活口径：`backend` 为 `GET /healthz`（不是 `/health`）；`agent` 与 `document_service` 使用标准 gRPC Health（`python agent/main.py --check-health 127.0.0.1:8001` 与 `python -m document_service.main --check-health 127.0.0.1:8002`）。
- PDF 解析依赖 `mineru` CLI：在已激活 `agent-gate` 环境中代码通过 `shutil.which("mineru")` 自动定位，无需设置无意义的 `MINERU_BIN="mineru"`；仅在未激活环境通过子进程调用时需显式指定 `MINERU_BIN` 指向 `agent-gate/bin/mineru`。

## 本地测试、打包与门禁命令

- 仓库无根目录统一 `pyproject.toml`，各 Python 包独立声明依赖；代码直接 `import` 的库必须显式写入对应 `pyproject.toml`，不得依赖传递依赖（`agent` 由 `test_pyproject_dependencies.py` 校验）。`agent` 与 `document_service` 的 pytest 启用 `--import-mode=importlib` 避免同名测试模块冲突。
- 文档门禁、脚本与 CI 测试：`conda run -n agent-gate python -m pytest scripts/tests .github/tests -q`
- 业务包本地回环测试（显式绕开系统代理）：
  `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost conda run -n agent-gate python -m pytest <target_tests> -q`
- 调整包目录或拆分模块后，须运行 `agent/tests/test_packaging.py` 与 `document_service/tests/test_packaging.py` 校验实际 wheel 打包完整。
- 前端测试、Lint 与构建：`pnpm --dir frontend exec jest --runInBand`、`pnpm --dir frontend lint`、`pnpm --dir frontend build`（受限沙箱中 `next build` 会因端口绑定受限失败，须在非受限本机终端执行）。
- 前端运行时英文文案门禁：`frontend/src` 下所有 `.ts`/`.tsx` 非注释代码受 `frontend/tests/frontend-copy.test.ts` 校验禁止汉字字面量，需匹配中文的正则改用 Unicode 转义（如 `\u6765\u6e90`）。

## 工作目录、开发域名与提交防误脏

- 所有启停与测试命令统一从仓库根目录执行：`backend` 默认数据库为相对路径 `backend/backend.sqlite3`（对象存储在 `storage/data/`），若误在 `backend/` 子目录启动会连成嵌套空库 `backend/backend/backend.sqlite3`；执行清理或 Git 历史操作前先备份本地 `backend/backend.sqlite3`。
- 使用 `pnpm --dir frontend dev` 本地开发联调时须访问 `http://localhost:3000`；访问 `http://127.0.0.1:3000` 会因 `allowedDevOrigins` 不匹配导致 HMR WebSocket 异常并卡在加载态（`scripts/start.sh` 跑生产构建 `pnpm start`，无 HMR 限制）。
- `frontend/next-env.d.ts` 当前受 Git 跟踪，`next build` 与 `next dev` 会在开发/生产路径间自动改写该文件，提交前不要误暂存；同时保持 `memory/`、`.agents/`、`storage/data/`、`*.sqlite3` 与 `experiments/` 未跟踪，公开仓库禁止提交真实业务 PDF/DOCX 与大体积演示视频（详见 [document_processor/docs/DECISIONS.md](../../document_service/document_processor/docs/DECISIONS.md)）。
- 根 README 演示效果优先使用仓库内静态截图（`docs/assets/*.png`），不使用仓库相对路径 `<video>` 标签或 `img.shields.io` 远程 SVG。本机长期复用的 `agent-gate` 环境中，`pip check` 可能报告历史遗留非主链路包（如 `marker-pdf`、`dedoc`）冲突，不阻断 5 服务运行。

## 代理、模型端点与文档门禁

- 本机开启代理时，`curl` 调本地端口加 `--noproxy '*'`；调用模型 API 若报 `httpx.RemoteProtocolError` 或 `openai.APIConnectionError` 且堆栈经过 `httpcore/_sync/http_proxy.py`，用 `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy` 清代理直连重试。
- Hugging Face 公开模型下载若因本机隐式 token 报 401，在根目录 `config.toml` 的 `[huggingface]` 中设 `disable_implicit_token = true`（或显式设环境变量 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`）。
- 全仓配置统一从仓库根目录 `config.toml` 读取（模板见 [config.example.toml](../../config.example.toml)，可通过 `TRACEAGENT_CONFIG` 指定路径），优先级为代码默认值 < `config.toml` < 进程 `os.environ`；运行态不再读取 `.env`；改 `config.toml` 未生效时先检查 shell 是否残留导出过的旧 `BASE_URL`/`MODEL`/`OPENAI_API_KEY`。
- OpenAI 兼容端点接入：
  - `BASE_URL` 必须带完整 `/v1` 后缀，缺少时部分网关返回 HTML 页面。
  - 切新中转站前先做最小流式 tool-calling 探针（部分网关缺通道报 `503 model_not_found` 或触发 WAF `403`）。
  - 生产固定 `streaming=True`（部分端点非流式 tool call 会返回裸 SSE 字符串）。
  - 已移除 DeepSeek `thinking` / `reasoning_content` 专有适配，接入默认开启思考模式的 DeepSeek 端点会因未回传 `reasoning_content` 报 400。
  - 多上游轮询且无通道粘性的中转代理会导致 Prompt Cache 命中恒为 0。
- 仓库知识文档门禁：`python3 scripts/check_docs.py`（校验必需骨架、链接锚点、模块 `DECISIONS.md` 收录、归档计划决策迁出与文风预算，回归测试见 `scripts/tests/test_check_docs.py`）。
- 仓库架构与 300 行上限门禁：`python3 scripts/check_architecture.py`（校验全仓非忽略手写文件 <= 300 行、顶层 7 包单向分层、包内分层与依赖倒置原则、前端单向分层与零循环依赖，回归测试见 `scripts/tests/test_check_architecture.py`，CI 前置 job `repo-gates` 同步执行）。
