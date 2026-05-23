from __future__ import annotations

import pytest

from service.file_extraction_agent.impl import model_factory as model_factory_module
from service.file_extraction_agent.impl.model_factory import build_chat_model, normalize_model_config
from service.file_extraction_agent.processor import cancel_completion, create_completion_stream
from service.file_extraction_agent.schemas import ModelConfig


def test_create_completion_stream_builds_completion_input_and_runs_graph(monkeypatch):
    captured = {}

    def fake_build_resolution_model(config):
        captured["config"] = config
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        captured["completion_id"] = completion_input.completion_id
        captured["documents"] = completion_input.documents
        captured["messages"] = completion_input.messages
        captured["model"] = resolution_model
        yield 'event: completion.completed\ndata: {"id":"cmp_123"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    events = list(
        create_completion_stream(
            completion_id="cmp_123",
            documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
            messages=[{"role": "user", "content": "问题"}],
            model_config=ModelConfig(resolution_model_name="resolution"),
        )
    )

    assert events == ['event: completion.completed\ndata: {"id":"cmp_123"}\n\n']
    assert captured["completion_id"] == "cmp_123"
    assert captured["documents"][0].filename == "notice.html"
    assert captured["messages"][0].content == "问题"
    assert captured["model"] == "resolution-model"


def test_create_completion_stream_validates_input_before_iteration(monkeypatch):
    called = False

    def fake_build_resolution_model(config):
        nonlocal called
        called = True
        return "resolution-model"

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)

    with pytest.raises(ValueError, match="documents"):
        create_completion_stream(
            completion_id="cmp_123",
            documents=[],
            messages=[{"role": "user", "content": "问题"}],
            model_config=ModelConfig(resolution_model_name="resolution"),
        )

    assert called is False


def test_create_completion_stream_registers_active_completion_before_iteration(monkeypatch):
    def fake_build_resolution_model(config):
        return "resolution-model"

    def fake_run_completion_graph_stream(completion_input, resolution_model):
        del completion_input, resolution_model
        yield 'event: completion.completed\ndata: {"id":"cmp_early_cancel"}\n\n'

    monkeypatch.setattr("service.file_extraction_agent.processor.build_resolution_model", fake_build_resolution_model)
    monkeypatch.setattr("service.file_extraction_agent.processor.run_completion_graph_stream", fake_run_completion_graph_stream)

    stream = create_completion_stream(
        completion_id="cmp_early_cancel",
        documents=[{"filename": "notice.html", "html": '<p id="p1">通知</p>'}],
        messages=[{"role": "user", "content": "问题"}],
        model_config=ModelConfig(resolution_model_name="resolution"),
    )

    assert cancel_completion("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "cancelling"}
    assert list(stream) == [
        'event: completion.cancelled\ndata: {"id":"cmp_early_cancel","type":"completion.cancelled","status":"cancelled"}\n\n'
    ]
    assert cancel_completion("cmp_early_cancel") == {"id": "cmp_early_cancel", "status": "not_found"}


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


def test_build_chat_model_builds_responses_stream_then_chat_fallbacks(monkeypatch):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(model_factory_module, "ChatOpenAI", FakeChatOpenAI)

    model = build_chat_model(
        ModelConfig(
            base_url="https://example.com/v1",
            api_key="key",
            resolution_model_name="resolution",
        ),
        "resolution",
    )

    attempts = model.model_call_attempts()
    assert [attempt.name for attempt in attempts] == [
        "responses_stream",
        "chat_completions_stream",
        "responses_invoke",
        "chat_completions_invoke",
    ]
    assert [attempt.use_stream for attempt in attempts] == [True, True, False, False]
    assert [kwargs["use_responses_api"] for kwargs in captured] == [True, False, True, False]
    assert [kwargs["streaming"] for kwargs in captured] == [True, True, False, False]


def test_normalize_model_config_rejects_unknown_model_fields():
    with pytest.raises(TypeError, match="unexpected keyword argument 'broad_model_name'"):
        normalize_model_config({"broad_model_name": "broad", "resolution_model_name": "resolution"})
