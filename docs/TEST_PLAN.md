# Extractor V1 test plan

## 1. Purpose

The default pytest suite proves configuration, application control flow,
validation, retry behavior, and stable failures without relying on Ollama or
model quality. A separate, explicitly executed live evaluation runner covers
real local Ollama integration and a small model-quality baseline.

Tests must remain reproducible, must not weaken assertions to accommodate an
implementation, and must fail if a real model request is attempted accidentally.

## 2. Separate testing strategies

| Strategy | Location and command | Network/model policy | Purpose |
| --- | --- | --- | --- |
| Deterministic pytest tests | `tests/`, run with the standard pytest command | Offline. Real model requests are blocked. | Verify configuration, validation, control flow, retries, failure translation, and API wiring. |
| Live LLM evaluation | `scripts/evaluate_extractor_models.py`, executed explicitly and never through standard pytest | Real Ollama calls are expected. | Compare extraction accuracy, variability, failures, and latency for selected models. |

These strategies must not share a default entry point. Files under `scripts/`
must not be named or structured for pytest discovery, and standard pytest must
never start Ollama, download a model, or send a real LLM request. Conversely,
live outcomes are observations about a real model, not deterministic pytest
assertions.

The focused live evaluation runner is implemented. It contains a small synthetic
English/Polish dataset; it is not a general chaos platform and is not part of the
default pytest suite.

## 3. Deterministic pytest layers

### A. Configuration model and loader tests

Use temporary JSON files. No agent, HTTP application, or network is needed.

Covered cases:

| Case | Expected result |
| --- | --- |
| Complete valid config | Typed configuration with exact values. |
| Missing file | Clear configuration error; cause retained. |
| Invalid UTF-8 | Clear decoding/configuration error. |
| Malformed JSON | Clear configuration error based on `JSONDecodeError`. |
| Root is not an object | Validation failure. |
| Missing required field | Field-level validation failure. |
| Unknown field or misspelling | Validation failure, not silent ignore. |
| `schema_version` other than `1` | Validation failure. |
| Blank `model` or `instructions` | Validation failure after trimming. |
| Retry values `0` and `3` | Accepted boundary values. |
| Retry below `0`, above `3`, boolean, or non-integer | Validation failure. |
| Timeout at valid boundaries | Accepted. |
| Timeout zero, negative, above `600`, boolean, or non-number | Validation failure. |
| Repeated application request | Config loader is not called again. |

Do not assert an entire Pydantic error string. Assert the stable project error
category and the relevant field/location, because Pydantic's formatting is not
the project's public interface.

### B. Worker unit tests

Use Pydantic AI's `TestModel`, `FunctionModel`, or an agent override. Set
`ALLOW_MODEL_REQUESTS=False` for the test process so an incorrect test cannot
contact a real provider.

Keep the already valuable cases:

- Valid structured output becomes a successful `WorkerResult`.
- The user prompt contains both `task` and `input_text`.
- Invalid first output can be corrected on the configured retry.
- Retry exhaustion returns a controlled failure.

Covered V1 cases:

| Case | What the assertion proves |
| --- | --- |
| Configured instructions are present | JSON instructions, not a hidden constant, control the agent. |
| Configured model is used at composition | Model selection comes from JSON. |
| Native output mode | The agent requests provider-native structured output. |
| Thinking disabled | The extractor keeps `thinking=False` in agent model settings. |
| `output_retries=0` | No additional output attempt is made. |
| `output_retries=3` | The worker respects the upper configured budget. |
| Whitespace-only value | Output validation rejects semantically empty data. |
| Exhaustion | Exact project-owned public error is returned; raw library text is not exposed. |
| Simulated provider API failure | Sanitized provider failure is returned. |
| Simulated timeout | Sanitized provider failure is returned and the test does not wait in real time. |
| Unexpected exception | Exception propagates rather than being mislabeled. |
| Result invariants | Impossible success/data/error combinations raise validation errors. |

For `FunctionModel`, follow the installed Pydantic AI testing API. The repository's
current tests use asynchronous callbacks where required by the sandbox while the
production-facing worker call remains synchronous.

### C. API integration tests

Use FastAPI's test client and dependency overrides/fakes. These tests verify
wiring, not model intelligence.

Covered cases:

- Valid request reaches the Pydantic extractor dependency and preserves the
  success response shape.
- Controlled invalid-output failure preserves the documented failed response.
- Controlled provider failure preserves the documented failed response.
- Blank or missing `task` returns request validation failure without calling the
  worker.
- Blank or missing `input_text` returns request validation failure without
  calling the worker.
- An unexpected worker exception is not converted into a successful HTTP body.
- Worker composition fails before a model request for invalid configuration.
- A regression that reintroduces the legacy custom worker into the endpoint is
  detected.

