"""构建实际 wheel，确认安装包包含解析、资源准备和问答模块。"""

from pathlib import Path
import subprocess
import shutil
import sys
import zipfile


def test_wheel_contains_resource_and_qa_modules(tmp_path):
    source = Path(__file__).resolve().parents[1]
    project = tmp_path / "source"
    project.mkdir()
    for folder in ("service", "routes"):
        shutil.copytree(source / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
    for filename in ("main.py", "pyproject.toml", "README.md"):
        shutil.copy2(source / filename, project / filename)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(tmp_path)],
        cwd=project, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        names = set(wheel.namelist())
        metadata = wheel.read(next(name for name in names if name.endswith(".dist-info/METADATA"))).decode()
    assert "Requires-Dist: traceagent-protocol" in metadata
    assert not any(name.startswith("agent_proto/") for name in names)
    assert {
        "routes/document_resources.py", "service/document_resources/resources.py",
        "service/document_resources/model.py", "service/document_resources/documents.py",
        "service/document_resources/index.py",
        "service/document_processor/docx/docx_processor.py", "service/file_extraction_agent/core/loop.py",
        "service/file_extraction_agent/core/tools/embedding.py",
        "service/file_extraction_agent/core/graph.py", "service/file_extraction_agent/turn_stream.py",
        "service/file_extraction_agent/core/messages.py", "service/file_extraction_agent/core/model_invocation.py",
        "service/file_extraction_agent/core/executor.py",
    } <= names
    assert "service/document_resources/search.py" not in names
    assert "routes/document_processor.py" not in names
    assert not any(name.startswith("service/file_extraction_agent/core/tools/embedding/") for name in names)


def test_generated_protocol_matches_source(tmp_path):
    """从 proto 重新生成绑定，确认提交的产物没有过期。"""
    source = Path(__file__).resolve().parents[2]
    assert (source / "agent_proto" / "agent.proto").is_file(), "协议必须位于 agent 同级目录"
    result = subprocess.run([
        sys.executable, "-m", "grpc_tools.protoc", "-I.",
        f"--python_out={tmp_path}", f"--pyi_out={tmp_path}", f"--grpc_python_out={tmp_path}",
        "agent_proto/agent.proto",
    ], cwd=source, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for filename in ("agent_pb2.py", "agent_pb2.pyi", "agent_pb2_grpc.py"):
        assert (tmp_path / "agent_proto" / filename).read_text(encoding="utf-8") == (
            source / "agent_proto" / filename).read_text(encoding="utf-8")


def test_shared_protocol_wheel_is_independent(tmp_path):
    """共享协议可独立构建并导入，后端使用时无需安装 agent 业务包。"""
    source = Path(__file__).resolve().parents[2] / "agent_proto"
    assert source.is_dir(), "共享协议包必须与 agent、backend 同级"
    project = tmp_path / "source"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(
        "__pycache__", "build", "*.egg-info"))
    result = subprocess.run([
        sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation",
        "-w", str(tmp_path),
    ], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    installed = tmp_path / "installed"
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        names = set(wheel.namelist())
        assert {"agent_proto/agent.proto", "agent_proto/agent_pb2.py",
                "agent_proto/agent_pb2.pyi", "agent_proto/agent_pb2_grpc.py"} <= names
        assert not any(name.startswith(("service/", "routes/", "backend/")) for name in names)
        metadata = wheel.read(next(name for name in names if name.endswith(".dist-info/METADATA"))).decode()
        assert "Requires-Dist: agent-service" not in metadata
        wheel.extractall(installed)
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "from agent_proto import agent_pb2, agent_pb2_grpc; "
        "assert Path(agent_pb2.__file__).is_relative_to(Path(sys.argv[1])); "
        "assert 'service' not in sys.modules and 'torch' not in sys.modules; "
        "assert agent_pb2.CompletionEvent(type='completion.completed').type == 'completion.completed'",
        str(installed),
    ], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
