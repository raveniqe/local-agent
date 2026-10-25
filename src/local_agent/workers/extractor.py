"""Extractor workers for validated structured value extraction."""

from pydantic import ValidationError
from pydantic_ai import ModelAPIError
from pydantic_ai.agent import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

from local_agent.config import OLLAMA_BASE_URL
from local_agent.models import ExtractionResult, WorkerRequest, WorkerResult
from local_agent.protocols import ChatClient
from local_agent.validation import normalize_validation_error


class ExtractorWorker:
    """Extract a single structured value from text using a chat model."""

    def __init__(
        self,
        client: ChatClient,
        model: str = "qwen3:1.7b",
    ) -> None:
        """Initialize the legacy extractor with a chat client and model name."""
        self.client = client
        self.model = model

    def run(self, request: WorkerRequest) -> WorkerResult:
        """Run extraction and retry once when the model output is invalid."""
        prompt = f"""
        Task:
        {request.task}

        Input:
        {request.input_text}

        Return ONLY valid JSON in this exact shape:
        {{"value": "<extracted value>"}}
        """.strip()

        for attempt in range(2):
            response_text = self.client.chat(model=self.model, prompt=prompt)

            try:
                extraction = ExtractionResult.model_validate_json(response_text)
                return WorkerResult(
                    success=True, data=extraction.model_dump(), error=None
                )
            except ValidationError as exc:
                issue = normalize_validation_error(exc)

                if attempt == 1:
                    return WorkerResult(
                        success=False, data=None, error=issue.message_for_model
                    )

                prompt = f"""
                Task:
                {request.task}

                Input:
                {request.input_text}

                Previous response:
                {response_text}

                Issue description:
                {issue.message_for_model}

                Return ONLY valid JSON in this exact shape:
                {{"value": "<extracted value>"}}
                """.strip()

        raise AssertionError("Unreachable")


class PydanticExtractorWorker:
    """Extract a single structured value from text using a chat model."""

    def __init__(
        self,
        *,
        model: str,
        instructions: str,
        output_retries: int,
        request_timeout_seconds: float,
    ) -> None:
        """Configure the Pydantic AI extractor from validated settings."""
        self.model = OllamaModel(
            model,
            provider=OllamaProvider(base_url=f"{OLLAMA_BASE_URL.rstrip('/')}/v1"),
        )
        self.instructions = instructions
        self.output_retries = output_retries
        self.request_timeout_seconds = request_timeout_seconds

        self.agent = Agent(
            self.model,
            output_type=ExtractionResult,
            instructions=self.instructions,
            retries={"output": self.output_retries},
            model_settings={
                "timeout": self.request_timeout_seconds,
            },
        )

    def run(self, request: WorkerRequest) -> WorkerResult:
        """Extract a value and normalize expected model and provider failures."""
        prompt = f"""
        Task:
        {request.task}

        Input:
        {request.input_text}
        """.strip()

        try:
            extraction = self.agent.run_sync(prompt)
            return WorkerResult(
                success=True,
                data=extraction.output.model_dump(),
                error=None,
            )
        except UnexpectedModelBehavior:
            return WorkerResult(
                success=False,
                data=None,
                error="Extractor could not produce valid structured output.",
            )
        except ModelAPIError:
            return WorkerResult(
                success=False, data=None, error="Model provider request failed."
            )
