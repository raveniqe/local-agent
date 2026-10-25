import os
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, StringConstraints

from local_agent.config import load_extractor_config
from local_agent.models import WorkerRequest, WorkerResult
from local_agent.workers.extractor import PydanticExtractorWorker


class HealthResponse(BaseModel):
    """Response body for health endpoint"""

    health: Literal["ok"]


class EchoRequest(BaseModel):
    """Request body for the echo endpoint."""

    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]


class EchoResponse(BaseModel):
    """Response body returned by the echo endpoint."""

    response: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]


app = FastAPI()


@cache
def _get_extractor_worker() -> PydanticExtractorWorker:
    """Build the extractor worker used to handle extraction requests."""

    extractor_worker_settings = load_extractor_config(
        Path(os.getenv("EXTRACTOR_CONFIG_PATH", "config/extractor.json"))
    )

    worker = PydanticExtractorWorker(
        model=extractor_worker_settings.model,
        instructions=extractor_worker_settings.instructions,
        output_retries=extractor_worker_settings.output_retries,
        request_timeout_seconds=extractor_worker_settings.request_timeout_seconds,
    )

    return worker


@app.get("/health", response_model=HealthResponse)
def get_status():
    """Return the current API health."""
    return {"health": "ok"}


@app.post("/echo", response_model=EchoResponse)
def send_echo(request: EchoRequest):
    """Return the validated message received in the request."""
    return {"response": request.message}


@app.post("/extract", response_model=WorkerResult)
def extract(
    request: WorkerRequest,
    worker: Annotated[PydanticExtractorWorker, Depends(_get_extractor_worker)],
):
    """Return the worker result for a validated extraction request."""
    result = worker.run(request)

    return result
