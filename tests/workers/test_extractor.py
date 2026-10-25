import pytest
from pydantic import ValidationError
from pydantic_ai import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    UnexpectedModelBehavior,
    UserPromptPart,
)
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from local_agent.models import ExtractionResult, WorkerRequest
from local_agent.validation import OutputIssueKind, normalize_validation_error
from local_agent.workers.extractor import ExtractorWorker, PydanticExtractorWorker

INVALID_OUTPUT_ERROR = "Extractor could not produce valid structured output."
PROVIDER_ERROR = "Model provider request failed."


def make_worker(**changed_settings) -> PydanticExtractorWorker:
    settings = {
        "model": "qwen3:1.7b",
        "instructions": "Extract the requested value.",
        "output_retries": 1,
        "request_timeout_seconds": 120,
    }
    settings.update(changed_settings)

    return PydanticExtractorWorker(**settings)


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


def test_extractor_worker_builds_repair_prompt_after_invalid_output():
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


def test_pydantic_extractor_returns_worker_result():
    worker = make_worker()

    test_model = TestModel(custom_output_args={"value": "ABC-123"})

    with worker.agent.override(model=test_model):
        request = WorkerRequest(
            task="Extract the order number",
            input_text="Order ABC-123 was created",
        )

        result = worker.run(request=request)

        assert result.data == {"value": "ABC-123"}
        assert result.success is True
        assert result.error is None


def test_pydantic_extractor_returns_failure_on_unexpected_model_behavior(monkeypatch):

    def fake_run_sync(promt: str):
        raise UnexpectedModelBehavior(message="Simulated failure")

    worker = make_worker()

    monkeypatch.setattr(worker.agent, "run_sync", fake_run_sync)

    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    result = worker.run(request=request)

    assert result.data is None
    assert result.success is False
    assert result.error == INVALID_OUTPUT_ERROR


def test_pydantic_extractor_retries_invalid_output_and_returns_corrected_result():
    number_of_calls = 0

    async def agent_reply(
        messages: list[ModelMessage], agent_info: AgentInfo
    ) -> ModelResponse:
        nonlocal number_of_calls
        has_retry_prompt = False

        number_of_calls += 1
        for message in messages:
            for message_part in message.parts:
                if isinstance(message_part, RetryPromptPart):
                    has_retry_prompt = True

        if not has_retry_prompt:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=agent_info.output_tools[0].name, args={"value": 1}
                    )
                ]
            )

        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=agent_info.output_tools[0].name, args={"value": "ABC-123"}
                )
            ]
        )

    worker = make_worker()

    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with worker.agent.override(model=FunctionModel(agent_reply)):
        result = worker.run(request=request)

        assert number_of_calls == 2
        assert result.data == {"value": "ABC-123"}
        assert result.success is True
        assert result.error is None


def test_pydantic_extractor_returns_failure_after_retry_exhaustion():
    number_of_calls = 0

    async def agent_reply(
        messages: list[ModelMessage], agent_info: AgentInfo
    ) -> ModelResponse:
        nonlocal number_of_calls
        has_retry_prompt = False

        number_of_calls += 1
        for message in messages:
            for message_part in message.parts:
                if isinstance(message_part, RetryPromptPart):
                    has_retry_prompt = True

        if not has_retry_prompt:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=agent_info.output_tools[0].name, args={"value": 1}
                    )
                ]
            )

        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=agent_info.output_tools[0].name, args={"value": 1}
                )
            ]
        )

    worker = make_worker()

    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with worker.agent.override(model=FunctionModel(agent_reply)):
        result = worker.run(request=request)

        assert number_of_calls == 2
        assert result.data is None
        assert result.success is False
        assert result.error == INVALID_OUTPUT_ERROR


def test_pydantic_extractor_passes_task_and_input_to_agent():
    captured_prompt = []

    async def agent_reply(
        messages: list[ModelMessage], agent_info: AgentInfo
    ) -> ModelResponse:
        for message in messages:
            for message_part in message.parts:
                if isinstance(message_part, UserPromptPart):
                    captured_prompt.append(message_part.content)

        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=agent_info.output_tools[0].name, args={"value": "ABC-123"}
                )
            ]
        )

    worker = make_worker()

    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with worker.agent.override(model=FunctionModel(agent_reply)):
        result = worker.run(request=request)

        assert len(captured_prompt) == 1
        assert request.task in captured_prompt[0]
        assert request.input_text in captured_prompt[0]
        assert result.success is True
        assert result.error is None


