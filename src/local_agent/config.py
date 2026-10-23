"""Configuration models and loading utilities for the local agent."""

import json
import os
from json import JSONDecodeError
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

NonBlankString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ExtractorConfigError(Exception):
    """Raised when extractor configuration cannot be loaded or validated."""


class ExtractorConfig(BaseModel):
    """Validated settings used to configure the extractor worker."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(strict=True, ge=1, le=1)
    model: NonBlankString
    instructions: NonBlankString
    output_retries: int = Field(strict=True, ge=0, le=3)
    request_timeout_seconds: float = Field(strict=True, gt=0, le=600)


def load_extractor_config(path: Path) -> ExtractorConfig:
    """Load and validate extractor settings from a UTF-8 JSON file.

    Raises:
        ExtractorConfigError: If the file cannot be read, decoded, parsed, or
            validated as extractor configuration.
    """

    try:
        with open(path, "r", encoding="UTF-8") as config_file:
            config = json.load(config_file)

        return ExtractorConfig.model_validate(config)

    except OSError as exc:
        raise ExtractorConfigError(f"Could not open config file {path}.") from exc

    except UnicodeError as exc:
        raise ExtractorConfigError("Could not decode config file.") from exc

    except JSONDecodeError as exc:
        raise ExtractorConfigError("Could not parse JSON config file.") from exc

    except ValidationError as exc:
        raise ExtractorConfigError(
            f"Could not load extractor config from {path}."
        ) from exc
