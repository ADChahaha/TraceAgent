from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.services.contract_nli_experiment import (
    build_contract_nli_html_process,
    build_contract_nli_replay,
    get_experiment_sample,
    load_experiment_report,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/contract-nli")
def get_contract_nli_experiment(request: Request):
    try:
        report = load_experiment_report()
        samples = report.get("samples", [])
        default_sample_id = samples[0]["sample_id"] if samples else None
        return {
            "dataset": "contract_nli",
            "run_id": "dev_all_document_level_official_evidence_schema",
            "default_sample_id": default_sample_id,
            "samples": samples,
            "report": report,
        }
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/contract-nli/samples/{sample_id}/detail")
def get_contract_nli_sample_detail(sample_id: str, request: Request):
    try:
        get_experiment_sample(sample_id)
        return build_contract_nli_replay(sample_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/contract-nli/samples/{sample_id}/html-process")
def get_contract_nli_html_process(sample_id: str, request: Request):
    try:
        get_experiment_sample(sample_id)
        return build_contract_nli_html_process(sample_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
