from pydantic import ValidationError

from local_agent.models import ExtractionResult, WorkerRequest
from local_agent.validation import OutputIssueKind, normalize_validation_error
from local_agent.workers.extractor import ExtractorWorker


class FakeOllamaClient:
    def __init__(self) -> None:
        self.model: str | None = None
        self.prompt: str | None = None

    def chat(self, model: str, prompt: str) -> str:
        self.model = model
        self.prompt = prompt
        return '{"value": "ABC-123"}'


class FakeInvalidOllamaClient:
    def chat(self, model: str, prompt: str) -> str:
        return "ABC-123"


class FakeRetryOllamaClient:
    def __init__(self) -> None:
        self.number_of_chat_calls = 0

    def chat(self, model: str, prompt: str) -> str:
        if self.number_of_chat_calls == 0:
            self.number_of_chat_calls += 1
            return "ABC-123"
        else:
            self.number_of_chat_calls += 1
            return '{"value": "ABC-123"}'


class FakeFailedRetryOllamaClient:
    def __init__(self) -> None:
        self.number_of_chat_calls = 0

    def chat(self, model: str, prompt: str) -> str:
        if self.number_of_chat_calls == 0:
            self.number_of_chat_calls += 1
            return "ABC-123"
        else:
            self.number_of_chat_calls += 1
            return "ABC-123"


class FakeInvalidJsonThenMissingFieldClient:
    def __init__(self) -> None:
        self.number_of_chat_calls = 0

    def chat(self, model: str, prompt: str) -> str:
        if self.number_of_chat_calls == 0:
            self.number_of_chat_calls += 1
            return "ABC-123"

        else:
            self.number_of_chat_calls += 1
            return '{"order": "ABC-123"}'


class FakeRepairPromptClient:
    def __init__(self) -> None:
        self.prompts = []

    def chat(self, model: str, prompt: str) -> str:
        self.prompts.append(prompt)

        if len(self.prompts) == 1:
            return "BROKEN_MODEL_OUTPUT"

        return '{"value": "ABC-123"}'


def test_extractor_worker_returns_model_response():
    client = FakeOllamaClient()
    worker = ExtractorWorker(client=client)

    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    result = worker.run(request)

    assert result.success is True
    assert result.data == {"value": "ABC-123"}
    assert result.error is None

    assert client.model == "qwen3:1.7b"
    assert client.prompt is not None
    assert "Extract the order number" in client.prompt
    assert "Order ABC-123 was created" in client.prompt

    assert client.prompt is not None
    assert "Return ONLY valid JSON in this exact shape:" in client.prompt
    assert '{"value": "<extracted value>"}' in client.prompt


def test_extractor_worker_returns_failure_for_invalid_model_output():
    client = FakeInvalidOllamaClient()
    worker = ExtractorWorker(client=client)

    request = WorkerRequest(
        task="Extract the order number", input_text="Order ABC-123 was created"
    )

    result = worker.run(request)

    assert result.success is False
    assert result.data is None
    assert result.error is not None


def test_normalize_validation_error_returns_invalid_json_kind_when_error_type_is_invalid_json():
    response_text = "ABC-123"

    validation_result = None
    try:
        _ = ExtractionResult.model_validate_json(response_text)
    except ValidationError as exc:
        validation_result = normalize_validation_error(exc)

    assert validation_result is not None
    assert validation_result.kind == OutputIssueKind.INVALID_JSON
    assert (
        validation_result.message_for_model
        == "Previous response was not in valid JSON."
    )


def test_normalize_validation_error_returns_missing_field_kind_when_error_type_is_missing():
    response_text = '{"order": "ABC-123"}'

    validation_result = None
    try:
        _ = ExtractionResult.model_validate_json(response_text)
    except ValidationError as exc:
        validation_result = normalize_validation_error(exc)

    assert validation_result is not None
    assert validation_result.kind == OutputIssueKind.MISSING_FIELD
    assert (
        validation_result.message_for_model == 'The required field "value" is missing.'
    )


def test_normalize_validation_error_returns_unknown_kind_when_error_type_is_not_handled():
    response_text = '{"value": ""}'

    validation_result = None
    try:
        _ = ExtractionResult.model_validate_json(response_text)
    except ValidationError as exc:
        validation_result = normalize_validation_error(exc)

    assert validation_result is not None
    assert validation_result.kind == OutputIssueKind.UNKNOWN
    assert (
        validation_result.message_for_model
        == "The previous response failed output validation."
    )


def test_extractor_worker_calls_chat_twice_only_when_retries():
    client = FakeRetryOllamaClient()
    worker = ExtractorWorker(client=client)

    request = WorkerRequest(
        task="Extract the order number", input_text="Order ABC-123 was created"
    )

    result = worker.run(request)

    assert result.success is True
    assert result.data == {"value": "ABC-123"}
    assert client.number_of_chat_calls == 2


def test_extractor_worker_returns_success_false_after_two_retries():
    client = FakeFailedRetryOllamaClient()
    worker = ExtractorWorker(client=client)

    request = WorkerRequest(
        task="Extract the order number", input_text="Order ABC-123 was created"
    )

    result = worker.run(request)

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert client.number_of_chat_calls == 2


def test_extractor_worker_returns_last_validation_error_after_failed_retry():
    client = FakeInvalidJsonThenMissingFieldClient()
    worker = ExtractorWorker(client=client)

    request = WorkerRequest(
        task="Extract the order number", input_text="Order ABC-123 was created"
    )

    result = worker.run(request)

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert result.error == 'The required field "value" is missing.'
    assert client.number_of_chat_calls == 2


def test_proper_second_response():
    client = FakeRepairPromptClient()
    worker = ExtractorWorker(client)

    request = WorkerRequest(
        task="Extract the order number", input_text="Order ABC-123 was created"
    )

    _ = worker.run(request)

    repair_prompt = client.prompts[1]

    assert len(client.prompts) == 2
    assert "BROKEN_MODEL_OUTPUT" in repair_prompt
    assert "Extract the order number" in repair_prompt
    assert "Order ABC-123 was created" in repair_prompt
    assert "Previous response was not in valid JSON" in repair_prompt
    assert '{"value": "<extracted value>"}' in repair_prompt