The API tests target `PydanticExtractorWorker` and preserve the public request
and response contract while replacing the real model boundary.

## 4. Test isolation rules

- No default test reads a developer's real config or `.envrc`.
- Tests receive explicit temporary paths and restore environment changes.
- No default test depends on test execution order.
- Do not sleep to simulate timeout; raise the expected exception from a fake.
- Do not assert private Pydantic AI internals when observable behavior is enough.
- Do not record real prompts, documents, provider bodies, or environment values
  in snapshots or failure output.
- A test may count model calls to prove retries, but should not assert incidental
  formatting unless formatting is part of the contract.

## 5. Live LLM evaluation runner

The explicit runner lives at `scripts/evaluate_extractor_models.py`. It reads the
validated extractor configuration, uses the production worker, and can override
the model from the command line without creating a second config file. It must
not be imported or executed by pytest.

Useful commands:

```bash
uv run --env-file .env python scripts/evaluate_extractor_models.py --list-cases

PYDANTIC_AI_NO_BANNER=1 uv run --env-file .env \
  python scripts/evaluate_extractor_models.py \
  --model qwen3:4b-instruct \
  --model gemma3:4b \
  --repeat 3
```

The runner supports filtering by case, language, and difficulty. For each run it
records exact-value success, wrong values, controlled worker errors, unexpected
exceptions, and elapsed time. It exits non-zero when any evaluated run fails.

The implemented dataset covers:

1. English and Polish extraction cases.
2. Easy, medium, and hard examples with exact expected values.
3. Distractors, replaced identifiers, internal punctuation, dates, amounts, and
   identifiers.
4. Repeated execution to observe output variability.
5. Multiple model comparison with accuracy and latency summaries.

Deliberate provider outage, unavailable-model, timeout, malformed-input, and
ambiguous-input scenarios remain future extensions to the live dataset. The
runner already records controlled worker errors and unexpected exceptions if
they occur during an ordinary evaluation.

Live results must not be treated as deterministic unit-test evidence. They can
inform model selection, evaluation cases, or prompt changes, but those changes
need their own reviewed contract.

The V1 selection run used 18 English/Polish cases repeated three times. Both
`qwen3:4b-instruct` and `gemma3:4b` produced 54/54 exact matches in that
environment; Qwen averaged 4.1 seconds and Gemma 5.4 seconds. This observation
supports the current extractor model choice but does not predict performance on
future tools or open-ended tasks.

## 6. Recommended execution groups

The project uses separate entry points rather than pytest markers:

```text
pytest: config unit + worker unit + API integration (offline)
live:   explicit scripts/ runner with real Ollama (not pytest)
future: larger representative datasets and open-tool evaluations
```

During development, run the narrowest relevant module first, then the entire
default suite. The deterministic V1 verification uses the documented pytest
command without a running Ollama service. Any later live run is invoked and
reported separately.

## 7. Acceptance traceability

| Specification requirement | Primary evidence |
| --- | --- |
| JSON controls all four behavior settings | Config and composition tests. |
| Invalid config fails before model call | Loader tests plus a no-call assertion. |
| One active Pydantic extractor | API dependency regression test. |
| Valid structured result | Worker unit and API integration tests. |
| Retry budget and correction | `FunctionModel` call-sequence tests. |
| Stable retry-exhaustion failure | Worker and API failure tests. |
| Stable provider/timeout failure | Simulated exception tests. |
| Unexpected bugs remain visible | Propagation test. |
| No accidental network | Global model-request block plus fakes. |
| Real Ollama compatibility | Explicit live evaluation runner under `scripts/`. |

## 8. Quality tests deferred beyond V1

Unit tests cannot establish whether a real model extracts well across varied
documents. The current live runner is a small synthetic baseline. After V1,
expand evaluation with representative inputs, ambiguous and negative cases, and
explicit scoring rules for each new capability. Keep those evaluations separate
from application control-flow tests.

Some environments emit a non-failing `pydantic_graph` event-loop deprecation
warning during synchronous agent tests. It does not change the V1 result, but it
should be monitored when dependencies are upgraded.

## 9. Official references

- [Pydantic AI testing](https://pydantic.dev/docs/ai/guides/testing/)
- [Pydantic AI structured output](https://pydantic.dev/docs/ai/core-concepts/output/)
- [Pydantic AI retries](https://pydantic.dev/docs/ai/core-concepts/retries/)
- [Pydantic AI exceptions](https://pydantic.dev/docs/ai/api/pydantic-ai/exceptions/)
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
- [pytest temporary paths](https://docs.pytest.org/en/stable/how-to/tmp_path.html)
