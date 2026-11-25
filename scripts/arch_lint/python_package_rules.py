"""单包内部固定分层与依赖倒置（DIP）规则实现（backend / agent / document_service）。"""

from __future__ import annotations

from pathlib import Path

from scripts.arch_lint.rules import (
    AGENT_FORBIDDEN_CORE_TARGETS,
    AGENT_LOOP_FILE,
    AGENT_PURE_CORE_FILES,
    BACKEND_ADAPTER_FILES,
    BACKEND_CONCRETE_CLIENTS,
    BACKEND_LAYER_RANK,
    CONCRETE_OBJECT_STORE_SYMBOLS,
    DOCUMENT_SERVICE_COMPOSITION_ROOT,
    Violation,
)

DOC_RES_LAYER_RANK = {
    "schemas": 0,
    "protocols": 1,
    "domain": 2,
    "application": 3,
    "routes": 4,
    "main": 5,
}
DOC_RES_DOMAIN_MODULES = frozenset({"documents", "html_tree", "index", "model", "resources", "reader"})


def expanded_targets(module: str, names: list[str]) -> list[str]:
    """展开 `from pkg import submod` 为 `[pkg, pkg.submod]`，防止绕过子模块分层/DIP 检查。"""
    targets = [module]
    for name in names:
        if name != "*":
            targets.append(f"{module}.{name}")
    return targets


def _backend_layer(rel: str) -> str | None:
    parts = Path(rel).parts
    if len(parts) < 2 or parts[0] != "backend" or "tests" in parts:
        return None
    if rel == "backend/main.py":
        return "main"
    if rel == "backend/services/protocols.py":
        return "protocols"
    return parts[1] if parts[1] in BACKEND_LAYER_RANK else None


def _backend_target_layer(module: str) -> str | None:
    if not module.startswith("backend."):
        return None
    if module == "backend.main":
        return "main"
    if module == "backend.services.protocols":
        return "protocols"
    parts = module.split(".")
    return parts[1] if len(parts) >= 2 and parts[1] in BACKEND_LAYER_RANK else None


def check_backend_file(
    rel: str,
    imports: list[tuple[int, str, list[str]]],
    concrete_attrs: list[tuple[int, str]],
) -> list[Violation]:
    violations: list[Violation] = []
    src_layer = _backend_layer(rel)
    if src_layer is None:
        return violations

    for lineno, module, names in imports:
        for target in expanded_targets(module, names):
            target_layer = _backend_target_layer(target)
            if target_layer is not None:
                if BACKEND_LAYER_RANK[target_layer] > BACKEND_LAYER_RANK[src_layer]:
                    violations.append(
                        Violation(
                            rule="INTERNAL_LAYER",
                            file=rel,
                            line=lineno,
                            message=f"backend layer '{src_layer}' must not depend on higher layer '{target_layer}' ({target})",
                            fix="遵循单向分层 models -> core -> crud -> protocols -> services -> routes -> main；如需反向协作请在 protocols.py 定义抽象并由 main.py 注入。",
                        )
                    )
                if (src_layer == "routes" and target_layer in {"crud", "models"}) or (
                    src_layer == "routes" and (target == "backend.core.db" or target.startswith("backend.core.db."))
                ):
                    violations.append(
                        Violation(
                            rule="LAYER_BYPASS",
                            file=rel,
                            line=lineno,
                            message=f"backend route must not bypass services to import '{target}'",
                            fix="在 backend/services/ 提供用例函数或服务方法供 routes 调用，禁止 HTTP 路由直连 crud 或数据库模块。",
                        )
                    )
            if src_layer in {"services", "routes", "protocols"} and rel not in BACKEND_ADAPTER_FILES:
                if target in BACKEND_CONCRETE_CLIENTS:
                    violations.append(
                        Violation(
                            rule="DIP_CONCRETE_DEP",
                            file=rel,
                            line=lineno,
                            message=f"'{rel}' imports concrete transport adapter '{target}'",
                            fix="改依赖 backend.services.protocols 中的 AgentGateway / DocumentGateway 抽象协议，具体客户端仅在 backend/main.py 装配注入。",
                        )
                    )
        if src_layer in {"services", "routes", "protocols"} and rel not in BACKEND_ADAPTER_FILES:
            if module == "traceagent_shared.object_store" and (CONCRETE_OBJECT_STORE_SYMBOLS & set(names)):
                bad = ", ".join(sorted(CONCRETE_OBJECT_STORE_SYMBOLS & set(names)))
                violations.append(
                    Violation(
                        rule="DIP_CONCRETE_DEP",
                        file=rel,
                        line=lineno,
                        message=f"'{rel}' imports concrete object store symbol(s): {bad}",
                        fix="业务与路由层只依赖 ObjectStore Protocol，具体 S3ObjectStore/build_s3_object_store 须在 backend/main.py 装配根注入。",
                    )
                )

    if rel != "backend/main.py" and src_layer in {"services", "routes", "protocols"}:
        for lineno, sym in concrete_attrs:
            violations.append(
                Violation(
                    rule="DIP_CONCRETE_DEP",
                    file=rel,
                    line=lineno,
                    message=f"'{rel}' references concrete object store symbol '{sym}'",
                    fix="业务与路由层只依赖 ObjectStore Protocol，具体 S3ObjectStore/build_s3_object_store 须在 backend/main.py 装配根注入。",
                )
            )
    return violations


