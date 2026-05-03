"""Run MinerU pipeline and load its structured output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class MinerUConversionError(RuntimeError):
    """Raised when MinerU does not produce a usable content list."""


def convert_pdf_bytes_to_content_list(
    source_bytes: bytes,
    filename: str,
    *,
    lang: str | None = None,
) -> list[list[dict[str, Any]]]:
    """Parse PDF bytes with MinerU pipeline and return content_list_v2 pages."""

    resolved_lang = lang or resolve_mineru_lang()
    mineru_bin = resolve_mineru_executable()
    with tempfile.TemporaryDirectory(prefix="document-processor-mineru-") as tmp:
        work_dir = Path(tmp)
        input_path = work_dir / filename
        output_dir = work_dir / "output"
        input_path.write_bytes(source_bytes)

        command = [
            mineru_bin,
            "-p",
            str(input_path),
            "-o",
            str(output_dir),
            "-b",
            "pipeline",
            "-m",
            "auto",
            "-l",
            resolved_lang,
            "-f",
            "false",
            "-t",
            "true",
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=build_mineru_env(),
        )
        if completed.returncode != 0:
            raise MinerUConversionError(
                "MinerU pipeline failed: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )

        content_list_path = find_content_list_v2(output_dir)
        if content_list_path is None:
            raise MinerUConversionError("MinerU did not produce content_list_v2.json.")
        data = json.loads(content_list_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise MinerUConversionError("MinerU content_list_v2.json is not a list.")
        return data


def resolve_mineru_executable() -> str:
    """Find the MinerU CLI executable."""

    configured = os.getenv("MINERU_BIN")
    if configured:
        return configured
    sibling = Path(sys.executable).with_name("mineru")
    if sibling.exists() and os.access(sibling, os.X_OK):
        return str(sibling)
    found = shutil.which("mineru")
    if found:
        return found
    raise MinerUConversionError(
        "MinerU executable not found. Install mineru[core] or set MINERU_BIN."
    )


def resolve_mineru_lang() -> str:
    """Resolve the MinerU OCR language code."""

    return os.getenv("DOCUMENT_PROCESSOR_MINERU_LANG", "japan").strip() or "japan"


def build_mineru_env() -> dict[str, str]:
    """Build a conservative MinerU runtime environment."""

    env = os.environ.copy()
    env.setdefault("MINERU_API_MAX_CONCURRENT_REQUESTS", "1")
    return env


def find_content_list_v2(output_dir: Path) -> Path | None:
    """Return the first MinerU content_list_v2 artifact under output_dir."""

    matches = sorted(output_dir.rglob("*_content_list_v2.json"))
    return matches[0] if matches else None