@pytest.mark.parametrize(
    ("output_retries", "expected_calls"),
    [(0, 1), (3, 4)],
)
def test_pydantic_extractor_respects_configured_output_retry_limit(
    output_retries, expected_calls
):
    number_of_calls = 0

    async def agent_reply(
        messages: list[ModelMessage], agent_info: AgentInfo
    ) -> ModelResponse:
        nonlocal number_of_calls
        number_of_calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=agent_info.output_tools[0].name,
                    args={"value": 1},
                )
            ]
        )

    worker = make_worker(output_retries=output_retries)
    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with worker.agent.override(model=FunctionModel(agent_reply)):
        result = worker.run(request=request)

    assert number_of_calls == expected_calls
    assert result.success is False
    assert result.data is None
    assert result.error == INVALID_OUTPUT_ERROR


def test_pydantic_extractor_uses_configured_instructions():
    configured_instructions = "Use only literal values from the supplied text."
    captured_instructions = []

    async def agent_reply(
        messages: list[ModelMessage], agent_info: AgentInfo
    ) -> ModelResponse:
        captured_instructions.append(agent_info.instructions)

        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=agent_info.output_tools[0].name,
                    args={"value": "ABC-123"},
                )
            ]
        )

    worker = make_worker(instructions=configured_instructions)
    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with worker.agent.override(model=FunctionModel(agent_reply)):
        result = worker.run(request=request)

    assert result.success is True
    assert captured_instructions == [configured_instructions]


def test_pydantic_extractor_passes_configured_timeout_to_model_settings():
    captured_timeouts = []

    async def agent_reply(
        messages: list[ModelMessage], agent_info: AgentInfo
    ) -> ModelResponse:
        assert agent_info.model_settings is not None
        captured_timeouts.append(agent_info.model_settings.get("timeout"))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=agent_info.output_tools[0].name,
                    args={"value": "ABC-123"},
                )
            ]
        )

    worker = make_worker(request_timeout_seconds=45)
    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with worker.agent.override(model=FunctionModel(agent_reply)):
        result = worker.run(request=request)

    assert result.success is True
    assert captured_timeouts == [45]


def test_pydantic_extractor_sanitizes_provider_failure(monkeypatch):
    def raise_provider_error(prompt: str):
        raise ModelHTTPError(
            status_code=503,
            model_name="qwen3:1.7b",
            body={"detail": "private provider response"},
        )

    worker = make_worker()
    monkeypatch.setattr(worker.agent, "run_sync", raise_provider_error)
    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    result = worker.run(request=request)

    assert result.success is False
    assert result.data is None
    assert result.error == PROVIDER_ERROR
    assert "private provider response" not in result.error


def test_pydantic_extractor_sanitizes_timeout_failure(monkeypatch):
    def raise_timeout_error(prompt: str):
        try:
            raise TimeoutError("private timeout detail")
        except TimeoutError as exc:
            raise ModelAPIError(
                model_name="qwen3:1.7b",
                message="provider request timed out: private timeout detail",
            ) from exc

    worker = make_worker()
    monkeypatch.setattr(worker.agent, "run_sync", raise_timeout_error)
    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    result = worker.run(request=request)

    assert result.success is False
    assert result.data is None
    assert result.error == PROVIDER_ERROR
    assert "private timeout detail" not in result.error


def test_pydantic_extractor_does_not_hide_unexpected_programming_error(monkeypatch):
    def raise_programming_error(prompt: str):
        raise RuntimeError("programming defect")

    worker = make_worker()
    monkeypatch.setattr(worker.agent, "run_sync", raise_programming_error)
    request = WorkerRequest(
        task="Extract the order number",
        input_text="Order ABC-123 was created",
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        worker.run(request=request)
