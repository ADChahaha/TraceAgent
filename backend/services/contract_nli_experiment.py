from __future__ import annotations

import re
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1] / "data" / "contract_nli" / "dev_all_document_level_official_evidence_schema"
RAW_ROOT = Path(__file__).resolve().parents[2] / "experiments" / "contract_nli" / "data" / "contract-nli" / "raw"
CONTRACT_NLI_ROOT = Path(__file__).resolve().parents[2] / "experiments" / "contract_nli"
PDF_OCR_CACHE_ROOTS = [
    CONTRACT_NLI_ROOT / "outputs" / "contract_nli_pdf10_six_ocr_vs_text" / "ocr_agent" / "agent_runs",
    CONTRACT_NLI_ROOT / "outputs" / "contract_nli_dev_all_document_level_official_evidence_schema_pdf_ocr_probe" / "agent_runs",
]
PDF_OCR_TRACE_ROOTS = [
    CONTRACT_NLI_ROOT / "outputs" / "contract_nli_pdf10_six_ocr_vs_text" / "ocr_agent" / "agent_runs",
    CONTRACT_NLI_ROOT / "outputs" / "contract_nli_dev_all_document_level_official_evidence_schema_pdf_ocr_probe" / "agent_runs",
]


@lru_cache(maxsize=1)
def load_experiment_report() -> dict[str, Any]:
    report_path = EXPERIMENT_ROOT / "agent_vs_direct_report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def list_experiment_samples() -> list[dict[str, Any]]:
    report = load_experiment_report()
    return list(report.get("samples", []))


def get_experiment_sample(sample_id: str) -> dict[str, Any]:
    for sample in list_experiment_samples():
        if str(sample.get("sample_id")) == str(sample_id):
            return sample
    raise KeyError(sample_id)


def load_agent_trace(sample_id: str) -> dict[str, Any]:
    for root in PDF_OCR_TRACE_ROOTS:
        trace_path = root / str(sample_id) / "extraction_result.json"
        if trace_path.exists():
            return json.loads(trace_path.read_text(encoding="utf-8"))
    trace_path = EXPERIMENT_ROOT / "agent_runs" / str(sample_id) / "extraction_result.json"
    return json.loads(trace_path.read_text(encoding="utf-8"))


def build_contract_nli_replay(sample_id: str) -> dict[str, Any]:
    sample = get_experiment_sample(sample_id)
    extraction = load_agent_trace(sample_id)
    result = extraction.get("result") or {}
    trace = extraction.get("trace") or {}
    actions = trace.get("actions") or []
    display_html = _build_display_html(actions)
    document_tree = trace.get("document_tree") or []
    hypotheses = sample.get("hypotheses") or {}
    fields = []
    for label_id, hypothesis in hypotheses.items():
        prefix = label_id.replace("-", "_")
        field_result = result.get(f"{prefix}_choice")
        evidence = result.get(f"{prefix}_evidence") or []
        fields.append(
            {
                "field_name": f"{prefix}_choice",
                "display_name": hypothesis.get("label", label_id),
                "agent_value": field_result,
                "review_value": None,
                "final_value": field_result,
                "field_status": "resolved",
                "route": "accept",
                "source": "agent",
                "committed": False,
            }
        )
        fields.append(
            {
                "field_name": f"{prefix}_evidence",
                "display_name": f"{hypothesis.get('label', label_id)} evidence",
                "agent_value": evidence,
                "review_value": None,
                "final_value": evidence,
                "field_status": "resolved",
                "route": "accept",
                "source": "agent",
                "committed": False,
            }
        )
    return {
        "summary": {
            "task_id": f"contract-nli-{sample_id}",
            "status": "completed",
            "stage": "done",
            "route": "accept",
            "route_reason": "内置 ContractNLI 实验样本",
            "error_message": None,
            "has_result": True,
            "has_trace": True,
            "needs_review": False,
        },
        "result": {
            "task_id": f"contract-nli-{sample_id}",
            "status": "completed",
            "route": "accept",
            "fields": fields,
        },
        "trace": None,
        "replay": {
            "task_id": f"contract-nli-{sample_id}",
            "status": "completed",
            "stage": "done",
            "documents": [
                {
                    "document_id": str(sample.get("document_id")),
                    "filename": sample.get("filename"),
                }
            ],
            "display_html": display_html,
            "outline_tree": document_tree,
            "broad_plan": trace.get("broad_plan"),
            "actions": actions,
            "result": result,
            "field_states": trace.get("field_states") or {},
            "audit": {"route": "accept", "route_reason": "内置 ContractNLI 实验样本"},
        },
        "review": None,
        "audit": None,
    }


