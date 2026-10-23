# Extractor V1 specification

Status: proposed implementation contract based on the repository state inspected
on 2026-10-22.

## 1. Goal

V1 provides one extractor that accepts a task and input text, asks one Ollama
model to return a validated `ExtractionResult`, and exposes the result through
the existing worker and HTTP interfaces. Stable extractor behavior is loaded
from a JSON file.

V1 is intentionally not a general worker framework. It has one provider, one
extractor, one fixed output model, and one request path.

## 2. Verified current state

The repository currently contains two parallel implementations:

```text
POST /extract
    -> ExtractorWorker
    -> custom OllamaClient calling /api/chat
    -> manual JSON validation and repair prompt

PydanticExtractorWorker (not wired to POST /extract)
    -> Pydantic AI Agent
    -> OllamaModel through the OpenAI-compatible /v1 endpoint
    -> ExtractionResult validation and Pydantic AI output retries
```

The current domain contracts are:

- `WorkerRequest.task`: stripped, non-empty string.
- `WorkerRequest.input_text`: stripped, non-empty string.
- `ExtractionResult.value`: string with `min_length=1`. It currently does not
  strip whitespace, so a whitespace-only value can pass validation.
- `WorkerResult`: `success`, optional `data`, and optional `error`. Its validator
  rejects a successful result with an error and a failed result without an
  error, but it does not yet require data on success or forbid data on failure.

The focused Pydantic extractor suite currently has 14 passing tests. It verifies
successful structured output, prompt contents, output retry behavior, and retry
exhaustion. The HTTP tests still exercise the legacy worker.

`pyproject.toml` declares Python 3.13 or newer, Pydantic 2.13.5 or newer, and
Pydantic AI with the OpenAI provider. The `local-agent` console command currently
prints a greeting and is not a usable extractor interface.

## 3. V1 boundaries

### In scope

- One JSON configuration file for stable extractor behavior.
- Configurable model name, instructions, output retry count, and request timeout.
- The existing `WorkerRequest` request shape.
- The fixed `ExtractionResult` output shape: `{"value": "..."}`.
- The existing `WorkerResult` response envelope.
- Programmatic invocation through `worker.run(WorkerRequest(...))`.
- HTTP invocation through `POST /extract`.
- Clear configuration, provider, and invalid-output failure behavior.
- Deterministic automated tests and one optional live smoke test.

### Out of scope

- Multiple agents or workers, routing, delegation, orchestration, plugins, or a
  worker registry.
- A user-defined or dynamically generated output schema.
- Arbitrary providers or provider selection in JSON.
- Tool calling, conversations, memory, streaming, queues, persistence, or job
  scheduling.
- Authentication, authorization, rate limiting, and production observability.
- A new command-line interface. The HTTP endpoint is the V1 external interface.
- Evaluating factual model quality. That needs a separate curated evaluation
  dataset; deterministic unit tests only verify application behavior.

## 4. Configuration contract

Proposed V1 file, shown with representative values:

```json
{
  "schema_version": 1,
  "model": "qwen3:1.7b",
  "instructions": "Extract the value requested by the task. Return only data matching the required schema.",
  "output_retries": 1,
  "request_timeout_seconds": 120
}
```

| Field | Type | V1 validation | Meaning |
| --- | --- | --- | --- |
| `schema_version` | integer | exactly `1` | Rejects incompatible future config formats explicitly. |
| `model` | string | stripped and non-empty | Ollama model name passed to `OllamaModel`. |
| `instructions` | string | stripped and non-empty | Stable instructions passed to the Pydantic AI agent. |
| `output_retries` | integer | `0` through `3` | Additional structured-output attempts after the initial attempt. |
| `request_timeout_seconds` | number | greater than `0`, at most `600` | Timeout passed through model settings for one provider request. |

All fields are required in V1 and unknown fields are rejected. Explicit fields
make a configuration reproducible and rejecting extras catches misspellings.
JSON is decoded as UTF-8 and validated before the model or API serves work.

Configuration discovery is a proposed decision:

1. `EXTRACTOR_CONFIG_PATH` identifies the file when set.
2. Otherwise the application uses `config/extractor.json`, resolved from the
   process working directory.
3. The file is loaded once during application composition, not for every request.

The testable configuration boundary is
`load_extractor_config(path: Path) -> ExtractorConfig`. The active worker accepts
the validated behavior values as explicit constructor arguments: `model`,
`instructions`, `output_retries`, and `request_timeout_seconds`. Application
composition is responsible for passing values from the loaded config to that
worker; the worker does not read the JSON file itself.

`OLLAMA_BASE_URL` remains an environment variable, with the current local default
of `http://localhost:11434`. It is deployment configuration rather than extractor
behavior and may later contain environment-specific network information. V1
normalizes it to exactly one `/v1` suffix for the Pydantic AI Ollama provider.

The JSON file must not contain credentials or secrets.

## 5. Invocation contract

### Programmatic interface

The active worker accepts a validated `WorkerRequest` and returns a
`WorkerResult`. The call remains synchronous in V1 to match the existing code:

```text
WorkerRequest(task, input_text)
    -> active extractor worker.run(...)
    -> WorkerResult
```

### HTTP interface

`POST /extract` accepts:

```json
{
  "task": "Extract the invoice number",
  "input_text": "Invoice FV/2026/10/22"
}
```

Successful response:

```json
{
  "success": true,
  "data": {"value": "FV/2026/10/22"},
  "error": null
}
```

