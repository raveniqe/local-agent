"""Contract tests for the Extractor V1 JSON configuration boundary."""

import json
from collections.abc import Callable
from json import JSONDecodeError
from pathlib import Path

import pytest
from pydantic import ValidationError

from local_agent import config as config_module

VALID_CONFIG = {
    "schema_version": 1,
    "model": "qwen3:1.7b",
    "instructions": "Extract the requested value.",
    "output_retries": 1,
    "request_timeout_seconds": 120,
}


def write_config(path: Path, **changes: object) -> Path:
    payload = VALID_CONFIG | changes
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def load_config() -> Callable[[Path], object]:
    loader = getattr(config_module, "load_extractor_config", None)
    if loader is None:
        pytest.skip("V1 gap: implement local_agent.config.load_extractor_config(path)")
    return loader


def validation_cause(exception: Exception) -> ValidationError:
    cause = exception.__cause__
    assert isinstance(cause, ValidationError)
    return cause


def test_extractor_config_loader_is_available():
    assert callable(
        getattr(config_module, "load_extractor_config", None)
    ), "V1 gap: local_agent.config must expose load_extractor_config(path)"


def test_loads_complete_valid_config(load_config, tmp_path):
    path = write_config(
        tmp_path / "extractor.json",
        model="  qwen3:1.7b  ",
        instructions="  Extract the requested value.  ",
    )

    config = load_config(path)

    assert config.schema_version == 1
    assert config.model == "qwen3:1.7b"
    assert config.instructions == "Extract the requested value."
    assert config.output_retries == 1
    assert config.request_timeout_seconds == 120


def test_missing_config_preserves_file_error_as_cause(load_config, tmp_path):
    path = tmp_path / "missing.json"

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    assert isinstance(exc_info.value.__cause__, FileNotFoundError)
    assert str(path) in str(exc_info.value)


def test_invalid_utf8_preserves_decode_error_as_cause(load_config, tmp_path):
    path = tmp_path / "extractor.json"
    path.write_bytes(b"\xff")

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)


def test_malformed_json_preserves_json_error_as_cause(load_config, tmp_path):
    path = tmp_path / "extractor.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    assert isinstance(exc_info.value.__cause__, JSONDecodeError)


def test_config_root_must_be_an_object(load_config, tmp_path):
    path = tmp_path / "extractor.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    validation_cause(exc_info.value)


@pytest.mark.parametrize("missing_field", VALID_CONFIG)
def test_all_config_fields_are_required(load_config, tmp_path, missing_field):
    payload = VALID_CONFIG.copy()
    payload.pop(missing_field)
    path = tmp_path / "extractor.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    cause = validation_cause(exc_info.value)
    assert any(missing_field in error["loc"] for error in cause.errors())


def test_unknown_config_field_is_rejected(load_config, tmp_path):
    path = write_config(tmp_path / "extractor.json", output_retry=1)

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    cause = validation_cause(exc_info.value)
    assert any("output_retry" in error["loc"] for error in cause.errors())


@pytest.mark.parametrize("schema_version", [2, "1", True])
def test_only_integer_schema_version_one_is_supported(
    load_config, tmp_path, schema_version
):
    path = write_config(
        tmp_path / f"extractor-{schema_version!r}.json",
        schema_version=schema_version,
    )

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    cause = validation_cause(exc_info.value)
    assert any("schema_version" in error["loc"] for error in cause.errors())


@pytest.mark.parametrize("field", ["model", "instructions"])
@pytest.mark.parametrize("value", ["", "   "])
def test_text_config_fields_must_not_be_blank(load_config, tmp_path, field, value):
    path = write_config(tmp_path / f"extractor-{field}.json", **{field: value})

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    cause = validation_cause(exc_info.value)
    assert any(field in error["loc"] for error in cause.errors())


@pytest.mark.parametrize("output_retries", [0, 3])
def test_output_retry_boundaries_are_valid(load_config, tmp_path, output_retries):
    path = write_config(
        tmp_path / f"extractor-{output_retries}.json",
        output_retries=output_retries,
    )

    config = load_config(path)

    assert config.output_retries == output_retries


@pytest.mark.parametrize("output_retries", [-1, 4, True, 1.5, "1"])
def test_invalid_output_retry_values_are_rejected(
    load_config, tmp_path, output_retries
):
    path = write_config(
        tmp_path / f"extractor-{output_retries!r}.json",
        output_retries=output_retries,
    )

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    cause = validation_cause(exc_info.value)
    assert any("output_retries" in error["loc"] for error in cause.errors())


@pytest.mark.parametrize("timeout", [0.1, 600])
def test_request_timeout_boundaries_are_valid(load_config, tmp_path, timeout):
    path = write_config(
        tmp_path / f"extractor-{timeout}.json",
        request_timeout_seconds=timeout,
    )

    config = load_config(path)

    assert config.request_timeout_seconds == timeout


@pytest.mark.parametrize("timeout", [0, -1, 600.1, True, "120"])
def test_invalid_request_timeouts_are_rejected(load_config, tmp_path, timeout):
    path = write_config(
        tmp_path / f"extractor-{timeout!r}.json",
        request_timeout_seconds=timeout,
    )

    with pytest.raises(Exception) as exc_info:
        load_config(path)

    cause = validation_cause(exc_info.value)
    assert any("request_timeout_seconds" in error["loc"] for error in cause.errors())
