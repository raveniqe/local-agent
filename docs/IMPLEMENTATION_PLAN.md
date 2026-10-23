# Extractor V1 implementation plan

This plan implements the contract in [EXTRACTOR_SPEC.md](EXTRACTOR_SPEC.md) as a
series of small learning milestones. Production Python remains user-authored.
Codex reviews each attempt and may add tests or fixtures only when explicitly
asked.

## Working sequence

```text
validated JSON config
        |
        v
compose one Pydantic AI Agent
        |
        v
PydanticExtractorWorker.run(WorkerRequest)
        |
        v
WorkerResult
        ^
        |
POST /extract
```

The migration should move the HTTP endpoint onto this path. It should not add a
registry or abstractions for hypothetical future workers.

## Milestone 0: Preserve the baseline

Goal: make current behavior and migration gaps explicit before production edits.

Verified baseline:

- The worktree was clean on branch `experiment/pydantic-ai-extractor` when this
  plan was prepared.
- `tests/workers/test_extractor.py` passes 14 tests.
- The API still constructs the legacy `ExtractorWorker` and custom
  `OllamaClient`.
- The Pydantic AI worker has hard-coded model and instructions.
- Existing API tests prove the legacy path, not the intended V1 path.

Exit criteria:

- The user agrees with the V1 scope and proposed configuration contract.
- Any disagreement about public errors, timeout, or config discovery is resolved
  in the specification before code is changed.

## Milestone 1: Configuration boundary

Goal: load and validate the exact JSON contract independently from the agent.

User implementation tasks:

1. Define a focused Pydantic configuration model with unknown fields forbidden.
2. Implement a loader that accepts an explicit path, decodes JSON, and returns the
   validated model.
3. Keep path discovery (`EXTRACTOR_CONFIG_PATH` and the default path) separate
   from parsing so tests can pass temporary paths directly.
4. Preserve the original exception as a cause while exposing a clear
   configuration failure category. Do not silently fall back to defaults.

Design checkpoint:

- The loader knows nothing about FastAPI, workers, or Ollama.
- The config model does not contain runtime `task` or `input_text`.
- No generic config framework is introduced.

Exit criteria:

- A valid file produces the expected typed settings.
- Every invalid-config acceptance case fails before an agent can be created.
- Unit tests use temporary files and no network.

## Milestone 2: Agent composition from configuration

Goal: create the existing Pydantic AI worker from validated settings.

User implementation tasks:

1. Move model name and instructions out of hard-coded constructor defaults.
2. Pass `output_retries` to the agent's output retry setting.
3. Pass `request_timeout_seconds` through Pydantic AI model settings.
4. Build the Ollama provider URL from `OLLAMA_BASE_URL`, guaranteeing one `/v1`
   suffix.
5. Load configuration once at application composition. Prefer FastAPI lifespan
   state if it remains simple; a cached dependency is acceptable if it has the
   same fail-fast and test-isolation behavior.

Design checkpoint:

- There is still one concrete extractor, not a factory registry.
- Provider URL stays outside the JSON behavior config.
- Tests can inject or override the agent without starting Ollama.

Exit criteria:

- Tests can prove that each JSON behavior field reaches the intended Pydantic AI
  setting.
- Repeated requests do not reread the config or recreate uncontrolled state.

## Milestone 3: Output and failure contract

Goal: make success and expected failures predictable at the worker boundary.

User implementation tasks:

1. Tighten `ExtractionResult.value` so whitespace-only output is invalid.
2. Tighten `WorkerResult` invariants: success requires data/no error; failure
   requires error/no data.
3. Translate exhausted structured-output retries into the documented stable
   error.
4. Determine the actual provider and timeout exception types for the installed
   versions, then translate only those expected failures.
5. Leave unexpected exceptions uncaught.

Design checkpoint:

- Do not expose raw Pydantic AI or provider messages as the public contract.
- Do not add an error hierarchy or broad exception middleware for V1.
- If an existing assertion conflicts with the newly approved contract, explain
  the contract change first; never edit the assertion solely to get green tests.

Exit criteria:

- Success and failure invariants are enforced by validation.
- Retry exhaustion, provider failure, and timeout are distinguishable in tests
  from unexpected programming errors.
- Responses contain no provider body, prompt, input text, or stack trace.

## Milestone 4: Activate the Pydantic AI path

Goal: make `POST /extract` use the configured Pydantic extractor.

User implementation tasks:

1. Change application composition and dependency typing to the Pydantic worker.
2. Preserve the existing request and response JSON shapes.
3. Update API tests so they prove the intended worker is active, using dependency
   injection rather than a live model.
4. Decide whether to remove the legacy worker immediately or retain it briefly as
   clearly inactive migration code. Do not expose a runtime switch between them.

Exit criteria:

- One code path serves both programmatic and HTTP extraction.
- No default test contacts Ollama.
- API tests would fail if the application were accidentally rewired to the old
  worker.

## Milestone 5: Reproducibility and handoff

Goal: prove the documented V1 and remove stale descriptions.

User implementation tasks:

1. Add a safe example JSON configuration with no environment-specific secrets.
2. Run the deterministic default suite from a clean checkout.
3. Run the optional live Ollama smoke test separately and record prerequisites.
4. Update README architecture, setup, configuration, and limitations after the
   active path is real.
5. Resolve or document the current event-loop deprecation warning if it remains;
   do not let warning cleanup expand the V1 scope.

Exit criteria:

- Every item in the specification's acceptance criteria is demonstrated by an
  automated test, except the explicitly manual live smoke check.
- A new contributor can configure and invoke the extractor without reading the
  implementation.
- `git diff` contains only reviewed, intentional changes.

## Suggested review rhythm

For each milestone:

1. The user implements one small slice.
2. Codex reviews behavior, boundaries, and relevant official documentation.
3. The user corrects the implementation.
4. Tests are added or adjusted only for the agreed behavior.
5. The milestone is committed separately if the user chooses to commit it.

This keeps authorship with the user and makes failures useful learning signals.

## Explicitly deferred work

Park these ideas until V1 passes its acceptance criteria:

- CLI extraction command.
- Config hot reload.
- Multiple schemas, models, providers, or extractor types.
- Native-output optimization and model capability detection.
- Typed/versioned API error objects.
- Async endpoint/worker migration.
- Evaluation framework, tracing backend, persistence, and deployment automation.
