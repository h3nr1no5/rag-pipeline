## ADDED Requirements

### Requirement: StepTimer provides structured step-level profiling

The system SHALL provide a `StepTimer` async context manager class in `src/core/logging.py` that measures elapsed time for a code block and logs the duration.

- `StepTimer` SHALL accept a `name: str` parameter identifying the profiled step
- `StepTimer` SHALL log on exit at INFO level in format: `[PROFILE] <name>: <duration_ms>ms`
- `StepTimer` SHALL measure wall-clock time using `time.perf_counter()`
- `StepTimer` SHALL round duration to the nearest integer millisecond
- `StepTimer` SHALL have sub-millisecond overhead (no syscalls on hot path, no I/O until context exit)
- `StepTimer` SHALL handle exceptions gracefully — if the wrapped block raises, the timer SHALL still log the elapsed time before propagating the exception

#### Scenario: Timer logs duration after successful block
- **WHEN** `async with StepTimer("my_step"): await asyncio.sleep(0.05)`
- **THEN** a log entry is emitted containing `[PROFILE] my_step: 5Xms` (approximately 50ms)

#### Scenario: Timer logs duration even when block raises
- **WHEN** `async with StepTimer("failing_step"): raise ValueError("boom")`
- **THEN** the ValueError propagates AND a `[PROFILE] failing_step: Xms` log entry is emitted before propagation

### Requirement: LangChain pipeline is instrumented with StepTimer probes

`LangChainQAChain.generate()` in `src/domain/services/chain_langchain.py` SHALL wrap each of its sub-steps with `StepTimer` for profiling. The following steps SHALL be individually timed:

- `retrieve`: Wraps the `retriever.retrieve(question)` call
- `build_prompt`: Wraps the `build_prompt()` call
- `llm_generate`: Wraps the `llm.generate()` call
- `verify`: Wraps the `ResponseVerifier.verify()` call
- `clean_response`: Wraps the `clean_response()` call

The StepTimer wrapping SHALL not change any functional behavior — return values, error handling, and step ordering SHALL remain identical.

#### Scenario: All five LangChain steps emit PROFILE lines
- **WHEN** `generate()` is called with a valid question and document set
- **THEN** the log output contains exactly 5 `[PROFILE]` lines: one each for `retrieve`, `build_prompt`, `llm_generate`, `verify`, and `clean_response` (in that order)

#### Scenario: StepTimer does not alter return value or exception behavior
- **WHEN** `generate()` succeeds normally
- **THEN** the return value (sources dict, verification results, cleaned answer) SHALL be identical to the un-instrumented version
- **WHEN** any step raises an exception
- **THEN** the exception SHALL propagate from `generate()` as before (StepTimer SHALL NOT swallow it)

### Requirement: LlamaIndex pipeline is instrumented with StepTimer probes

`LlamaIndexRetriever.generate()` and `_retrieve_and_rerank()` in `src/domain/services/retrieval_llamaindex.py` SHALL wrap their sub-steps with `StepTimer` for profiling. The following steps SHALL be individually timed:

- `retrieve` (top-level): Wraps the entire `_retrieve_and_rerank()` call from `generate()`
- `ensure_components`: Wraps the FAISS index and BM25 retriever initialization/validation
- `hybrid_search`: Wraps both dense (FAISS) and sparse (BM25) retrieval calls and RRF fusion
- `rerank`: Wraps the `CrossEncoderReRanker.rerank()` call
- `build_prompt`: Wraps the prompt construction
- `llm_generate`: Wraps the `llm.generate()` call

The StepTimer wrapping SHALL not change any functional behavior — return values, error handling, and step ordering SHALL remain identical.

#### Scenario: All six LlamaIndex steps emit PROFILE lines
- **WHEN** `generate()` is called with a valid question and document set
- **THEN** the log output contains exactly 6 `[PROFILE]` lines: one each for `retrieve`, `ensure_components`, `hybrid_search`, `rerank`, `build_prompt`, and `llm_generate`

#### Scenario: StepTimer does not alter return value or exception behavior
- **WHEN** `generate()` succeeds normally
- **THEN** the return value SHALL be identical to the un-instrumented version
- **WHEN** any step raises an exception
- **THEN** the exception SHALL propagate from `generate()` as before

### Requirement: Real-model integration tests exercise both pipelines

A new test directory `tests/integration/real_models/` SHALL contain end-to-end tests that exercise the LangChain and LlamaIndex pipelines with real ML models (not mocked). The tests SHALL:

- Use a shared `conftest.py` that overrides the `seed_singletons` autouse fixture to no-op (keeping real LLM, embedder, cross-encoder singletons)
- Inherit DB setup (`setup_test_db`) and auth (`auth_client`) from parent conftest files
- Test LangChain pipeline via the actual `LangChainQAChain.generate()` method
- Test LlamaIndex pipeline via the actual `LlamaIndexRetriever.generate()` method
- Upload a real PDF document and use its chunks as retrieval context
- Assert on `[PROFILE]` log output, not on answer content (which is non-deterministic)
- Be marked with `@pytest.mark.slow` to allow exclusion from fast test runs

#### Scenario: LangChain real-model test emits PROFILE lines
- **WHEN** a document is uploaded and a question is asked against the LangChain pipeline
- **THEN** log output contains 5 `[PROFILE]` lines matching: `retrieve`, `build_prompt`, `llm_generate`, `verify`, `clean_response`

#### Scenario: LlamaIndex real-model test emits PROFILE lines
- **WHEN** a document is uploaded and a question is asked against the LlamaIndex pipeline
- **THEN** log output contains 6 `[PROFILE]` lines matching: `retrieve`, `ensure_components`, `hybrid_search`, `rerank`, `build_prompt`, `llm_generate`

### Requirement: StepTimer instrumentation stays in production code

The StepTimer probes added to `chain_langchain.py` and `retrieval_llamaindex.py` SHALL remain in the codebase permanently after profiling is complete. They SHALL NOT be removed after the baseline profile is captured, providing ongoing visibility into pipeline performance.

#### Scenario: StepTimer probes survive cleanup phase
- **WHEN** the profiling phase concludes and optimization begins
- **THEN** the StepTimer probes SHALL still be present in the instrumented source files
