from __future__ import annotations

from service.file_extraction_agent.processor import extract
from service.file_extraction_agent.schemas import ModelConfig
from service.file_extraction_agent.impl import model_factory as model_factory_module
from service.file_extraction_agent.impl.model_factory import normalize_model_config


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


def test_normalize_model_config_loads_default_env_file(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                'BASE_URL="https://example.com/v1"',
                'API_KEY="key"',
                'BROAD_MODEL="broad"',
                'RESOLUTION_MODEL="resolution"',
                'TEMPERATURE="0.1"',
                'TOP_P="0.9"',
                'TOP_K="40"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(model_factory_module, "_candidate_env_paths", lambda: [env_path])
    missing_cwd = tmp_path / "missing"
    missing_cwd.mkdir()
    monkeypatch.chdir(missing_cwd)
    for name in (
        "BASE_URL",
        "API_KEY",
        "OPENAI_API_KEY",
        "BROAD_MODEL",
        "RESOLUTION_MODEL",
        "MODEL",
        "TEMPERATURE",
        "TOP_P",
        "TOP_K",
    ):
        monkeypatch.delenv(name, raising=False)

    config = normalize_model_config(None)

    assert config.base_url == "https://example.com/v1"
    assert config.api_key == "key"
    assert config.broad_model_name == "broad"
    assert config.resolution_model_name == "resolution"
    assert config.temperature == 0.1
    assert config.top_p == 0.9
    assert config.top_k == 40
