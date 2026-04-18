# AGENT RULES FOR `agent/`

This file applies to AI agents working inside `agent/`.
Follow the repository root [AGENT.md](../AGENT.md) first, then apply the stricter rules here for this package.

## Environment

- MUST create and use the Conda environment `agent-gate` before running Python-related commands in this package if it does not already exist.
- MUST run `conda activate agent-gate` before executing `python`, `pip`, `pytest`, `uvicorn`, or package-local scripts for `agent/`.
- MUST assume validation results are incomplete if commands were run outside `agent-gate`.

Recommended bootstrap:

```bash
conda create -n agent-gate python=3.11 -y
conda activate agent-gate
cd agent
pip install -e ".[dev]"
```

## Scope Reminder

- `document_processor` handles document normalization.
- `file_extraction_agent` handles field extraction on normalized content.
- Read the nearest `docs/DESIGN.md` before changing code, tests, or structural docs in this package.
