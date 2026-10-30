# local-agent

`local-agent` is a small, self-hosted LLM application built to explore how
reliable AI workers can be designed, tested, exposed through an API, and
deployed as normal software.

Extractor V1 accepts a task and input text, asks a JSON-configured Ollama model
for native structured output, validates the result with Pydantic, and returns a
consistent success or failure envelope. Output retries and the provider-request
timeout are also configured through JSON.

The active extractor model is `qwen3:4b-instruct`. A separate live evaluation
runner can compare this model with other models available on the Ollama host
without changing the production configuration.

V1 intentionally contains one extractor, one fixed result schema, one provider,
and one HTTP extraction endpoint. More open-ended tools require their own
contracts and evaluations; this repository does not yet provide a general agent
framework.

## Current architecture

```text
HTTP client
    ↓
FastAPI
    ↓
WorkerRequest
    ↓
cached configuration and worker dependency
    ↓
PydanticExtractorWorker
    ↓
Pydantic AI Agent
    ↓
OllamaModel through the OpenAI-compatible /v1 endpoint
    ↓
NativeOutput(ExtractionResult)
    ↓
WorkerResult validation
    ↓
HTTP response
```

Stable extractor behavior comes from `config/extractor.json`. The Ollama address
remains environment-specific and comes from `OLLAMA_BASE_URL`. Tests replace the
real model with Pydantic AI test doubles while keeping application validation and
control flow under test.

## What works today

The current version includes:

- FastAPI HTTP API
- Pydantic request and response validation
- `PydanticExtractorWorker` for constrained structured extraction
- JSON configuration with strict validation and unknown-field rejection
- Pydantic AI `OllamaModel` integration
- native structured output validated as `ExtractionResult`
- configured structured-output retries and provider-request timeout
- sanitized provider and invalid-output failures
- dependency injection between the API and worker
- Pydantic AI test doubles for deterministic API and worker tests
- explicit English/Polish live model evaluation runner
- Docker image
- GitHub Actions CI
- Docker image publishing to GHCR
- automated deployment through a private CD workflow and self-hosted runner

The application has been tested end-to-end through the full path:

```text
HTTP request
→ FastAPI
→ PydanticExtractorWorker
→ Ollama
→ configured local model
→ NativeOutput(ExtractionResult)
→ WorkerResult
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

If the model fails to produce a valid structured result within the configured
retry budget, the HTTP request can still complete successfully while the worker
reports a controlled failure:

```json id="3bo2b2"
{
  "success": false,
  "data": null,
  "error": "Extractor could not produce valid structured output."
}
```

This intentionally separates HTTP-level success from worker-level success.

## Requirements

For local development:

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- at least one Ollama model available to the application

The current JSON configuration uses:

```text
qwen3:4b-instruct
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
ollama pull qwen3:4b-instruct
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

```text
client
  ↓
local-agent host
  ↓
FastAPI
  ↓
PydanticExtractorWorker
  ↓
Ollama host
  ↓
JSON-configured model
```

## Configuration

Stable extractor behavior is configured in `config/extractor.json`:

```json
{
  "schema_version": 1,
  "model": "qwen3:4b-instruct",
  "instructions": "Extract the value requested by the task. Return only data matching the required schema.",
  "output_retries": 1,
  "request_timeout_seconds": 120
}
```

All fields are required and unknown fields are rejected. `schema_version` must
be `1`, `output_retries` must be between `0` and `3`, and the timeout must be
greater than `0` and no greater than `600` seconds.

Set `EXTRACTOR_CONFIG_PATH` to load a different configuration file. Otherwise
the application uses `config/extractor.json`, resolved from its working
directory.

Deployment-specific values remain environment variables.

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Base URL of the Ollama HTTP API |
| `EXTRACTOR_CONFIG_PATH` | `config/extractor.json` | Path to the extractor behavior configuration |

Example with Ollama running on another host:

```bash id="ro7xm5"
OLLAMA_BASE_URL=http://<ollama-host>:11434 \
uv run uvicorn local_agent.api:app --reload
```

Do not put credentials, private deployment URLs, or customer data in the JSON
configuration.

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
  "error": "Extractor could not produce valid structured output."
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

```text
task + input text
    ↓
Pydantic AI requests native JSON matching ExtractionResult
    ↓
model response
    ↓
JSON decoding and Pydantic validation
    ├── valid
    │     ↓
    │   successful WorkerResult
    │
    └── invalid
          ↓
       Pydantic AI output retry, within the configured budget
          ↓
       validate again
```

If the configured retry budget is exhausted, the worker returns:

```json
{
  "success": false,
  "data": null,
  "error": "Extractor could not produce valid structured output."
}
```

Expected provider failures use the sanitized error `Model provider request
failed.` Unexpected programming exceptions are not hidden behind a controlled
worker failure.

## Testing

The test suite does not require a running Ollama instance.

```bash id="gqyl4r"
uv run pytest
```

