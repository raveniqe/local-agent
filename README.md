# local-agent

`local-agent` is a small, self-hosted LLM application built to explore how reliable AI workers and agents can be designed, tested, exposed through an API, and deployed as normal software.

The project currently provides a constrained extraction worker backed by a locally hosted Ollama instance. It accepts a task and input text, asks a configured model for structured output, validates the result with Pydantic, and retries once with repair context when the model returns invalid data.

The Ollama host may expose multiple local models. Individual workers can be configured to use a specific model depending on their role. The current extraction worker is configured to use `qwen3:1.7b`.

The longer-term goal is to grow this into a modular local agent runtime with multiple specialized models, tool calling, routing, bounded agent loops, automation integrations, and model evaluation.

## Current architecture

```text id="m5alqs"
HTTP client
    ↓
FastAPI
    ↓
WorkerRequest
    ↓
ExtractorWorker
    ↓
ChatClient protocol
    ↓
OllamaClient
    ↓
Ollama
    ↓
configured local model
    ↓
structured output validation
    ↓
WorkerResult
    ↓
HTTP response
```

The worker depends on a behavioral `ChatClient` protocol rather than directly on Ollama.

This keeps the worker independent from the concrete model provider and makes the LLM boundary easy to replace during testing.

The runtime is also not conceptually tied to a single model. Ollama can host multiple models, while each worker or future agent can be composed with the model appropriate for its task.

## What works today

The current version includes:

- FastAPI HTTP API
- Pydantic request and response validation
- `ExtractorWorker` for constrained structured extraction
- Ollama HTTP client
- structured JSON validation
- retry with repair context after invalid model output
- dependency injection between the API and worker
- fake LLM clients for deterministic API and worker tests
- Docker image
- GitHub Actions CI
- Docker image publishing to GHCR
- automated deployment through a private CD workflow and self-hosted runner

The application has been tested end-to-end through the full path:

```text id="0391jc"
HTTP request
→ FastAPI
→ ExtractorWorker
→ Ollama
→ configured local model
→ validated WorkerResult
→ HTTP response
```

## Example

Request:

```http id="fcwa6c"
POST /extract
Content-Type: application/json
```

```json id="tyiinb"
{
  "task": "Extract the customer name",
  "input_text": "Customer: Alice"
}
```

Successful response:

```json id="oz6t7k"
{
  "success": true,
  "data": {
    "value": "Alice"
  },
  "error": null
}
```

If the model fails to produce a valid structured result after both attempts, the HTTP request can still complete successfully while the worker reports a controlled failure:

```json id="3bo2b2"
{
  "success": false,
  "data": null,
  "error": "Previous response was not in valid JSON."
}
```

This intentionally separates HTTP-level success from worker-level success.

## Requirements

For local development:

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- at least one Ollama model available to the application

The current `ExtractorWorker` configuration uses:

```text id="model-current"
qwen3:1.7b
```

but the Ollama instance may contain additional models for other workers, experiments, or future agent roles.

Ollama does not need to run on the same machine as `local-agent`. It only needs to be reachable over HTTP.

## Running locally

Install the project dependencies:

```bash id="kuosmf"
uv sync
```

For the current extractor configuration, make sure the default extraction model is available:

```bash id="xcfhba"
ollama pull qwen3:1.7b
```

If Ollama is not already running as a service:

```bash id="55ld2f"
ollama serve
```

Start the FastAPI application:

```bash id="dw6bzm"
uv run uvicorn local_agent.api:app --reload
```

The API will be available locally at:

```text id="k8f9l2"
http://127.0.0.1:8000
```

Interactive FastAPI documentation:

```text id="zr18c4"
http://127.0.0.1:8000/docs
```

## Accessing the API

### Local development

When `local-agent` is running directly on your development machine:

```bash id="pbui99"
curl http://127.0.0.1:8000/health
```

Here, `127.0.0.1` refers to the machine on which the API process is running.

### Remote or Docker deployment

When `local-agent` is deployed on another machine, use the address of the deployment host instead:

```bash id="wbckpi"
curl http://<local-agent-host>:8000/health
```

For example, a client machine on the same network can call:

```bash id="w211b2"
curl -X POST http://<local-agent-host>:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Extract the customer name",
    "input_text": "Customer: Alice"
  }'
```