def _strip_agent_prefix(target: str) -> str:
    return target[len("agent.") :] if target.startswith("agent.") else target


def check_agent_file(rel: str, imports: list[tuple[int, str, list[str]]]) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, module, names in imports:
        for raw_target in expanded_targets(module, names):
            target = _strip_agent_prefix(raw_target)
            if rel == "agent/service/file_extraction_agent/schemas.py":
                if target.startswith(("service.file_extraction_agent.core", "service.file_extraction_agent.application", "routes")):
                    violations.append(
                        Violation(
                            rule="INTERNAL_LAYER",
                            file=rel,
                            line=lineno,
                            message=f"agent schemas must remain dependency-free, found '{target}'",
                            fix="将纯数据结构留在 schemas.py，不要反向依赖 core、application 或 routes。",
                        )
                    )
            if rel in AGENT_PURE_CORE_FILES or rel == AGENT_LOOP_FILE:
                forbidden = AGENT_FORBIDDEN_CORE_TARGETS + (
                    ("service.file_extraction_agent.core.tools",) if rel in AGENT_PURE_CORE_FILES else ()
                )
                if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(
                        Violation(
                            rule="DIP_CONCRETE_DEP",
                            file=rel,
                            line=lineno,
                            message=f"agent core module '{rel}' must not depend on concrete/outer module '{target}'",
                            fix="核心编排层只依赖 service.file_extraction_agent.core.contracts 抽象协议与 schemas，具体模型/工具/传输实现由 application.py 或 main.py 注入。",
                        )
                    )
            if rel.startswith("agent/service/"):
                if target == "routes" or target.startswith("routes.") or target == "main":
                    violations.append(
                        Violation(
                            rule="INTERNAL_LAYER",
                            file=rel,
                            line=lineno,
                            message=f"agent service layer must not depend on transport layer '{target}'",
                            fix="保持依赖方向 schemas -> core -> application -> routes -> main，不要在 service 层反向导入 routes。",
                        )
                    )
    return violations


def _doc_service_layer(rel: str) -> str | None:
    if rel == "document_service/main.py":
        return "main"
    if rel == "document_service/routes.py":
        return "routes"
    if rel.startswith("document_service/document_resources/"):
        stem = Path(rel).stem
        if stem in {"schemas", "protocols", "application"}:
            return stem
        if stem in DOC_RES_DOMAIN_MODULES:
            return "domain"
    return None


def _doc_target_layer(target: str) -> str | None:
    if target == "document_service.main":
        return "main"
    if target == "document_service.routes":
        return "routes"
    if target.startswith("document_service.document_resources."):
        sub = target.split(".")[2]
        if sub in {"schemas", "protocols", "application"}:
            return sub
        if sub in DOC_RES_DOMAIN_MODULES:
            return "domain"
    return None


def check_document_service_file(
    rel: str,
    imports: list[tuple[int, str, list[str]]],
    concrete_attrs: list[tuple[int, str]],
) -> list[Violation]:
    violations: list[Violation] = []
    if rel == DOCUMENT_SERVICE_COMPOSITION_ROOT or "tests" in Path(rel).parts:
        return violations
    src_layer = _doc_service_layer(rel)
    for lineno, module, names in imports:
        for target in expanded_targets(module, names):
            if rel.startswith("document_service/document_processor/") and target.startswith(
                ("document_service.document_resources", "document_service.routes", "document_service.main")
            ):
                violations.append(
                    Violation(
                        rule="INTERNAL_LAYER",
                        file=rel,
                        line=lineno,
                        message=f"document_processor must not depend on '{target}'",
                        fix="保持 document_processor 独立于 document_resources 与 gRPC 路由层。",
                    )
                )
            target_layer = _doc_target_layer(target)
            if src_layer is not None and target_layer is not None:
                if DOC_RES_LAYER_RANK[target_layer] > DOC_RES_LAYER_RANK[src_layer]:
                    violations.append(
                        Violation(
                            rule="INTERNAL_LAYER",
                            file=rel,
                            line=lineno,
                            message=f"document_service layer '{src_layer}' must not depend on higher layer '{target_layer}' ({target})",
                            fix="遵循单向分层 schemas -> protocols -> domain(documents/index/resources/reader) -> application -> routes -> main。",
                        )
                    )
        if module == "traceagent_shared.object_store" and (CONCRETE_OBJECT_STORE_SYMBOLS & set(names)):
            bad = ", ".join(sorted(CONCRETE_OBJECT_STORE_SYMBOLS & set(names)))
            violations.append(
                Violation(
                    rule="DIP_CONCRETE_DEP",
                    file=rel,
                    line=lineno,
                    message=f"'{rel}' imports concrete object store symbol(s): {bad}",
                    fix="document_service 业务与路由模块只依赖 ObjectStore Protocol / ObjectStoreFactory，具体 build_s3_object_store 仅在 document_service/main.py 装配注入。",
                )
            )
    for lineno, sym in concrete_attrs:
        violations.append(
            Violation(
                rule="DIP_CONCRETE_DEP",
                file=rel,
                line=lineno,
                message=f"'{rel}' references concrete object store symbol '{sym}'",
                fix="document_service 业务与路由模块只依赖 ObjectStore Protocol / ObjectStoreFactory，具体 build_s3_object_store 仅在 document_service/main.py 装配注入。",
            )
        )
    return violations
