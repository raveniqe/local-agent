from pathlib import Path
from typing import get_args, get_type_hints
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from pydantic_ai.profiles import ModelProfile

import local_agent.api as api_module
from local_agent.api import _get_extractor_worker, app, extract
from local_agent.config import ExtractorConfig, ExtractorConfigError
from local_agent.models import WorkerResult
from local_agent.workers.extractor import PydanticExtractorWorker

client = TestClient(app)


def make_extractor_settings() -> ExtractorConfig:
    return ExtractorConfig(
        schema_version=1,
        model="configured-model",
        instructions="Configured extraction instructions.",
        output_retries=2,
        request_timeout_seconds=45,
    )


@pytest.fixture(autouse=True)
def clear_extractor_worker_cache():
    clear_cache = getattr(_get_extractor_worker, "cache_clear", None)
    if clear_cache is not None:
        clear_cache()

    yield

    if clear_cache is not None:
        clear_cache()


@pytest.fixture
def extractor_worker_mock():
    worker = Mock(spec=PydanticExtractorWorker)
    app.dependency_overrides[_get_extractor_worker] = lambda: worker

    yield worker

    app.dependency_overrides.pop(_get_extractor_worker, None)


def test_status_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"health": "ok"}


def test_echo_rejects_missing_message():
    response = client.post("/echo", json={"test": ""})

    assert response.status_code == 422


def test_echo_rejects_non_string_message():
    response = client.post("/echo", json={"message": 1})

    assert response.status_code == 422


def test_echo_rejects_blank_message():
    response = client.post("/echo", json={"message": "   "})

    assert response.status_code == 422


def test_echo_returns_stripped_message():
    response = client.post("/echo", json={"message": "  hello  "})

    assert response.status_code == 200
    assert response.json() == {"response": "hello"}


def test_echo_returns_response():
    response = client.post(
        "/echo",
        json={"message": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {"response": "hello"}


def test_extract_integrates_with_intended_pydantic_worker():
    worker = PydanticExtractorWorker(
        model="qwen3:1.7b",
        instructions="Extract the requested value.",
        output_retries=1,
        request_timeout_seconds=120,
    )
    test_model = TestModel(
        custom_output_text='{"value": "Alice"}',
        profile=ModelProfile(supports_json_schema_output=True),
    )
    app.dependency_overrides[_get_extractor_worker] = lambda: worker

    try:
        with worker.agent.override(model=test_model):
            response = client.post(
                "/extract",
                json={
                    "task": "Extract the customer name",
                    "input_text": "Customer: Alice",
                },
            )
    finally:
        app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"value": "Alice"},
        "error": None,
    }


def test_extract_dependency_is_declared_as_pydantic_worker():
    factory_return_type = get_type_hints(_get_extractor_worker)["return"]
    endpoint_worker_annotation = get_type_hints(extract, include_extras=True)["worker"]
    endpoint_worker_type = get_args(endpoint_worker_annotation)[0]

    assert factory_return_type is PydanticExtractorWorker
    assert endpoint_worker_type is PydanticExtractorWorker


