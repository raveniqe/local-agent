from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, model_validator


class WorkerRequest(BaseModel):
    """
    Represents a task request passed to a worker.

    Contains the task description and the input text the worker
    should process.
    """

    task: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    input_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WorkerResult(BaseModel):
    """
    Represents the result returned by a worker.

    A successful result may contain data and must not contain an error.
    A failed result must contain an error message.
    """

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_result(self):
        """
        Validate that the result state is internally consistent.
        """
        if self.success is True and self.error is not None:
            raise ValueError("Successful result cannot contain an error")

        if self.success is False and self.error is None:
            raise ValueError("Failed result must contain an error")

        return self


class ExtractionResult(BaseModel):
    """
    Represents a structured value extracted by a worker.
    """

    value: str = Field(min_length=1)
