from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, StringConstraints

from local_agent.config import OLLAMA_BASE_URL
from local_agent.models import WorkerRequest, WorkerResult
from local_agent.ollama import OllamaClient
from local_agent.workers.extractor import ExtractorWorker


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


def _get_extractor_worker() -> ExtractorWorker:
    """Build the extractor worker used to handle extraction requests."""
    client = OllamaClient(base_url=OLLAMA_BASE_URL)

    worker = ExtractorWorker(client)

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
    worker: Annotated[ExtractorWorker, Depends(_get_extractor_worker)],
):
    """Return the worker result for a validated extraction request."""
    result = worker.run(request)

    return result