Controlled extraction failure:

```json
{
  "success": false,
  "data": null,
  "error": "Extractor could not produce valid structured output."
}
```

V1 preserves the current HTTP behavior: a validated request receives a
`WorkerResult`, including controlled model failures, without introducing a new
HTTP error mapping. Invalid request bodies continue to use FastAPI/Pydantic's
request-validation response. A later API version may introduce typed error codes
and different HTTP statuses.

## 6. Output and prompt behavior

- The agent's static `instructions` come from the validated JSON configuration.
- `task` and `input_text` remain per-request user prompt content.
- The output type remains the concrete `ExtractionResult` Pydantic model.
- V1 keeps Pydantic AI's normal structured-output mechanism already exercised by
  the tests. Switching to native Ollama structured output is deferred until the
  chosen model and local Ollama version are tested for compatibility.
- `output_retries=N` means one initial output attempt plus at most `N` additional
  output attempts.
- A successful value should be stripped and non-empty. Making whitespace-only
  output invalid is a V1 contract tightening and requires a deliberate production
  model change by the user.
- A successful `WorkerResult` must contain data and no error. A failed result must
  contain an error and no data. Tightening these invariants is also an explicit
  implementation task, not an undocumented test workaround.

## 7. Failure behavior

| Failure | Required V1 behavior | Model request made? |
| --- | --- | --- |
| Missing config file | Fail application startup/readiness with the file path and failure category. | No |
| Invalid UTF-8 or malformed JSON | Fail startup with a configuration error; do not silently use defaults. | No |
| Invalid, missing, or unknown config field | Fail startup with field-level validation details. | No |
| Invalid HTTP request | FastAPI validation response; worker is not called. | No |
| Invalid structured output, retries available | Let Pydantic AI issue its output retry. | Yes |
| Invalid structured output, retries exhausted | Return failed `WorkerResult` with `Extractor could not produce valid structured output.` | Yes |
| Expected provider/API/connection/timeout failure | Return failed `WorkerResult` with `Model provider request failed.` | Attempted |
| Unexpected programming error | Propagate it so it is visible to tests and error reporting. | Possibly |

Public errors are intentionally stable and sanitized. Provider response bodies,
prompts, input documents, credentials, and stack traces must not be copied into
the response. Internal logging is useful but detailed logging policy is outside
this V1; it must not leak those values.

Implementation must identify the concrete timeout/transport exceptions produced
by the installed Pydantic AI and provider stack. It must not use a broad
`except Exception` to convert programmer errors into a misleading provider
failure.

## 8. Acceptance criteria

V1 is complete when all of the following are true:

1. A valid JSON config is loaded once and controls model, instructions, output
   retries, and provider-request timeout.
2. Missing, malformed, unsupported-version, incomplete, mistyped, and
   unknown-field configs fail before any model call.
3. The application has one active Pydantic AI extractor path; `POST /extract` no
   longer instantiates the legacy worker.
4. A valid request can return `{"success": true, "data": {"value": "..."},
   "error": null}` through both the worker and HTTP interfaces.
5. Whitespace-only extracted values are rejected.
6. An initially invalid model output can be corrected within the configured retry
   budget.
7. Retry exhaustion and simulated provider failure produce the documented,
   sanitized failed `WorkerResult` values.
8. Unexpected exceptions remain visible rather than being mislabeled.
9. Default tests are reproducible offline and prevent accidental real model
   requests.
10. An optional, documented Ollama smoke test proves the real local integration
    without becoming part of the default test suite.
11. README and architecture documentation describe the active implementation,
    not both paths as if both were current. This documentation update belongs to
    the final implementation milestone, not this planning-only change.

## 9. Decisions and remaining uncertainties

The following choices are proposed because they minimize migration risk:

- Keep `WorkerRequest`, `WorkerResult`, and `POST /extract` instead of inventing a
  new public interface.
- Keep Ollama as the sole V1 provider.
- Keep a fixed `ExtractionResult` instead of accepting schemas from JSON.
- Keep provider location in the environment and agent behavior in JSON.
- Normalize public error text instead of exposing third-party exception wording.
- Load configuration once and fail fast instead of changing behavior while the
  process is running.

Items to confirm during implementation:

- Whether config loading uses FastAPI lifespan state or a cached composition
  function. The externally visible requirement is load-once/fail-fast behavior.
- Which installed provider exception represents connection timeout in practice.
  Confirm it with an isolated test before finalizing the exception translation.
- Whether the legacy worker is deleted immediately after migration or retained
  temporarily as clearly non-active code. V1 must not leave two selectable
  production paths.
- The upper timeout and retry bounds are conservative guardrails, not limitations
  imposed by Pydantic AI. Change them only through an explicit contract decision.

## 10. Official references

- [Pydantic AI agents and instructions](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [Pydantic AI structured output](https://pydantic.dev/docs/ai/core-concepts/output/)
- [Pydantic AI output retries](https://pydantic.dev/docs/ai/core-concepts/retries/)
- [Pydantic AI Ollama provider](https://pydantic.dev/docs/ai/models/ollama/)
- [Pydantic AI exceptions](https://pydantic.dev/docs/ai/api/pydantic-ai/exceptions/)
- [Pydantic AI timeouts](https://pydantic.dev/docs/ai/core-concepts/timeouts/)
- [Pydantic model validation and extra fields](https://docs.pydantic.dev/latest/concepts/models/)
- [Python `json` module](https://docs.python.org/3/library/json.html)
