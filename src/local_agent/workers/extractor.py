from pydantic import ValidationError

from local_agent.models import ExtractionResult, WorkerRequest, WorkerResult
from local_agent.protocols import ChatClient
from local_agent.validation import normalize_validation_error


class ExtractorWorker:
    def __init__(
        self,
        client: ChatClient,
        model: str = "qwen3:1.7b",
    ) -> None:
        self.client = client
        self.model = model

    def run(self, request: WorkerRequest) -> WorkerResult:
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
