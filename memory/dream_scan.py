#!/usr/bin/env python3
"""只读 Dreaming 会话扫描器与记忆健康检查脚本。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_FILES = ["AGENTS.md"]
ENTRY_MAX_CHARS = 2500
PAGE_MAX_CHARS = 4500

AGY_SPAWN_ID_RE = re.compile(
    r"(?:\\?\"conversationId\\?\":\s*\\?\"|\b(?:done|error)\s*\(|failed to run agent \\?\")"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def _resolve_repo_root(repo_root: Path | None) -> Path:
    return (repo_root or REPO_ROOT).resolve()


def _resolve_home(home: Path | None) -> Path:
    return (home or Path.home()).resolve()


def _collect_agy_child_ids(brain: Path) -> set[str]:
    """从父会话日志中识别 Antigravity 派生的子代理与 workflow 会话 ID。"""
    child_ids: set[str] = set()
    for p in brain.glob("*/.system_generated/steps/*/output.txt"):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if 'Workflow "' in txt or "[agent:" in txt or "conversationId" in txt:
            child_ids.update(AGY_SPAWN_ID_RE.findall(txt))
    for t in brain.glob("*/.system_generated/logs/transcript.jsonl"):
        own = t.parent.parent.parent.name
        txt = t.read_text(encoding="utf-8", errors="ignore")
        if "invoke_subagent" in txt or "run_workflow" in txt:
            for cid in AGY_SPAWN_ID_RE.findall(txt):
                if cid != own:
                    child_ids.add(cid)
    return child_ids


def parse_last_dream_at(repo_root: Path | None = None) -> dt.datetime:
    root = _resolve_repo_root(repo_root)
    dream_log = root / "memory" / "dream-log.md"
    if dream_log.exists():
        m = re.search(r"last_dream_at:\s*([0-9T:+-]+)", dream_log.read_text(encoding="utf-8"))
        if m:
            try:
                return dt.datetime.fromisoformat(m.group(1))
            except ValueError:
                pass
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)


def clip(text: str, limit: int = 240) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def clip_match(text: str, pattern: re.Pattern[str], limit: int = 320) -> str:
    """返回以首个正则命中为中心的紧凑片段。"""
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    m = pattern.search(clean)
    if not m:
        return clip(clean, limit)
    half = limit // 2
    center = (m.start() + m.end()) // 2
    start = max(0, center - half)
    end = min(len(clean), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean) else ""
    return f"{prefix}{clean[start:end]}{suffix}"


def _clean_agy_user_text(content: str) -> str:
    inner = re.sub(r"<ADDITIONAL_METADATA>.*", "", content, flags=re.S)
    inner = re.sub(r"</?USER_REQUEST>", "", inner).strip()
    return inner


def _load_agy_full_content(full_path: Path) -> dict[int, str]:
    """仅在用户文本截断或窄范围展开时按 step_index 读取完整正文。"""
    full_map: dict[int, str] = {}
    if not full_path.exists():
        return full_map
    with full_path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            step_idx = obj.get("step_index")
            content = obj.get("content")
            if isinstance(step_idx, int) and isinstance(content, str):
                full_map[step_idx] = content
    return full_map


def _matches_repo_line(line: str, root: Path) -> bool:
    return str(root) in line or root.name in line


def scan_agy(
    since_ts: float,
    until_ts: float | None,
    include_subagents: bool,
    session_filter: str | None = None,
    need_full_text: bool = False,
    repo_root: Path | None = None,
    home: Path | None = None,
) -> tuple[list[dict], int]:
    root = _resolve_repo_root(repo_root)
    base_home = _resolve_home(home)
    results = []
    skipped_subagents = 0
    brain = base_home / ".gemini/antigravity/brain"
    if not brain.exists():
        return results, skipped_subagents
    child_ids = _collect_agy_child_ids(brain) if not session_filter else set()
    for t in sorted(brain.glob("*/.system_generated/logs/transcript.jsonl")):
        cid = t.parent.parent.parent.name
        if session_filter and session_filter.lower() not in cid.lower():
            continue
        mtime = t.stat().st_mtime
        if mtime <= since_ts:
            continue
        if until_ts is not None and mtime > until_ts:
            continue

        matched_repo = False
        raw_turns: list[tuple[str, str, bool, int | None, bool]] = []
        with t.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not matched_repo and _matches_repo_line(line, root):
                    matched_repo = True
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                typ = obj.get("type")
                content = obj.get("content", "")
                truncated = "content" in (obj.get("truncated_fields") or [])
                step_idx = obj.get("step_index")
                if typ == "USER_INPUT" and isinstance(content, str):
                    inner = _clean_agy_user_text(content)
                    if inner:
                        raw_turns.append(("USER", inner, False, step_idx, truncated))
                elif typ == "PLANNER_RESPONSE" and isinstance(content, str) and content.strip():
                    is_final = not obj.get("tool_calls")
                    raw_turns.append(("ASSISTANT", content.strip(), is_final, step_idx, truncated))

        if not matched_repo:
            continue

        full_map: dict[int, str] | None = None
        has_truncated_user = any(role == "USER" and tr for role, _, _, _, tr in raw_turns)
        if (need_full_text or has_truncated_user) and any(tr for _, _, _, _, tr in raw_turns):
            full_map = _load_agy_full_content(t.with_name("transcript_full.jsonl"))

        msgs: list[tuple[str, str]] = []
        all_msgs: list[tuple[str, str]] = []
        user_count = 0
        for role, text, is_final, step_idx, truncated in raw_turns:
            if full_map is not None and truncated and step_idx in full_map:
                text = _clean_agy_user_text(full_map[step_idx]) if role == "USER" else full_map[step_idx].strip()
            if not text:
                continue
            if role == "USER":
                user_count += 1
                msgs.append((role, text))
                all_msgs.append((role, text))
            else:
                all_msgs.append((role, text))
                if is_final:
                    msgs.append((role, text))

        if not (msgs or all_msgs):
            continue
        is_subagent = (cid in child_ids) or (user_count == 0)
        if not include_subagents and not session_filter and is_subagent:
            skipped_subagents += 1
            continue
        results.append(
            {
                "tool": "antigravity",
                "session": cid,
                "mtime": mtime,
                "is_subagent": is_subagent,
                "msgs": msgs,
                "all_msgs": all_msgs,
            }
        )
    return results, skipped_subagents


def scan_codex(
    since_ts: float,
    until_ts: float | None,
    include_subagents: bool,
    session_filter: str | None = None,
    repo_root: Path | None = None,
    home: Path | None = None,
) -> tuple[list[dict], int]:
    root = _resolve_repo_root(repo_root)
    base_home = _resolve_home(home)
    results = []
    skipped_subagents = 0
    cs = base_home / ".codex/sessions"
    if not cs.exists():
        return results, skipped_subagents
    root_str = str(root)
    for jf in sorted(cs.rglob("*.jsonl")):
        if session_filter and session_filter.lower() not in jf.name.lower():
            continue
        mtime = jf.stat().st_mtime
        if mtime <= since_ts:
            continue
        if until_ts is not None and mtime > until_ts:
            continue

        matched_cwd = False
        codex_subagent = False
        msgs: list[tuple[str, str]] = []
        user_count = 0
        with jf.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not matched_cwd and _matches_repo_line(line, root):
                    matched_cwd = True
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type")
                p = obj.get("payload", {})
                if t == "session_meta" and isinstance(p, dict):
                    cwd = p.get("cwd", "")
                    if isinstance(cwd, str) and (cwd == root_str or cwd.startswith(root_str + "/")):
                        matched_cwd = True
                    src = p.get("source")
                    if isinstance(src, dict) and "subagent" in src:
                        codex_subagent = True
                if t == "response_item" and isinstance(p, dict) and p.get("type") == "message":
                    role = p.get("role")
                    if role in ("user", "assistant"):
                        parts = [
                            c.get("text", "")
                            for c in p.get("content", [])
                            if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")
                        ]
                        txt = " ".join(parts).strip()
                        if not txt or txt.startswith(
                            (
                                "# AGENTS.md",
                                "<environment_context>",
                                "<permissions",
                                "<skill>",
                                "<INSTRUCTIONS>",
                                "Side conversation boundary.",
                            )
                        ):
                            continue
                        if role == "user":
                            user_count += 1
                        msgs.append((role.upper(), txt))
        if not (matched_cwd and msgs):
            continue
        is_subagent = codex_subagent or (user_count == 0)
        if not include_subagents and not session_filter and is_subagent:
            skipped_subagents += 1
            continue
        results.append(
            {
                "tool": "codex",
                "session": jf.name,
                "mtime": mtime,
                "is_subagent": is_subagent,
                "msgs": msgs,
                "all_msgs": msgs,
            }
        )
    return results, skipped_subagents


def scan_claude(
    since_ts: float,
    until_ts: float | None,
    include_subagents: bool,
    session_filter: str | None = None,
    repo_root: Path | None = None,
    home: Path | None = None,
) -> tuple[list[dict], int]:
    root = _resolve_repo_root(repo_root)
    base_home = _resolve_home(home)
    results = []
    skipped_subagents = 0
    cp = base_home / ".claude/projects"
    if not cp.exists():
        return results, skipped_subagents
    repo_name_lower = root.name.lower()
    repo_slug = repo_name_lower.replace("_", "-")
    for d in sorted(cp.iterdir()):
        d_lower = d.name.lower()
        if not d.is_dir() or (repo_slug not in d_lower and repo_name_lower not in d_lower):
            continue
        for jf in sorted(d.glob("*.jsonl")):
            if session_filter and session_filter.lower() not in jf.name.lower():
                continue
            mtime = jf.stat().st_mtime
            if mtime <= since_ts:
                continue
            if until_ts is not None and mtime > until_ts:
                continue
            msgs: list[tuple[str, str]] = []
            user_count = 0
            claude_sidechain = jf.name.startswith("agent-")
            with jf.open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("isSidechain"):
                        claude_sidechain = True
                    t = obj.get("type")
                    if t == "user":
                        if obj.get("isMeta"):
                            continue
                        c = obj.get("message", {}).get("content", "")
                        if isinstance(c, list):
                            parts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
                            txt = " ".join(parts).strip()
                        elif isinstance(c, str):
                            txt = c.strip()
                        else:
                            txt = ""
                        if txt and txt != "[Request interrupted by user]":
                            user_count += 1
                            msgs.append(("USER", txt))
                    elif t == "assistant":
                        c = obj.get("message", {}).get("content", [])
                        if isinstance(c, list):
                            texts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
                            txt = " ".join(texts).strip()
                            if txt:
                                msgs.append(("ASSISTANT", txt))
            if not msgs:
                continue
            is_subagent = claude_sidechain or (user_count == 0)
            if not include_subagents and not session_filter and is_subagent:
                skipped_subagents += 1
                continue
            results.append(
                {
                    "tool": "claude",
                    "session": jf.name,
                    "mtime": mtime,
                    "is_subagent": is_subagent,
                    "msgs": msgs,
                    "all_msgs": msgs,
                }
            )
    return results, skipped_subagents


def parse_turn_spec(spec: str, max_turn: int) -> list[int]:
    """解析轮次选择器（如 '33'、'15,33'、'14-18'）为排序后的 1 基索引列表。"""
    turns: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a_str, b_str = part.split("-", 1)
            a, b = int(a_str), int(b_str)
            lo, hi = min(a, b), max(a, b)
            for n in range(max(1, lo), min(max_turn, hi) + 1):
                turns.add(n)
        else:
            n = int(part)
            if 1 <= n <= max_turn:
                turns.add(n)
    return sorted(turns)


def _format_compact_turns(
    session: dict,
    selected: list[tuple[int, str, str]],
    assistant_limit: int,
    short_id: str,
) -> str:
    """格式化单会话摘要：USER 全文保留，ASSISTANT 截断并附带 --turn 展开命令。"""
    tstr = dt.datetime.fromtimestamp(session["mtime"]).strftime("%Y-%m-%d %H:%M")
    turns = session["msgs"]
    tag = " [subagent]" if session["is_subagent"] else ""
    lines = [f"\n### [{session['tool']}{tag}] `{session['session']}` ({tstr}, {len(turns)} msgs)"]
    has_truncated_assistant = False
    for num, role, txt in selected:
        clean = " ".join(txt.split())
        if role == "USER":
            lines.append(f"- `#{num}` **USER**: {clean}")
        elif len(clean) > assistant_limit:
            has_truncated_assistant = True
            shown = clip(clean, assistant_limit)
            lines.append(f"- `#{num}` **ASSISTANT** ({assistant_limit}/{len(clean)}c): {shown}")
        else:
            lines.append(f"- `#{num}` **ASSISTANT**: {clean}")
    if has_truncated_assistant:
        lines.append(
            f"  > Hook (full reply): `python3 memory/dream_scan.py --session {short_id} --turn <N[,M]|start-end>`"
        )
    return "\n".join(lines)


def gfm_slug(text: str) -> str:
    out = []
    for ch in text.strip().lower():
        if ch in (" ", "-"):
            out.append("-")
        elif ch.isalnum() or ch == "_":
            out.append(ch)
    return "".join(out)


def list_rel_md(subdir: Path) -> list[str]:
    return [str(p.relative_to(subdir)) for p in sorted(subdir.rglob("*.md"))] if subdir.exists() else []


def _is_active_memory(rel: str) -> bool:
    return rel == "memory.md" or rel.startswith(("memory/wiki/", "memory/preference/"))


def _resolve_internal_md(src: Path, target: str, repo_root: Path) -> str | None:
    if target.startswith(("http://", "https://", "/")):
        return None
    path_part, _, _ = target.partition("#")
    p = (src.parent / urllib.parse.unquote(path_part)).resolve() if path_part else src.resolve()
    try:
        rel = p.relative_to(repo_root).as_posix()
    except ValueError:
        return None
    if _is_active_memory(rel):
        return rel
    return None


def check_memory_integrity(repo_root: Path | None = None) -> dict:
    root = _resolve_repo_root(repo_root)
    memory_dir = root / "memory"
    dream_log = memory_dir / "dream-log.md"
    md_files = [root / "AGENTS.md", root / "memory.md", dream_log]
    for sub in ("wiki", "preference", "notes", "tasks", "archive"):
        d = memory_dir / sub
        if d.exists():
            md_files += sorted(d.rglob("*.md"))
    link_re = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
    total_links = 0
    broken = []
    graph: dict[str, set[str]] = {}
    active_files: set[str] = set()
    total_active_chars = 0
    oversized_files: list[dict] = []

    for f in md_files:
        if not f.exists():
            continue
        rel = f.relative_to(root).as_posix()
        txt = f.read_text(encoding="utf-8")
        lines = txt.splitlines()
        is_active = _is_active_memory(rel)
        if is_active:
            active_files.add(rel)
            graph.setdefault(rel, set())
            chars = len(txt)
            total_active_chars += chars
            limit = ENTRY_MAX_CHARS if rel == "memory.md" else PAGE_MAX_CHARS
            if chars > limit:
                oversized_files.append({"file": rel, "chars": chars, "max_chars": limit})

        for line in lines:
            for m in link_re.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://")):
                    continue
                total_links += 1
                if target.startswith("/"):
                    if not Path(target).exists():
                        broken.append((rel, target, "missing_abs"))
                    continue
                path_part, _, frag = target.partition("#")
                p = (f.parent / urllib.parse.unquote(path_part)).resolve() if path_part else f.resolve()
                if not p.exists():
                    broken.append((rel, target, "missing_file"))
                    continue
                if frag:
                    t_txt = p.read_text(encoding="utf-8", errors="ignore")
                    slugs = {gfm_slug(h) for h in re.findall(r"^#{1,6}\s+(.+)$", t_txt, flags=re.M)}
                    if urllib.parse.unquote(frag) not in slugs:
                        broken.append((rel, target, "missing_anchor"))

                target_rel = _resolve_internal_md(f, target, root)
                if target_rel and is_active:
                    graph[rel].add(target_rel)

    depths: dict[str, int] = {}
    queue: list[str] = []
    if "memory.md" in active_files:
        depths["memory.md"] = 0
        queue.append("memory.md")
    while queue:
        cur = queue.pop(0)
        for nxt in sorted(graph.get(cur, set())):
            if nxt not in depths:
                depths[nxt] = depths[cur] + 1
                queue.append(nxt)
    unreachable_files = sorted(f for f in active_files if f not in depths)
    max_depth = max(depths.values()) if depths else 0

    mem_path = root / "memory.md"
    if mem_path.exists():
        mem_txt = mem_path.read_text(encoding="utf-8")
        mem_lines = len(mem_txt.splitlines())
        mem_chars = len(mem_txt)
    else:
        mem_lines = 0
        mem_chars = 0
    active_preferences = list_rel_md(memory_dir / "preference")
    active_notes = list_rel_md(memory_dir / "notes")
    tasks_dir = memory_dir / "tasks"
    active_tasks = [p.name for p in sorted(tasks_dir.glob("*.md"))] if tasks_dir.exists() else []
    protected_hashes = {
        fn: hashlib.sha256((root / fn).read_bytes()).hexdigest()[:12]
        for fn in PROTECTED_FILES
        if (root / fn).exists()
    }
    return {
        "memory_md_lines": mem_lines,
        "memory_md_chars": mem_chars,
        "total_active_chars": total_active_chars,
        "total_active_files": len(active_files),
        "max_depth": max_depth,
        "oversized_files": oversized_files,
        "unreachable_files": unreachable_files,
        "active_preferences": active_preferences,
        "active_notes": active_notes,
        "active_tasks": active_tasks,
        "total_links": total_links,
        "broken": broken,
        "protected_sha256_prefix": protected_hashes,
    }


def _print_integrity_report(integrity: dict, verbose: bool = False) -> None:
    print(f"- `memory.md`: {integrity['memory_md_lines']} lines, {integrity['memory_md_chars']} chars")
    print(
        f"- Active memory: {integrity['total_active_files']} files, "
        f"{integrity['total_active_chars']} chars (max_depth={integrity['max_depth']})"
    )
    print(f"- Preferences (`memory/preference/`): {integrity['active_preferences']}")
    print(f"- Notes (`memory/notes/`): {integrity['active_notes']}")
    print(f"- Tasks (`memory/tasks/`): {integrity['active_tasks']}")
    print(f"- Links checked: {integrity['total_links']}, broken: {integrity['broken']}")
    print(
        f"- Oversized files: {len(integrity['oversized_files'])}"
        + (" []" if not integrity["oversized_files"] else "")
    )
    for item in integrity["oversized_files"] if verbose or integrity["oversized_files"] else []:
        print(f"  - `{item['file']}`: {item['chars']} chars > {item['max_chars']}")
    print(f"- Unreachable files: {integrity['unreachable_files']}")
    print(f"- Protected SHA-256 prefix: {integrity['protected_sha256_prefix']}")


def _collect_sessions(
    since_ts: float,
    until_ts: float | None,
    include_subagents: bool,
    session_filter: str | None,
    need_full_text: bool,
    repo_root: Path | None = None,
    home: Path | None = None,
) -> tuple[list[dict], int]:
    agy, agy_skip = scan_agy(
        since_ts, until_ts, include_subagents, session_filter, need_full_text, repo_root=repo_root, home=home
    )
    cdx, cdx_skip = scan_codex(
        since_ts, until_ts, include_subagents, session_filter, repo_root=repo_root, home=home
    )
    cld, cld_skip = scan_claude(
        since_ts, until_ts, include_subagents, session_filter, repo_root=repo_root, home=home
    )
    return agy + cdx + cld, agy_skip + cdx_skip + cld_skip


def _run_grep_mode(sessions: list[dict], pattern_str: str, max_hits: int, max_chars: int) -> None:
    regex = re.compile(pattern_str, re.IGNORECASE)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    print(
        f"# Dream Narrow Grep\n- Pattern: `{pattern_str}` | Matching sessions: {len(sessions)} "
        f"| Max hits: {max_hits} | Char budget: {max_chars}"
    )
    hits = 0
    used_chars = 0
    truncated_by_budget = False
    for s in sessions:
        tstr = dt.datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
        turn_list = s["all_msgs"]
        session_header_printed = False
        for idx, (role, txt) in enumerate(turn_list, 1):
            if not regex.search(txt):
                continue
            snippet = clip_match(txt, regex, 320)
            line = f"- `#{idx}` **{role}**: {snippet}"
            header = f"\n### [{s['tool']}] `{s['session']}` ({tstr})"
            add_len = len(line) + 1 + (0 if session_header_printed else len(header) + 1)
            if hits >= max_hits or (used_chars > 0 and used_chars + add_len > max_chars):
                truncated_by_budget = True
                break
            if not session_header_printed:
                print(header)
                session_header_printed = True
                used_chars += len(header) + 1
            print(line)
            used_chars += len(line) + 1
            hits += 1
        if truncated_by_budget:
            break
    print(f"\n- Hits returned: {hits} (truncated_by_budget={truncated_by_budget})")


def _short_session_id(session: dict) -> str:
    sid = session["session"]
    if session["tool"] == "antigravity" and "-" in sid:
        return sid.split("-", 1)[0]
    return sid[:32]


def _run_session_mode(
    sessions: list[dict],
    reply_chars: int,
    tail: int | None,
    max_chars: int,
    turn_spec: str | None,
    offset: int,
    all_turns: bool,
) -> None:
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    print(f"# Dream Session Slice\n- Matched sessions: {len(sessions)} | Char budget: {max_chars}")
    used_chars = 0
    for s in sessions[:3]:
        tstr = dt.datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
        turns = s["all_msgs"] if all_turns else s["msgs"]
        if turn_spec:
            indices = parse_turn_spec(turn_spec, len(turns))
            header = f"\n### [{s['tool']}] `{s['session']}` ({tstr}, {len(turns)} turns, full turns: {indices})"
            print(header)
            used_chars += len(header) + 1
            for n in indices:
                role, txt = turns[n - 1]
                body = txt[offset:] if offset > 0 else txt
                entry = f"\n#### `#{n}` {role} ({len(txt)} chars)\n{body}"
                if used_chars > 0 and used_chars + len(entry) > max_chars:
                    remain = max(0, max_chars - used_chars)
                    if remain > 200:
                        print(entry[:remain])
                        next_off = offset + remain - len(f"\n#### `#{n}` {role} ({len(txt)} chars)\n")
                        print(
                            f"\n> ... truncated at char {max(0, next_off)}/{len(txt)}; "
                            f"continue with `--turn {n} --offset {max(0, next_off)}` or larger `--max-chars`"
                        )
                    else:
                        print(f"\n> ... stopped at --max-chars budget before `#{n}`; inspect with `--turn {n}`")
                    return
                print(entry)
                used_chars += len(entry)
            return

        if tail is not None:
            start = max(0, len(turns) - tail)
            selected = [
                (i + 1, turns[i][0], turns[i][1])
                for i in range(len(turns))
                if turns[i][0] == "USER" or i >= start
            ]
        else:
            selected = [(i + 1, turns[i][0], turns[i][1]) for i in range(len(turns))]

        block = _format_compact_turns(s, selected, assistant_limit=reply_chars, short_id=_short_session_id(s))
        if used_chars > 0 and used_chars + len(block) > max_chars:
            print("\n- _... (stopped at --max-chars budget) ..._")
            return
        print(block)
        used_chars += len(block)


def _read_git_summary(repo_root: Path) -> tuple[list[str], list[str]]:
    try:
        git_status = subprocess.check_output(
            ["git", "-C", str(repo_root), "status", "-s"], text=True, stderr=subprocess.DEVNULL
        ).splitlines()
        git_log = subprocess.check_output(
            ["git", "-C", str(repo_root), "log", "--oneline", "-n", "5"], text=True, stderr=subprocess.DEVNULL
        ).splitlines()
        return git_status, git_log
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [], []


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Dreaming scanner with full user turns and --turn hooks.")
    parser.add_argument("--repo-root", type=Path, default=None, help="Override target repository root path")
    parser.add_argument("--since", help="Override ISO timestamp cutoff (e.g. 2026-11-24T00:00:00+08:00)")
    parser.add_argument("--until", help="Upper ISO timestamp cutoff for batching backlogs")
    parser.add_argument("--all", action="store_true", help="Ignore last_dream_at cutoff (useful with --grep/--session)")
    parser.add_argument("--include-subagents", action="store_true", help="Include subagent-only sessions without user turns")
    parser.add_argument("--order", choices=["newest", "oldest"], default="newest", help="Sort order for session batching")
    parser.add_argument("--max-sessions", type=int, default=12, help="Max sessions in summary output (default: 12)")
    parser.add_argument("--max-chars", type=int, default=16000, help="Hard character budget for transcript section (default: 16000)")
    parser.add_argument(
        "--reply-chars",
        type=int,
        default=None,
        help="Prefix characters kept per ASSISTANT reply (default: 180 in scan, 360 in --session)",
    )
    parser.add_argument("--tail", type=int, default=None, help="In --session mode, show all USER turns + last N ASSISTANT turns")
    parser.add_argument("--session", help="Inspect a specific session ID prefix (ignores last_dream_at unless --since is set)")
    parser.add_argument("--turn", help="Print full untruncated turn(s) in --session mode, e.g. '33', '15,33', or '14-18'")
    parser.add_argument("--offset", type=int, default=0, help="Character offset for reading a huge single turn with --turn")
    parser.add_argument("--all-turns", action="store_true", help="In --session mode, include mid-turn assistant commentary before tool calls")
    parser.add_argument("--grep", help="Narrow regex search over extracted session turns instead of full reads")
    parser.add_argument("--max-hits", type=int, default=25, help="Max matched turns in --grep mode (default: 25)")
    parser.add_argument("--audit", action="store_true", help="Only run memory link, reachability and size check")
    args = parser.parse_args()

    repo_root = _resolve_repo_root(args.repo_root)

    if args.audit:
        print("# Memory Audit")
        integrity = check_memory_integrity(repo_root)
        _print_integrity_report(integrity, verbose=True)
        return

    if args.all or (args.session and not args.since):
        since_dt = dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)
        since_ts = 0.0
    else:
        since_dt = dt.datetime.fromisoformat(args.since) if args.since else parse_last_dream_at(repo_root)
        since_ts = since_dt.timestamp()

    until_ts = dt.datetime.fromisoformat(args.until).timestamp() if args.until else None
    need_full_text = bool(args.grep or args.session)

    if args.grep or args.session:
        sessions, _ = _collect_sessions(
            since_ts, until_ts, args.include_subagents, args.session, need_full_text, repo_root=repo_root
        )
        if args.grep:
            _run_grep_mode(sessions, args.grep, args.max_hits, args.max_chars)
        else:
            reply_chars = 360 if args.reply_chars is None else args.reply_chars
            _run_session_mode(
                sessions,
                reply_chars,
                args.tail,
                args.max_chars,
                turn_spec=args.turn,
                offset=args.offset,
                all_turns=args.all_turns,
            )
        return

    reply_chars = 180 if args.reply_chars is None else args.reply_chars
    print(f"# Dream Scan Report\n- Cutoff (`since`): {since_dt.isoformat()}" + (f" | `until`: {args.until}" if args.until else ""))
    integrity = check_memory_integrity(repo_root)
    _print_integrity_report(integrity, verbose=False)

    git_status, git_log = _read_git_summary(repo_root)
    print(f"- `git status -s` count: {len(git_status)}")
    print("- Recent commits:")
    for gl in git_log:
        print(f"  - `{gl}`")

    sessions, skipped_subagents = _collect_sessions(
        since_ts, until_ts, args.include_subagents, None, need_full_text=False, repo_root=repo_root
    )
    if args.order == "oldest":
        sessions.sort(key=lambda s: s["mtime"])
    else:
        # 优先展示主会话，避免子代理爆发挤占主对话轮次预算
        sessions.sort(key=lambda s: (not s["is_subagent"], s["mtime"]), reverse=True)

    main_cnt = sum(1 for s in sessions if not s["is_subagent"])
    sub_cnt = len(sessions) - main_cnt
    skip_note = f"; {skipped_subagents} subagents skipped, pass --include-subagents to include" if skipped_subagents else ""
    print(f"\n## Transcript Signals Since Cutoff ({len(sessions)} sessions: {main_cnt} main, {sub_cnt} subagent{skip_note})")

    used_chars = 0
    shown_sessions: list[dict] = []
    omitted_sessions: list[dict] = []
    for s in sessions:
        if len(shown_sessions) >= args.max_sessions:
            omitted_sessions.append(s)
            continue
        selected = [(i + 1, role, txt) for i, (role, txt) in enumerate(s["msgs"])]
        block = _format_compact_turns(s, selected, assistant_limit=reply_chars, short_id=_short_session_id(s))
        if shown_sessions and used_chars + len(block) > args.max_chars:
            omitted_sessions.append(s)
            continue
        print(block)
        used_chars += len(block)
        shown_sessions.append(s)

    if omitted_sessions:
        print(
            f"\n## Omitted Sessions Due To Budget ({len(omitted_sessions)} omitted; "
            f"max_sessions={args.max_sessions}, max_chars={args.max_chars})"
        )
        for s in omitted_sessions[:20]:
            tstr = dt.datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%dT%H:%M:%S")
            print(f"- [{s['tool']}] `{s['session']}` ({tstr}, {len(s['msgs'])} msgs)")
        if len(omitted_sessions) > 20:
            print(f"- ... and {len(omitted_sessions) - 20} more")
        if args.order == "oldest" and shown_sessions:
            cutoff_hint = dt.datetime.fromtimestamp(shown_sessions[-1]["mtime"]).astimezone().isoformat()
            print(f"- Batch hint: process shown batch first, then run `--order oldest --since {cutoff_hint}`")
        else:
            print("- Batch hint: backlog exceeded single-pass budget; run with `--order oldest` + `--since/--until` to process in chunks.")


if __name__ == "__main__":
    main()