The LLM boundary is replaced with Pydantic AI `TestModel` or `FunctionModel`
instances while the real application layers remain under test. Test setup also
blocks accidental requests to non-test models.

For API tests, FastAPI dependency overrides inject the intended Pydantic AI
worker or a worker mock.

This allows deterministic scenarios such as:

```text id="tr8g8k"
valid model output
→ success=True

invalid structured output until retry exhaustion
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
→ PydanticExtractorWorker
→ validation/retry logic
→ WorkerResult
→ HTTP response
```

Only the external LLM boundary is replaced.

### Live model evaluation

Live evaluation is separate from pytest and makes real Ollama requests:

```bash
uv run --env-file .env python scripts/evaluate_extractor_models.py --list-cases

PYDANTIC_AI_NO_BANNER=1 uv run --env-file .env \
  python scripts/evaluate_extractor_models.py \
  --model qwen3:4b-instruct \
  --model gemma3:4b \
  --repeat 3
```

The runner contains 18 synthetic English/Polish extraction cases and can filter
by model, case, language, or difficulty. Its results measure only that dataset;
they do not establish quality for future tools or open-ended agent behavior.

#### Extractor V1 baseline

The recorded V1 model-selection run executed all 18 cases three times for each
model, for 54 requests per model:

| Model | Exact matches | Pass rate | Average response time |
| --- | ---: | ---: | ---: |
| `qwen3:4b-instruct` | 54/54 | 100.0% | 4.1 s |
| `gemma3:4b` | 54/54 | 100.0% | 5.4 s |

These results are a baseline for the current synthetic dataset in the author's
self-hosted environment. They are not a general model benchmark, and the latency
figures are not expected to transfer directly to different hardware or Ollama
setups. The exact cases remain versioned in
`scripts/evaluate_extractor_models.py`, so the comparison can be repeated after
changing a model, prompt, or runtime configuration.

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
  -e EXTRACTOR_CONFIG_PATH=/app/config/extractor.json \
  -v "$PWD/config/extractor.json:/app/config/extractor.json:ro" \
  local-agent
```

The image bundles the default extractor configuration at
`/app/config/extractor.json`. The read-only bind mount above replaces that file
with the configuration from the current checkout. Omit the mount and
`EXTRACTOR_CONFIG_PATH` to use the bundled default, or point
`EXTRACTOR_CONFIG_PATH` at another mounted file to override it.

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
└── workers/
    └── extractor.py

tests/
└── ...

config/
└── extractor.json

scripts/
└── evaluate_extractor_models.py

docs/
└── ...
```

Main responsibilities:

```text id="0hehzi"
api.py
→ FastAPI HTTP boundary and dependency composition

config.py
→ extractor configuration model, loader, and provider location

models.py
→ Pydantic data contracts

workers/extractor.py
→ Pydantic AI agent composition, extraction, and failure normalization

scripts/evaluate_extractor_models.py
→ explicit live model-quality and latency evaluation
```

## Roadmap

The completed V1 extractor is intentionally small. New capabilities should be
added only after their request, output, safety, and evaluation contracts are
defined.

Planned areas include:

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
- larger representative evaluation datasets
- benchmarks for tool selection, arguments, side effects, and failure recovery

The goal is not to build an unrestricted autonomous-agent framework.

The project focuses on small, explicit components with constrained responsibilities, observable behavior, validated boundaries, and testable integrations.

## Current limitations

- The extractor currently expects a single result shape: `{"value": "..."}`.
- The current extractor is configured to use `qwen3:4b-instruct` through JSON.
- One configured model is active at a time; runtime model routing is not
  implemented.
- Ollama connection failures and timeouts do not yet have a dedicated API error model.
- Only the extraction worker is currently exposed through the main task API.
- Tool calling is not implemented yet.
- Agent orchestration is not implemented yet.

These limitations are kept explicit rather than hidden behind placeholder abstractions.

## Development principles

The project follows a few simple principles:

- treat LLM output as untrusted input
- validate boundaries explicitly
- keep provider-specific composition small and explicit
- allow specialized models to serve specialized roles
- prefer deterministic code around nondeterministic models
- test application behavior without requiring live inference
- keep workers independent from the HTTP layer
- keep deployment infrastructure separate from the public repository
- prefer explicit, bounded behavior over uncontrolled autonomy
- add abstractions when real use cases require them rather than in advance

## Status

Extractor V1 is implemented and verified. The repository remains under active
development for later capabilities.

Currently working end-to-end:

```text id="n660gj"
FastAPI
→ PydanticExtractorWorker
→ Pydantic AI
→ Ollama configured by environment
→ qwen3:4b-instruct configured by JSON
→ NativeOutput(ExtractionResult)
→ Docker
→ CI
→ GHCR
→ private CD
→ self-hosted deployment
```

The next capability should be scoped and evaluated independently. Passing the
extractor benchmark does not imply that the selected model is safe or effective
for open-ended tool use.
