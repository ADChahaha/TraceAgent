from __future__ import annotations

from service.file_extraction_agent.processor import extract
from service.file_extraction_agent.schemas import ModelConfig


def test_extract_builds_input_models_and_runs_graph(monkeypatch):
    captured = {}

    def fake_build_stage_models(config):
        captured["config"] = config
        return "broad-model", "resolution-model"

    def fake_run_graph(extraction_input, broad_model, resolution_model):
        captured["html"] = extraction_input.html
        captured["field"] = extraction_input.task_spec.fields[0].name
        captured["models"] = (broad_model, resolution_model)
        return "ok"

    monkeypatch.setattr("service.file_extraction_agent.processor.build_stage_models", fake_build_stage_models)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_extraction_graph", fake_run_graph)

    result = extract(
        html='<p id="dp-p-1">正文</p>',
        task_spec={"fields": [{"name": "title"}]},
        model_config=ModelConfig(broad_model_name="broad", resolution_model_name="resolution"),
    )

    assert result == "ok"
    assert captured["html"] == '<p id="dp-p-1">正文</p>'
    assert captured["field"] == "title"
    assert captured["models"] == ("broad-model", "resolution-model")