def build_contract_nli_html_process(sample_id: str) -> dict[str, Any]:
    sample = get_experiment_sample(sample_id)
    raw_path = RAW_ROOT / str(sample.get("filename"))
    raw_html = raw_path.read_text(encoding="utf-8", errors="ignore")
    pdf_ocr = load_cached_pdf_ocr(sample_id)
    if pdf_ocr:
        agent_html = pdf_ocr.get("html") or ""
        display_html = pdf_ocr.get("display_html") or ""
        source_kind = "pdf-ocr"
        raw_excerpt = f"原始 PDF 文件：{sample.get('filename')}\n\n前端展示的是 MinerU OCR 后的 agent HTML。"
        raw_chars = raw_path.stat().st_size
        raw_element_count = 0
        ocr_block_count = len(pdf_ocr.get("blocks") or [])
    else:
        agent_html = normalize_html_for_agent(raw_html)
        display_html = ""
        source_kind = "raw-html"
        raw_excerpt = raw_html[:2000]
        raw_chars = len(raw_html)
        raw_element_count = count_html_elements(raw_html)
        ocr_block_count = None
    return {
        "sample_id": str(sample_id),
        "document_id": str(sample.get("document_id")),
        "filename": sample.get("filename"),
        "document_type": sample.get("document_type"),
        "source_kind": source_kind,
        "raw_html_chars": raw_chars,
        "agent_html_chars": len(agent_html),
        "agent_html": agent_html,
        "display_html": display_html,
        "raw_html_excerpt": raw_excerpt,
        "agent_html_excerpt": agent_html[:2000],
        "display_html_excerpt": display_html[:2000],
        "raw_element_count": raw_element_count,
        "agent_element_count": count_html_elements(agent_html),
        "ocr_block_count": ocr_block_count,
        "query_checks": [
            {
                "query": query,
                "match_count": count_text_matches(agent_html, query),
            }
            for query in [
                "Confidential Information",
                "Information",
                "Evaluation Material",
                "Proprietary Information",
            ]
        ],
    }


def load_cached_pdf_ocr(sample_id: str) -> dict[str, Any] | None:
    for root in PDF_OCR_CACHE_ROOTS:
        path = root / str(sample_id) / "document_processor.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def _build_display_html(actions: list[dict[str, Any]]) -> str:
    html_chunks: list[str] = []
    seen: set[str] = set()
    for action in actions:
        result = action.get("result")
        if not isinstance(result, dict):
            continue
        matches = result.get("matches")
        if isinstance(matches, list):
            for match in matches:
                if not isinstance(match, dict):
                    continue
                html = match.get("html")
                if isinstance(html, str) and html and html not in seen:
                    seen.add(html)
                    html_chunks.append(html)
        html = result.get("html")
        if isinstance(html, str) and html and html not in seen:
            seen.add(html)
            html_chunks.append(html)
    if not html_chunks:
        return '<h1 id="p000_b000">Contract</h1>'
    if html_chunks[0].startswith("<h1"):
        return "\n".join(html_chunks)
    return '<h1 id="p000_b000">Contract</h1>\n' + "\n".join(html_chunks)


def normalize_html_for_agent(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    blocks = []
    block_tags = ["p", "li", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6"]
    root = soup.body or soup
    for node in root.find_all(block_tags):
        if node.find_parent(block_tags):
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        if not text:
            continue
        tag = node.name.lower()
        if tag in {"dt", "dd"}:
            tag = "p"
        blocks.append((tag, text))
    if not blocks:
        text = " ".join((soup.get_text(" ", strip=True) or "").split())
        return f'<h1 id="p000_b000">Contract</h1>\n<p id="p001_b000">{text}</p>' if text else '<h1 id="p000_b000">Contract</h1>'
    lines = ['<h1 id="p000_b000">Contract</h1>']
    for index, (tag, text) in enumerate(blocks, start=1):
        lines.append(f'<{tag} id="p{index:03d}_b000">{escape_html(text)}</{tag}>')
    return "\n".join(lines)


def count_html_elements(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    return len([node for node in soup.find_all(True) if node.get_text(" ", strip=True)])


def count_text_matches(html: str, query: str) -> int:
    normalized_html = html.casefold()
    return normalized_html.count(query.casefold())


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
