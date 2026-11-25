"""测试 scripts/check_architecture.py：300 行门禁、顶层/包内分层、依赖倒置（DIP）与前端无环检查。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_architecture.py"


def load_linter():
    spec = importlib.util.spec_from_file_location("check_architecture", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_file_line_limit_flags_over_300_and_only_exempts_generated_pb2(tmp_path: Path):
    mod = load_linter()
    write(tmp_path, "backend/services/ok.py", "x = 1\n" * 300)
    write(tmp_path, "backend/services/too_long.py", "x = 1\n" * 301)
    write(tmp_path, "backend/services/test_pb2_adapter.py", "x = 1\n" * 305)
    write(tmp_path, "frontend/src/components/long.css", ".a {}\n" * 305)
    write(tmp_path, "agent_proto/agent_pb2.py", "x = 1\n" * 500)
    write(tmp_path, "agent_proto/agent_pb2_grpc.py", "x = 1\n" * 500)
    write(tmp_path, "node_modules/pkg/index.js", "const x = 1;\n" * 500)

    report = mod.check_architecture(tmp_path)
    flagged = {v.file for v in report["line_violations"]}
    assert flagged == {
        "backend/services/too_long.py",
        "backend/services/test_pb2_adapter.py",
        "frontend/src/components/long.css",
    }
    assert all(v.rule == "FILE_MAX_LINES" and "300" in v.fix for v in report["line_violations"])


def test_package_layer_and_backend_dip_rules_catch_absolute_and_relative_imports(tmp_path: Path):
    mod = load_linter()
    write(tmp_path, "agent/service/bad.py", "import document_service.routes\n")
    write(tmp_path, "backend/services/bad_pkg.py", "from storage.core import object_store\n")
    write(tmp_path, "backend/routes/chat.py", "from backend import crud\n")
    write(tmp_path, "backend/routes/rel.py", "from .. import crud\nfrom backend.core import db\n")
    write(tmp_path, "backend/crud/bad.py", "from backend.services import errors\n")
    write(
        tmp_path,
        "backend/services/bad_dip.py",
        "from . import agent_client\n"
        "from traceagent_shared.object_store import build_s3_object_store\n",
    )
    write(
        tmp_path,
        "backend/main.py",
        "from backend.services.agent_client import AgentClient\n"
        "from traceagent_shared.object_store import build_s3_object_store\n",
    )

    report = mod.check_architecture(tmp_path)
    rules_by_file: dict[str, set[str]] = {}
    for item in report["python_violations"]:
        rules_by_file.setdefault(item.file, set()).add(item.rule)

    assert "PACKAGE_LAYER" in rules_by_file["agent/service/bad.py"]
    assert "PACKAGE_LAYER" in rules_by_file["backend/services/bad_pkg.py"]
    assert "LAYER_BYPASS" in rules_by_file["backend/routes/chat.py"]
    assert "LAYER_BYPASS" in rules_by_file["backend/routes/rel.py"]
    assert "INTERNAL_LAYER" in rules_by_file["backend/crud/bad.py"]
    assert "DIP_CONCRETE_DEP" in rules_by_file["backend/services/bad_dip.py"]
    assert "backend/main.py" not in rules_by_file


def test_agent_and_document_service_dip_and_internal_layer_rules(tmp_path: Path):
    mod = load_linter()
    write(tmp_path, "agent/service/file_extraction_agent/core/graph.py", "from .model import build_qa_model\n")
    write(tmp_path, "document_service/document_resources/reader.py", "from document_service.document_resources import application\nfrom traceagent_shared.object_store import build_s3_object_store\n")
    write(tmp_path, "document_service/document_resources/documents.py", "from .. import routes\n")
    write(tmp_path, "document_service/routes.py", "import traceagent_shared.object_store as os_mod\nx = os_mod.build_s3_object_store\n")
    write(tmp_path, "document_service/main.py", "from traceagent_shared.object_store import build_s3_object_store\n")

    report = mod.check_architecture(tmp_path)
    flagged = {(v.file, v.rule) for v in report["python_violations"]}
    assert ("agent/service/file_extraction_agent/core/graph.py", "DIP_CONCRETE_DEP") in flagged
    assert ("document_service/document_resources/reader.py", "INTERNAL_LAYER") in flagged
    assert ("document_service/document_resources/reader.py", "DIP_CONCRETE_DEP") in flagged
    assert ("document_service/document_resources/documents.py", "INTERNAL_LAYER") in flagged
    assert ("document_service/routes.py", "DIP_CONCRETE_DEP") in flagged
    assert all(v.file != "document_service/main.py" for v in report["python_violations"])


def test_frontend_layer_cycle_dotted_names_side_effects_and_accurate_lines(tmp_path: Path):
    mod = load_linter()
    write(tmp_path, "frontend/src/lib/session-types.ts", '\nimport { x } from "@/lib/foo.client";\nexport type T = typeof x;\n')
    write(tmp_path, "frontend/src/lib/foo.client.ts", 'export const x = 1;\n')
    write(
        tmp_path,
        "frontend/src/lib/api.ts",
        'import "../components/a";\n'
        'export function copy() { return "from \'@/components/b\'"; }\n'
        'export const url = "http://127.0.0.1:8001";\n',
    )
    write(tmp_path, "frontend/src/components/a.tsx", 'import { B } from "@/components/../components/b";\nexport const A = B;\n')
    write(tmp_path, "frontend/src/components/b.tsx", 'import { A } from "./a";\nexport const B = A;\n')
    write(tmp_path, "frontend/src/components/ui/btn.tsx", 'import { x } from "@/lib/foo.client";\nexport const Btn = x;\n')

    report = mod.check_architecture(tmp_path)
    by_key = {(v.file, v.rule, v.line) for v in report["frontend_violations"]}
    assert ("frontend/src/lib/session-types.ts", "FRONTEND_LAYER", 2) in by_key
    assert ("frontend/src/lib/api.ts", "FRONTEND_LAYER", 1) in by_key
    assert ("frontend/src/lib/api.ts", "FRONTEND_BOUNDARY", 3) in by_key
    assert ("frontend/src/components/ui/btn.tsx", "FRONTEND_LAYER", 1) in by_key
    assert not any(v.file == "frontend/src/lib/api.ts" and v.line == 2 for v in report["frontend_violations"])
    assert any(v.rule == "FRONTEND_CYCLE" for v in report["frontend_violations"])


def test_real_repository_passes_architecture_and_line_limits():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Status: PASS (0 violations)" in result.stdout
