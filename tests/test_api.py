import pytest
from fastapi.testclient import TestClient

from local_agent.api import _get_extractor_worker, app
from local_agent.workers.extractor import ExtractorWorker

client = TestClient(app)


class FakeLLMChatClient:
    def chat(self, model: str, prompt: str) -> str:
        return '{"value": "Alice"}'


class FailingFakeChatClient:
    def chat(self, model: str, prompt: str) -> str:
        return "It isn't valid JSON"


def get_fake_extractor_worker():
    return ExtractorWorker(FakeLLMChatClient())


def get_fake_failing_extractor_worker():
    return ExtractorWorker(FailingFakeChatClient())


@pytest.fixture
def prepare_successful_environment():
    app.dependency_overrides[_get_extractor_worker] = get_fake_extractor_worker

    yield

    app.dependency_overrides = {}


@pytest.fixture
def prepare_environment_for_failed_extractor():
    app.dependency_overrides[_get_extractor_worker] = get_fake_failing_extractor_worker

    yield

    app.dependency_overrides = {}


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


def test_extract_returns_successful_request_and_data(prepare_successful_environment):
    response = client.post(
        "/extract",
        json={
            "task": "Extract the customer name",
            "input_text": "Customer: Alice",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"value": "Alice"},
        "error": None,
    }


def test_extract_returns_failed_result_when_model_returns_invalid_json(
    prepare_environment_for_failed_extractor,
):
    response = client.post(
        "/extract",
        json={"task": "Extract the customer name", "input_text": "Customer: Alison"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "data": None,
        "error": "Previous response was not in valid JSON.",
    }
