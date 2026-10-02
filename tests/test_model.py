import pytest
from pydantic import ValidationError

from local_agent.models import WorkerRequest, WorkerResult


def test_successful_worker_result():
    result = WorkerResult(
        success=True,
        data={"x": 1},
    )

    assert result.success is True
    assert result.data == {"x": 1}
    assert result.error is None


def test_successful_worker_result_cannot_contain_error():
    with pytest.raises(ValidationError):
        WorkerResult(
            success=True,
            error="boom",
        )


def test_unsuccessful_worker_result_must_contain_error():
    with pytest.raises(ValidationError):
        WorkerResult(
            success=False,
        )


def test_worker_request_rejects_empty_task():
    with pytest.raises(ValidationError):
        WorkerRequest(task="", input_text="some input")


def test_worker_request_accepts_valid_data():
    request = WorkerRequest(
        task="Extract order data",
        input_text="Order 123",
    )

    assert request.task == "Extract order data"
    assert request.input_text == "Order 123"