The client does not need direct access to Ollama.

The deployed `local-agent` service communicates with Ollama on its behalf.

```text id="fuvdy4"
client
  ↓
local-agent host
  ↓
FastAPI
  ↓
ExtractorWorker
  ↓
Ollama host
  ↓
selected model
```

## Configuration

The Ollama endpoint is configured through an environment variable.

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Base URL of the Ollama HTTP API |

Example with Ollama running on another host:

```bash id="ro7xm5"
OLLAMA_BASE_URL=http://<ollama-host>:11434 \
uv run uvicorn local_agent.api:app --reload
```

Configuration is injected at runtime rather than baked into the application image.

Model selection is currently performed when individual workers are composed. The extraction worker currently uses `qwen3:1.7b`; making model selection configurable at runtime is part of the roadmap.

## API

### `GET /health`

Checks whether the API process is alive.

This endpoint does not require Ollama to be reachable.

Local example:

```bash id="xi8f1e"
curl http://127.0.0.1:8000/health
```

Response:

```json id="q38v3i"
{
  "health": "ok"
}
```

For a deployed instance:

```bash id="u1vwlz"
curl http://<local-agent-host>:8000/health
```

### `POST /echo`

A small validation endpoint used while developing the FastAPI boundary.

Leading and trailing whitespace is removed from the input.

```bash id="fvbk0y"
curl -X POST http://127.0.0.1:8000/echo \
  -H "Content-Type: application/json" \
  -d '{"message":"  hello  "}'
```

Response:

```json id="6pp33z"
{
  "response": "hello"
}
```

Blank strings and invalid input types are rejected through FastAPI/Pydantic validation.

### `POST /extract`

Runs the extraction worker using its configured model.

Both `task` and `input_text` must be non-empty strings.

```bash id="vl75q8"
curl -X POST http://127.0.0.1:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Extract the order number",
    "input_text": "Order ABC-123 has been created."
  }'
```

Successful response:

```json id="fp1toz"
{
  "success": true,
  "data": {
    "value": "ABC-123"
  },
  "error": null
}
```

Controlled worker failure:

```json id="wguuo5"
{
  "success": false,
  "data": null,
  "error": "Previous response was not in valid JSON."
}
```

Invalid API input, such as a missing required field or an empty string, is rejected with HTTP `422`.

## Reliability model

The extractor treats LLM output as untrusted input.

The expected model response is:

```json id="1javgc"
{
  "value": "..."
}
```

The processing flow is:

```text id="ep9inc"
model response
    ↓
Pydantic validation
    ├── valid
    │     ↓
    │   success
    │
    └── invalid
          ↓
       normalize validation issue
          ↓
       build repair prompt
          ↓
       second model call
          ↓
       validate again
```

If the second result is also invalid, the worker returns a controlled `WorkerResult` with:

```text id="lcvsdx"
success = false
data = null
error = <validation-related message>
```

The worker does not expose malformed model output directly as a successful structured result.

## Testing

The test suite does not require a running Ollama instance.

```bash id="gqyl4r"
uv run pytest
```

The LLM boundary is replaced with deterministic fake `ChatClient` implementations while the real application layers remain under test.

For API tests, FastAPI dependency overrides inject an `ExtractorWorker` configured with a fake chat client.

This allows deterministic scenarios such as:

```text id="tr8g8k"
valid model output
→ success=True

invalid JSON twice
→ retry
→ success=False
```

without depending on:

- network availability
- a running Ollama server
- model latency
- nondeterministic model output
- which models happen to be installed on the Ollama host

The tested path still includes:

```text id="utayy4"
HTTP request
→ FastAPI
→ WorkerRequest
→ ExtractorWorker
→ validation/retry logic
→ WorkerResult
→ HTTP response
```

Only the external LLM boundary is replaced.

## Docker

Build the image locally:

```bash id="ccbgcl"
docker build -t local-agent .
```

Run it:

```bash id="hibnt6"
docker run --rm \
  -p 8000:8000 \
  -e OLLAMA_BASE_URL=http://<ollama-host>:11434 \
  local-agent
```

The container starts Uvicorn with the FastAPI application and listens on:

```text id="xqxepm"
0.0.0.0:8000
```

