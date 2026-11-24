"""测试 memory/dream_scan.py 的健康检查、跨端会话扫描与 CLI 模式。"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "memory" / "dream_scan.py"


def load_dream_scan():
    if not SCRIPT_PATH.exists():
        pytest.fail(f"缺少目标脚本: {SCRIPT_PATH}")
    spec = importlib.util.spec_from_file_location("dream_scan", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_minimal_memory_repo(root: Path) -> None:
    (root / "AGENTS.md").write_text("# 协作说明\n\n入口见 [memory.md](memory.md)。\n", encoding="utf-8")
    (root / "memory" / "preference").mkdir(parents=True)
    (root / "memory" / "wiki").mkdir(parents=True)
    (root / "memory" / "notes").mkdir(parents=True)
    (root / "memory" / "tasks").mkdir(parents=True)
    (root / "memory" / "archive").mkdir(parents=True)
    (root / "memory" / "docs").mkdir(parents=True)
    (root / "memory" / "tests" / "docs").mkdir(parents=True)

    (root / "memory.md").write_text(
        "# 项目记忆\n\n"
        "- [协作偏好](memory/preference/workspace-preferences.md#沟通习惯)\n"
        "- [服务概览](memory/wiki/services.md)\n",
        encoding="utf-8",
    )
    (root / "memory" / "dream-log.md").write_text(
        "# Dreaming 记录\n\nlast_dream_at: 2026-11-20T10:00:00+08:00\n",
        encoding="utf-8",
    )
    (root / "memory" / "preference" / "workspace-preferences.md").write_text(
        "# 协作偏好\n\n## 沟通习惯\n\n保持简洁。\n",
        encoding="utf-8",
    )
    (root / "memory" / "wiki" / "services.md").write_text(
        "# 服务概览\n\n见 [部署细节](deploy-details.md)。\n",
        encoding="utf-8",
    )
    (root / "memory" / "wiki" / "deploy-details.md").write_text(
        "# 部署细节\n\n测试数据。\n",
        encoding="utf-8",
    )
    # 非活跃记忆目录不计入可达性图
    (root / "memory" / "notes" / "draft.md").write_text("# 草稿\n", encoding="utf-8")
    (root / "memory" / "tasks" / "todo.md").write_text("# 待办\n", encoding="utf-8")
    (root / "memory" / "archive" / "old.md").write_text("# 归档\n", encoding="utf-8")
    (root / "memory" / "docs" / "DESIGN.md").write_text("# 设计\n", encoding="utf-8")
    (root / "memory" / "tests" / "docs" / "test_dream_scan.md").write_text("# 测试说明\n", encoding="utf-8")


def test_check_memory_integrity_clean_repo_allows_direct_links(tmp_path: Path):
    ds = load_dream_scan()
    create_minimal_memory_repo(tmp_path)

    report = ds.check_memory_integrity(tmp_path)

    assert report["broken"] == []
    assert report["oversized_files"] == []
    assert report["unreachable_files"] == []
    assert report["max_depth"] == 2
    assert report["total_active_files"] == 4
    assert "layer_violations" not in report
    assert "crosslink_walls" not in report
    expected_hash = hashlib.sha256((tmp_path / "AGENTS.md").read_bytes()).hexdigest()[:12]
    assert report["protected_sha256_prefix"] == {"AGENTS.md": expected_hash}


def test_check_memory_integrity_detects_broken_oversized_and_unreachable(tmp_path: Path):
    ds = load_dream_scan()
    create_minimal_memory_repo(tmp_path)

    # 断链、缺失中文标题锚点，以及超过入口体积上限
    (tmp_path / "memory.md").write_text(
        "# 项目记忆\n\n"
        "- [协作偏好](memory/preference/workspace-preferences.md)\n"
        "- [服务概览](memory/wiki/services.md)\n"
        "- [缺失文件](memory/wiki/missing.md)\n"
        "- [缺失锚点](memory/preference/workspace-preferences.md#不存在标题)\n"
        + "a" * (ds.ENTRY_MAX_CHARS + 20)
        + "\n",
        encoding="utf-8",
    )
    # 同一行多个内部链接不再被当作互链墙违规
    (tmp_path / "memory" / "wiki" / "services.md").write_text(
        "# 服务概览\n\n"
        "[a](deploy-details.md) [b](deploy-details.md) [c](deploy-details.md) "
        "[d](deploy-details.md) [e](deploy-details.md) [f](deploy-details.md)\n",
        encoding="utf-8",
    )
    # notes 中的断链仍应被检出
    (tmp_path / "memory" / "notes" / "draft.md").write_text(
        "# 草稿\n\n见 [坏链](../wiki/gone.md)。\n",
        encoding="utf-8",
    )
    # 未从 memory.md 连出的孤岛文件
    (tmp_path / "memory" / "wiki" / "orphan.md").write_text("# 孤岛\n", encoding="utf-8")

    report = ds.check_memory_integrity(tmp_path)

    assert ("memory.md", "memory/wiki/missing.md", "missing_file") in report["broken"]
    assert (
        "memory.md",
        "memory/preference/workspace-preferences.md#不存在标题",
        "missing_anchor",
    ) in report["broken"]
    assert ("memory/notes/draft.md", "../wiki/gone.md", "missing_file") in report["broken"]
    assert any(item["file"] == "memory.md" for item in report["oversized_files"])
    assert report["unreachable_files"] == ["memory/wiki/orphan.md"]


def test_parse_last_dream_at_and_turn_spec(tmp_path: Path):
    ds = load_dream_scan()
    create_minimal_memory_repo(tmp_path)

    parsed = ds.parse_last_dream_at(tmp_path)
    assert parsed == dt.datetime.fromisoformat("2026-11-20T10:00:00+08:00")

    # 缺失 dream-log 时回退约 48 小时前
    (tmp_path / "memory" / "dream-log.md").unlink()
    fallback = ds.parse_last_dream_at(tmp_path)
    delta = dt.datetime.now(dt.timezone.utc) - fallback
    assert dt.timedelta(hours=47) <= delta <= dt.timedelta(hours=49)

    assert ds.parse_turn_spec("3,1,5-7,99,0", max_turn=6) == [1, 3, 5, 6]


def test_cross_tool_transcript_scanners_filter_repo_and_subagents(tmp_path: Path):
    ds = load_dream_scan()
    repo_root = tmp_path / "agent_gate"
    repo_root.mkdir()
    fake_home = tmp_path / "home"

    # 1. Antigravity: 一个主会话（含截断 USER 消息和子代理 ID）、一个被派生的子代理会话、一个无关仓库会话
    main_cid = "11111111-1111-1111-1111-111111111111"
    child_cid = "22222222-2222-2222-2222-222222222222"
    other_cid = "33333333-3333-3333-3333-333333333333"

    main_log_dir = fake_home / ".gemini/antigravity/brain" / main_cid / ".system_generated/logs"
    main_log_dir.mkdir(parents=True)
    (main_log_dir / "transcript.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "step_index": 1,
                        "type": "USER_INPUT",
                        "content": f"<USER_REQUEST>截断前缀 {repo_root}</USER_REQUEST><ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>",
                        "truncated_fields": ["content"],
                    }
                ),
                json.dumps(
                    {
                        "step_index": 2,
                        "type": "PLANNER_RESPONSE",
                        "content": "启动子代理",
                        "tool_calls": [{"name": "invoke_subagent", "result": f'{{"conversationId": "{child_cid}"}}'}],
                    }
                ),
                json.dumps(
                    {
                        "step_index": 3,
                        "type": "PLANNER_RESPONSE",
                        "content": "已完成 agent_gate 迁移。",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (main_log_dir / "transcript_full.jsonl").write_text(
        json.dumps(
            {
                "step_index": 1,
                "type": "USER_INPUT",
                "content": f"<USER_REQUEST>完整用户需求: 迁移 dreaming 到 {repo_root}</USER_REQUEST><ADDITIONAL_METADATA>m</ADDITIONAL_METADATA>",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    child_log_dir = fake_home / ".gemini/antigravity/brain" / child_cid / ".system_generated/logs"
    child_log_dir.mkdir(parents=True)
    (child_log_dir / "transcript.jsonl").write_text(
        json.dumps({"step_index": 1, "type": "USER_INPUT", "content": f"子任务 {repo_root}"}) + "\n",
        encoding="utf-8",
    )

    other_log_dir = fake_home / ".gemini/antigravity/brain" / other_cid / ".system_generated/logs"
    other_log_dir.mkdir(parents=True)
    (other_log_dir / "transcript.jsonl").write_text(
        json.dumps({"step_index": 1, "type": "USER_INPUT", "content": "unrelated project"}) + "\n",
        encoding="utf-8",
    )

    # 2. Codex: 主会话 + 子代理会话
    codex_dir = fake_home / ".codex/sessions/2026/11/24"
    codex_dir.mkdir(parents=True)
    (codex_dir / "rollout-main.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"cwd": str(repo_root)}}),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "# AGENTS.md injected"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "帮我检查 agent_gate 测试"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "全部测试通过。"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (codex_dir / "rollout-sub.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"cwd": str(repo_root), "source": {"subagent": "worker"}}}),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "subagent work"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # 3. Claude Code: 目录使用连字符 slug（-Users-x-agent-gate），含主会话和 sidechain
    claude_dir = fake_home / ".claude/projects/-Users-tester-agent-gate"
    claude_dir.mkdir(parents=True)
    (claude_dir / "session-a.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"content": "排查 backend SSE"}}),
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "已修复 SSE。"}]}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (claude_dir / "agent-side.jsonl").write_text(
        json.dumps({"type": "user", "isSidechain": True, "message": {"content": "sidechain task"}}) + "\n",
        encoding="utf-8",
    )

    # 验证默认跳过子代理且补全截断 USER 原文
    agy, agy_skip = ds.scan_agy(0.0, None, include_subagents=False, repo_root=repo_root, home=fake_home)
    assert len(agy) == 1
    assert agy_skip == 1
    assert agy[0]["session"] == main_cid
    assert agy[0]["msgs"][0] == ("USER", f"完整用户需求: 迁移 dreaming 到 {repo_root}")
    assert agy[0]["msgs"][1] == ("ASSISTANT", "已完成 agent_gate 迁移。")

    cdx, cdx_skip = ds.scan_codex(0.0, None, include_subagents=False, repo_root=repo_root, home=fake_home)
    assert len(cdx) == 1
    assert cdx_skip == 1
    assert cdx[0]["msgs"] == [("USER", "帮我检查 agent_gate 测试"), ("ASSISTANT", "全部测试通过。")]

    cld, cld_skip = ds.scan_claude(0.0, None, include_subagents=False, repo_root=repo_root, home=fake_home)
    assert len(cld) == 1
    assert cld_skip == 1
    assert cld[0]["msgs"] == [("USER", "排查 backend SSE"), ("ASSISTANT", "已修复 SSE。")]

    # 验证开启 include_subagents 时能收回全部子代理
    agy_all, _ = ds.scan_agy(0.0, None, include_subagents=True, repo_root=repo_root, home=fake_home)
    assert {s["session"] for s in agy_all} == {main_cid, child_cid}


def test_cli_audit_grep_and_session_turn_modes(tmp_path: Path):
    create_minimal_memory_repo(tmp_path)
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude/projects" / f"-tmp-{tmp_path.name.replace('_', '-')}"
    claude_dir.mkdir(parents=True)
    (claude_dir / "abc12345.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"content": "检查 Dreaming 链接"}}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "细节: " + "A" * 400}]},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ, HOME=str(fake_home))

    audit_res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(tmp_path), "--audit"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Links checked:" in audit_res.stdout
    assert "broken: []" in audit_res.stdout
    assert "Oversized files: 0 []" in audit_res.stdout
    assert "Unreachable files: []" in audit_res.stdout

    grep_res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(tmp_path), "--all", "--grep", "Dreaming"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "检查 Dreaming 链接" in grep_res.stdout
    assert "Hits returned: 1" in grep_res.stdout

    turn_res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(tmp_path), "--session", "abc12345", "--turn", "2"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "A" * 400 in turn_res.stdout


def test_real_repository_memory_audit_is_clean():
    ds = load_dream_scan()
    report = ds.check_memory_integrity(REPO_ROOT)

    assert report["broken"] == []
    assert report["oversized_files"] == []
    assert report["unreachable_files"] == []
    assert list(report["protected_sha256_prefix"].keys()) == ["AGENTS.md"]
    assert report["total_active_files"] >= 3