def test_extractor_worker_factory_uses_config_path_and_all_settings(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "extractor.json"
    settings = make_extractor_settings()
    loaded_paths = []
    received_settings = {}
    expected_worker = object()

    def fake_load_extractor_config(path: Path) -> ExtractorConfig:
        loaded_paths.append(path)
        return settings

    def fake_worker(
        *,
        model: str,
        instructions: str,
        output_retries: int,
        request_timeout_seconds: float,
    ):
        received_settings.update(
            model=model,
            instructions=instructions,
            output_retries=output_retries,
            request_timeout_seconds=request_timeout_seconds,
        )
        return expected_worker

    monkeypatch.setenv("EXTRACTOR_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(api_module, "load_extractor_config", fake_load_extractor_config)
    monkeypatch.setattr(api_module, "PydanticExtractorWorker", fake_worker)

    worker = _get_extractor_worker()

    assert worker is expected_worker
    assert loaded_paths == [config_path]
    assert received_settings == {
        "model": "configured-model",
        "instructions": "Configured extraction instructions.",
        "output_retries": 2,
        "request_timeout_seconds": 45,
    }


def test_extractor_worker_factory_uses_default_config_path(monkeypatch):
    loaded_paths = []
    settings = make_extractor_settings()

    def fake_load_extractor_config(path: Path) -> ExtractorConfig:
        loaded_paths.append(path)
        return settings

    monkeypatch.delenv("EXTRACTOR_CONFIG_PATH", raising=False)
    monkeypatch.setattr(api_module, "load_extractor_config", fake_load_extractor_config)
    monkeypatch.setattr(
        api_module, "PydanticExtractorWorker", lambda **kwargs: object()
    )

    _get_extractor_worker()

    assert loaded_paths == [Path("config/extractor.json")]


def test_extractor_worker_factory_loads_config_and_builds_worker_once(monkeypatch):
    load_calls = 0
    worker_calls = 0
    settings = make_extractor_settings()

    def fake_load_extractor_config(path: Path) -> ExtractorConfig:
        nonlocal load_calls
        load_calls += 1
        return settings

    def fake_worker(**kwargs):
        nonlocal worker_calls
        worker_calls += 1
        return object()

    monkeypatch.setenv("EXTRACTOR_CONFIG_PATH", "config/test-extractor.json")
    monkeypatch.setattr(api_module, "load_extractor_config", fake_load_extractor_config)
    monkeypatch.setattr(api_module, "PydanticExtractorWorker", fake_worker)

    first_worker = _get_extractor_worker()
    second_worker = _get_extractor_worker()

    assert first_worker is second_worker
    assert load_calls == 1
    assert worker_calls == 1


def test_invalid_config_prevents_extractor_worker_creation(monkeypatch):
    def fail_config_load(path: Path):
        raise ExtractorConfigError("Invalid extractor configuration.")

    def fail_worker_creation(**kwargs):
        pytest.fail("Worker must not be created when configuration is invalid.")

    monkeypatch.setenv("EXTRACTOR_CONFIG_PATH", "config/invalid-extractor.json")
    monkeypatch.setattr(api_module, "load_extractor_config", fail_config_load)
    monkeypatch.setattr(api_module, "PydanticExtractorWorker", fail_worker_creation)

    with pytest.raises(ExtractorConfigError, match="Invalid extractor configuration"):
        _get_extractor_worker()


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            "Extractor could not produce valid structured output.",
            id="invalid-output",
        ),
        pytest.param("Model provider request failed.", id="provider-failure"),
    ],
)
def test_extract_preserves_controlled_worker_failure(error, extractor_worker_mock):
    extractor_worker_mock.run.return_value = WorkerResult(
        success=False,
        data=None,
        error=error,
    )

    response = client.post(
        "/extract",
        json={"task": "Extract the customer name", "input_text": "Customer: Alice"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "data": None,
        "error": error,
    }
    extractor_worker_mock.run.assert_called_once()


def test_extract_does_not_hide_unexpected_worker_exception(extractor_worker_mock):
    extractor_worker_mock.run.side_effect = RuntimeError("Unexpected worker failure")

    with pytest.raises(RuntimeError, match="Unexpected worker failure"):
        client.post(
            "/extract",
            json={
                "task": "Extract the customer name",
                "input_text": "Customer: Alice",
            },
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"task": "", "input_text": "Customer: Alice"},
        {"task": "Extract name", "input_text": ""},
    ],
)
def test_extract_rejects_empty_fields(payload, extractor_worker_mock):
    response = client.post("/extract", json=payload)

    assert response.status_code == 422
    extractor_worker_mock.run.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"task": "   ", "input_text": "Customer: Alice"},
        {"task": "Extract name", "input_text": "   "},
    ],
)
def test_extract_rejects_whitespace_only_fields(payload, extractor_worker_mock):
    response = client.post("/extract", json=payload)

    assert response.status_code == 422
    extractor_worker_mock.run.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"task": "Extract name"},
        {"input_text": "Customer: Alice"},
    ],
)
def test_extract_rejects_missing_required_fields(payload, extractor_worker_mock):
    response = client.post("/extract", json=payload)

    assert response.status_code == 422
    extractor_worker_mock.run.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"task": 123, "input_text": "Customer: Alice"},
        {"task": "Extract name", "input_text": ["Customer: Alice"]},
    ],
)
def test_extract_rejects_non_string_fields(payload, extractor_worker_mock):
    response = client.post("/extract", json=payload)

    assert response.status_code == 422
    extractor_worker_mock.run.assert_not_called()