Publishing port `8000` makes the API reachable through the Docker host.

For example:

```text id="p9m9l1"
client
↓
http://<docker-host>:8000
↓
Docker port mapping
↓
Uvicorn
↓
FastAPI
```

The Docker image is also built automatically by GitHub Actions and published to GHCR after successful checks on `main`.

## CI/CD

The delivery pipeline deliberately separates the public application repository from private deployment infrastructure.

```text id="abevyt"
public local-agent repository
        ↓
tests + pre-commit
        ↓
Docker build
        ↓
GHCR
        ↓
dispatch private deployment workflow
        ↓
private deployment repository
        ↓
self-hosted runner
        ↓
Docker Compose pull
        ↓
Docker Compose up
        ↓
running local-agent service
```

### CI

The public repository uses GitHub-hosted runners for:

- dependency installation
- pre-commit checks
- pytest
- Docker image build
- GHCR publishing

Pull requests run validation but do not publish or deploy application images.

Publishing and deployment are restricted to trusted pushes to `main`.

### CD

Deployment infrastructure is kept separate from the public repository.

The public workflow only signals a private deployment workflow after the image has been successfully published.

The private deployment workflow runs on a self-hosted runner located in the deployment environment and performs:

```bash id="oio6h4"
docker compose pull
docker compose up -d
```

This keeps direct access to the private runtime environment outside the public application repository.

## Project structure

```text id="bowyni"
src/local_agent/
├── api.py
├── config.py
├── models.py
├── ollama.py
├── protocols.py
├── validation.py
└── workers/
    └── extractor.py

tests/
└── ...

docs/
└── ...
```

Main responsibilities:

```text id="0hehzi"
api.py
→ FastAPI HTTP boundary and dependency composition

config.py
→ runtime configuration

models.py
→ Pydantic data contracts

protocols.py
→ behavioral interfaces such as ChatClient

ollama.py
→ Ollama HTTP integration

validation.py
→ normalization of model-output validation failures

workers/extractor.py
→ extraction workflow, retry logic and structured result handling
```

## Roadmap

The current extractor is intentionally small.

It is the first worker used to establish the runtime architecture before adding more autonomous behavior.

The runtime is intended to support multiple specialized local models rather than assuming that one model should handle every task.

Planned areas include:

- configurable model selection
- model-to-task routing
- explicit readiness checks for external dependencies
- richer worker error taxonomy
- tool definitions with validated arguments
- native tool calling
- deterministic routing between workers and agents
- bounded agent execution loops
- orchestration across multiple workers
- n8n integration
- real automation workflows
- evaluation datasets
- repeatable model-quality benchmarks
- comparison of local models for specialized workloads

The goal is not to build an unrestricted autonomous-agent framework.

The project focuses on small, explicit components with constrained responsibilities, observable behavior, validated boundaries, and testable integrations.

## Current limitations

- The extractor currently expects a single result shape: `{"value": "..."}`.
- The current extractor is configured to use `qwen3:1.7b`.
- Model selection is not yet exposed through runtime configuration or routing.
- Ollama connection failures and timeouts do not yet have a dedicated API error model.
- Only the extraction worker is currently exposed through the main task API.
- Tool calling is not implemented yet.
- Agent orchestration is not implemented yet.

These limitations are kept explicit rather than hidden behind placeholder abstractions.

## Development principles

The project follows a few simple principles:

- treat LLM output as untrusted input
- validate boundaries explicitly
- keep model providers behind small interfaces
- allow specialized models to serve specialized roles
- prefer deterministic code around nondeterministic models
- test application behavior without requiring live inference
- keep workers independent from the HTTP layer
- keep deployment infrastructure separate from the public repository
- prefer explicit, bounded behavior over uncontrolled autonomy
- add abstractions when real use cases require them rather than in advance

## Status

Active development.

Currently working end-to-end:

```text id="n660gj"
FastAPI
→ ExtractorWorker
→ Ollama
→ configured local model
→ structured validation
→ Docker
→ CI
→ GHCR
→ private CD
→ self-hosted deployment
```

The current extraction path uses `qwen3:1.7b`, while the Ollama runtime can host additional models for other specialized workloads.

The next major development area is tool calling, model routing, and agent orchestration.
