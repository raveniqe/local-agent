# Extractor V1 test plan

## 1. Purpose

The default pytest suite proves configuration, application control flow,
validation, retry behavior, and stable failures without relying on Ollama or
model quality. A separate, explicitly executed Live LLM Chaos Test runner will
cover the real local integration after the JSON-configured extractor works.

Tests must remain reproducible, must not weaken assertions to accommodate an
implementation, and must fail if a real model request is attempted accidentally.

## 2. Separate testing strategies

| Strategy | Location and command | Network/model policy | Purpose |
| --- | --- | --- | --- |
| Deterministic pytest tests | `tests/`, run with the standard pytest command | Offline. Real model requests are blocked. | Verify configuration, validation, control flow, retries, failure translation, and API wiring. |
| Live LLM Chaos Tests | A dedicated runner under `scripts/`, executed explicitly and never through standard pytest | Real local Ollama calls are expected. | Explore model variability, malformed responses, ambiguous inputs, and provider availability. |

These strategies must not share a default entry point. Files under `scripts/`
must not be named or structured for pytest discovery, and standard pytest must
never start Ollama, download a model, or send a real LLM request. Conversely,
chaos outcomes are observations about a real model, not deterministic pytest
assertions.

The Chaos Test Suite is intentionally out of scope for the current test
implementation. No chaos runner or large prompt dataset should be created until
the JSON-configured Pydantic AI extractor is functional.

## 3. Deterministic pytest layers

### A. Configuration model and loader tests

Use temporary JSON files. No agent, HTTP application, or network is needed.

Required cases:

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

Add or refine these V1 cases:

| Case | What the assertion proves |
| --- | --- |
| Configured instructions are present | JSON instructions, not a hidden constant, control the agent. |
| Configured model is used at composition | Model selection comes from JSON. |
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

Required cases:

- Valid request reaches the Pydantic extractor dependency and preserves the
  success response shape.
- Controlled invalid-output failure preserves the documented failed response.
- Controlled provider failure preserves the documented failed response.
- Blank or missing `task` returns request validation failure without calling the
  worker.
- Blank or missing `input_text` returns request validation failure without
  calling the worker.
- An unexpected worker exception is not converted into a successful HTTP body.
- Application composition fails/readiness is denied for invalid configuration.
- A regression that reintroduces `ExtractorWorker` into the endpoint is detected.

The current API tests target the legacy worker. During the activation milestone,
change them because the approved production dependency changes, not merely to
make a failure disappear. Preserve assertions about the public request and
response contract wherever that contract is unchanged.

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

## 5. Live LLM Chaos Tests (future work)

The future explicit runner should live under `scripts/` and may include the
original live Ollama smoke scenario as its smallest case. It must document the
required Ollama version, configured model, config path, local base URL, and how
results are recorded. It must not be imported or executed by pytest.

Minimum future scenarios:

1. Successful extraction through a real configured Ollama model.
2. Repeated execution of the same input to observe output variability.
3. Malformed, incomplete, and ambiguous inputs.
4. Unavailable model, stopped Ollama, and request timeout.
5. Verification that every response still respects the public result envelope.

Chaos results must not be treated as deterministic unit-test evidence. They can
inform later evaluation cases or prompt changes, but those changes need their
own reviewed contract.

## 6. Recommended execution groups

The exact marker names can follow the project's conventions when implemented:

```text
pytest: config unit + worker unit + API integration (offline)
chaos:  explicit scripts/ runner with real Ollama (not pytest, future work)
future: model-quality evaluations
```

During development, run the narrowest relevant module first, then the entire
default suite. The deterministic V1 verification is from a clean checkout with
the same documented pytest command and without a running Ollama service. Any
later chaos run is invoked and reported separately.

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
| Real Ollama compatibility | Future explicit Live LLM Chaos Test runner under `scripts/`. |

## 8. Quality tests deferred beyond V1

Unit tests cannot establish whether a real model extracts well across varied
documents. After V1, create a small versioned evaluation dataset containing
representative inputs, expected values, ambiguous cases, and explicit scoring
rules. Keep that separate from application control-flow tests and do not make the
initial V1 depend on a general evaluation platform.

## 9. Official references

- [Pydantic AI testing](https://pydantic.dev/docs/ai/guides/testing/)
- [Pydantic AI structured output](https://pydantic.dev/docs/ai/core-concepts/output/)
- [Pydantic AI retries](https://pydantic.dev/docs/ai/core-concepts/retries/)
- [Pydantic AI exceptions](https://pydantic.dev/docs/ai/api/pydantic-ai/exceptions/)
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
- [pytest temporary paths](https://docs.pytest.org/en/stable/how-to/tmp_path.html)
