"""架构门禁声明式规则表：对齐 ARCHITECTURE.md 与 OpenAI Harness Engineering 分层/依赖倒置原则。"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_LINES = 300

CODE_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".css"})

IGNORED_DIR_PARTS = frozenset({
    ".git",
    ".agents",
    "memory",
    "experiments",
    "node_modules",
    ".next",
    "build",
    "dist",
    ".venv",
    "venv",
    ".pytest_cache",
    "__pycache__",
    ".pnpm-store",
})

# 仓库内所有顶层受管包及模块前缀（用于识别跨包 import）
REPO_TOP_MODULES = frozenset({
    "agent_proto",
    "shared",
    "traceagent_shared",
    "storage",
    "document_service",
    "agent",
    "service",
    "routes",
    "backend",
    "scripts",
})

# 顶层包允许导入的仓库内部模块前缀（与 ARCHITECTURE.md 4 层拓扑一一对应）
PACKAGE_ALLOWED_INTERNAL: dict[str, frozenset[str]] = {
    "agent_proto": frozenset({"agent_proto"}),
    "shared": frozenset({"shared", "traceagent_shared"}),
    "storage": frozenset({"storage", "traceagent_shared"}),
    "document_service": frozenset({"document_service", "agent_proto", "traceagent_shared"}),
    "agent": frozenset({"agent", "service", "routes", "agent_proto", "traceagent_shared"}),
    "backend": frozenset({"backend", "agent_proto", "traceagent_shared"}),
    "scripts": frozenset({"scripts", "traceagent_shared"}),
}

# 各包内固定分层序号（仅允许同层或向下层依赖；更高层禁止被低层反向导入）
BACKEND_LAYER_RANK = {
    "models": 0,
    "core": 1,
    "crud": 2,
    "protocols": 3,
    "services": 4,
    "routes": 5,
    "main": 6,
}

# backend 非适配器的业务服务模块禁止直接导入具体客户端实现或具体 S3 工厂（依赖倒置原则 DIP）
BACKEND_ADAPTER_FILES = frozenset({
    "backend/services/agent_client.py",
    "backend/services/document_client.py",
})
BACKEND_CONCRETE_CLIENTS = frozenset({
    "backend.services.agent_client",
    "backend.services.document_client",
})

# 禁止在非装配根业务层直接导入具体 S3 客户端或工厂（须经 ObjectStore Protocol 注入）
CONCRETE_OBJECT_STORE_SYMBOLS = frozenset({
    "S3ObjectStore",
    "build_s3_object_store",
})

# agent 包内纯核心编排层（只允许依赖 schemas 与 core.contracts，禁止依赖具体模型/工具/SDK）
AGENT_PURE_CORE_FILES = frozenset({
    "agent/service/file_extraction_agent/core/contracts.py",
    "agent/service/file_extraction_agent/core/messages.py",
    "agent/service/file_extraction_agent/core/executor.py",
    "agent/service/file_extraction_agent/core/model_invocation.py",
    "agent/service/file_extraction_agent/core/graph.py",
})

AGENT_LOOP_FILE = "agent/service/file_extraction_agent/core/loop.py"

AGENT_FORBIDDEN_CORE_TARGETS = (
    "service.file_extraction_agent.core.model",
    "service.file_extraction_agent.core.title",
    "service.file_extraction_agent.application",
    "routes",
    "openai",
    "traceagent_shared",
)

# document_service 包内核心与路由模块禁止直接导入具体 S3 工厂（须由 main.py 装配根注入）
DOCUMENT_SERVICE_COMPOSITION_ROOT = "document_service/main.py"

# 前端严禁直连后端以下内部服务端口
FRONTEND_FORBIDDEN_DIRECT_PORTS = (
    "127.0.0.1:8001",
    "localhost:8001",
    "127.0.0.1:8002",
    "localhost:8002",
    "127.0.0.1:9000",
    "localhost:9000",
)


@dataclass(frozen=True)
class Violation:
    """单条架构或行数门禁违规，附带面向人与 Agent 的可执行修复指引。"""

    rule: str
    file: str
    line: int | None
    message: str
    fix: str

    def format_line(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line is not None else self.file
        return f"[{self.rule}] {loc}: {self.message}\n  Fix: {self.fix}"
