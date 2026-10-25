from typing import Annotated, Any, Self

from pydantic import BaseModel, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WorkerRequest(BaseModel):
    """
    Represents a task request passed to a worker.

    Contains the task description and the input text the worker
    should process.
    """

    task: NonEmptyString
    input_text: NonEmptyString


class WorkerResult(BaseModel):
    """
    Represents the result returned by a worker.

    A successful result must contain data and must not contain an error.
    A failed result must contain an error message.
    """

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """
        Validate that the result state is internally consistent.
        """

        if self.success:
            if self.data is None:
                raise ValueError("Successful result must contain data.")
            if self.error is not None:
                raise ValueError("Successful result cannot contain an error.")
        else:
            if self.error is None:
                raise ValueError("Failed result must contain an error.")
            if self.data is not None:
                raise ValueError("Failed result cannot contain data.")
        return self


class ExtractionResult(BaseModel):
    """
    Represents a structured value extracted by a worker.
    """

    value: NonEmptyString
