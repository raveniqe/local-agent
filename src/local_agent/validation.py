from dataclasses import dataclass
from enum import Enum

from pydantic import ValidationError


class OutputIssueKind(Enum):
    INVALID_JSON = "invalid_json"
    MISSING_FIELD = "missing_field"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OutputValidationIssue:
    kind: OutputIssueKind
    message_for_model: str


def normalize_validation_error(validation_error: ValidationError) -> OutputValidationIssue:
    errors = validation_error.errors()
    first_error = errors[0]

    error_type = first_error["type"]

    if error_type == "json_invalid":
        return OutputValidationIssue(
            kind=OutputIssueKind.INVALID_JSON,
            message_for_model="Previous response was not in valid JSON."
        )

    elif error_type == "missing":
        error_loc = first_error["loc"][0]
        return OutputValidationIssue(
            kind=OutputIssueKind.MISSING_FIELD,
            message_for_model=f'The required field "{error_loc}" is missing.'
        )

    return OutputValidationIssue(
        kind=OutputIssueKind.UNKNOWN,
        message_for_model="The previous response failed output validation."
    )


