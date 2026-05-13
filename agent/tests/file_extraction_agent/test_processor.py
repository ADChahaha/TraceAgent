from __future__ import annotations

import pytest

from service.file_extraction_agent.impl import model_factory as model_factory_module
from service.file_extraction_agent.impl.model_factory import normalize_model_config
from service.file_extraction_agent.processor import extract_stream
from service.file_extraction_agent.schemas import ModelConfig


def test_extract_stream_builds_documents_input_and_runs_stream_graph(monkeypatch):
    captured = {}

    def fake_build_resolution_model(config):
        captured["config"] = config
        return "resolution-model"

    def fake_run_graph_stream(extraction_input, resolution_model):
        captured["documents"] = extraction_input.documents
        captured["field"] = extraction_input.task_spec.fields[0].name
        captured["model"] = resolution_model
        yield '{"type":"result_completed"}\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_extraction_graph_stream", fake_run_graph_stream)

    events = list(
        extract_stream(
            documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            task_spec={"fields": [{"name": "title"}]},
            model_config=ModelConfig(resolution_model_name="resolution"),
        )
    )

    assert events == ['{"type":"result_completed"}\n']
    assert captured["documents"][0].filename == "notice.html"
    assert captured["field"] == "title"
    assert captured["model"] == "resolution-model"


def test_normalize_model_config_loads_default_env_file(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                'BASE_URL="https://example.com/v1"',
                'OPENAI_API_KEY="key"',
                'RESOLUTION_MODEL="resolution"',
                'TEMPERATURE="0.1"',
                'TOP_P="0.9"',
                'TOP_K="40"',
                'REASONING_EFFORT="high"',
                'MODEL_MAX_RETRIES="8"',
                'MODEL_REQUEST_TIMEOUT="120"',
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
        "RESOLUTION_MODEL",
        "MODEL",
        "TEMPERATURE",
        "TOP_P",
        "TOP_K",
        "REASONING_EFFORT",
        "MODEL_MAX_RETRIES",
        "MODEL_REQUEST_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)

    config = normalize_model_config(None)

    assert config.base_url == "https://example.com/v1"
    assert config.api_key == "key"
    assert config.resolution_model_name == "resolution"
    assert config.temperature == 0.1
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.reasoning_effort == "high"
    assert config.max_retries == 8
    assert config.request_timeout == 120.0


def test_normalize_model_config_rejects_unknown_model_fields():
    with pytest.raises(TypeError, match="unexpected keyword argument 'broad_model_name'"):
        normalize_model_config({"broad_model_name": "broad", "resolution_model_name": "resolution"})
