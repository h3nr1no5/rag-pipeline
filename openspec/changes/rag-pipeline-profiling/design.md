## Context

The LangChain RAG pipeline takes ~3 minutes per query end-to-end. Deep code review identified 4 suspected bottlenecks, but we lack structured timing data to confirm which dominate. Currently the only timing visibility is total request duration (from route handler), with no per-step breakdown.

The codebase already uses process-level singletons for the LLM, embedder, and cross-encoder (loaded lazily on first use). The LangChain pipeline lives in `src/domain/services/chain_langchain.py` (LangChainQAChain.generate()), and the LlamaIndex pipeline in `src/domain/services/retrieval_llamaindex.py` (LlamaIndexRetriever.generate()). Both share the same prompt builder, cross-encoder, and verification modules.

Integration tests live in `tests/integration/` with an existing `test_langchain_verification_integration.py` that uploads a real document and hits the real endpoint, but only measures total latency and uses mocked singletons.

## Goals / Non-Goals

**Goals:**
- Add a reusable `StepTimer` async context manager to `src/core/logging.py` for structured per-step timing
- Instrument `LangChainQAChain.generate()` with 5 timing probes: `retrieve`, `build_prompt`, `llm_generate`, `verify`, `clean_response`
- Instrument `LlamaIndexRetriever.generate()` and `_retrieve_and_rerank()` with 6 timing probes: `retrieve`, `ensure_components`, `hybrid_search`, `rerank`, `build_prompt`, `llm_generate`
- Create `tests/integration/real_models/` test directory with shared conftest that keeps real ML model singletons (no mocking), hosting both LangChain and LlamaIndex e2e tests
- Capture baseline `before_profile.log` with per-step timings for all pipeline steps
- Apply 4 optimizations in sequence: share embedder singleton, cache retriever by doc set, batch cross-encoder predictions, eager model loading
- Capture `after_profile.log` and diff against baseline to quantify improvement

**Non-Goals:**
- NOT changing the streaming endpoint behavior (still buffers full response)
- NOT adding distributed tracing or external observability tools
- NOT making architectural changes beyond the 4 scoped optimizations
- NOT adding end-to-end latency benchmarks as CI gates
- NOT profiling the cosine similarity or LlamaIndex backends beyond the LlamaIndex pipeline instrumented here

## Decisions

### Decision 1: StepTimer as async context manager only (no decorator variant)

**Chosen**: Single `async with StepTimer("name"):` context manager class in `src/core/logging.py`.
**Alternatives considered**: Decorator-based timing, manual `time.perf_counter()` pairs in each function.
**Rationale**: The pipeline code uses `await` within each step boundary, so an async context manager is the natural fit. It adds zero structural change to existing code — just wrapping existing blocks. A decorator would require refactoring to extract each step into its own function, which is more invasive than warranted for profiling instrumentation.

### Decision 2: StepTimer logs via `logging.getLogger()`, not a special callback

**Chosen**: Standard Python logging with a `[PROFILE]` prefix string.
**Alternatives considered**: Dedicated metrics callback, structlog event, in-memory dict accumulator.
**Rationale**: Simplest integration with existing test infrastructure. Tests already use `caplog` to assert on log messages. Using `[PROFILE]` prefix makes it trivially grep-able (`grep PROFILE`) and compatible with `--log-cli-level=INFO`. No new dependencies, no coupling to external systems.

### Decision 3: Real-model tests in new `tests/integration/real_models/` subdirectory

**Chosen**: Separate test directory with its own `conftest.py` that overrides `seed_singletons` to no-op.
**Alternatives considered**: (A) Modify existing `test_langchain_verification_integration.py` fixtures, (B) Add a `--run-real-models` marker, (C) Put tests in a separate top-level directory.
**Rationale**: Option B (marker) was rejected because real-model tests need different fixture behavior (no singleton mocking) and would complicate the existing conftest chain. A dedicated directory keeps the separation clean — the conftest there inherits from `tests/conftest.py` for DB setup and auth, but overrides the `seed_singletons` autouse fixture to keep real models. This also mirrors the existing pattern where `tests/integration/` has its own conftest.

### Decision 4: Optimization sequence is order-preserving per-codebase-state

**Chosen**: Apply optimizations strictly in sequence with each optimization building on the previous code state.
**Alternatives considered**: Independent parallel implementations merged at the end.
**Rationale**: Each optimization changes the same code paths (embedder sharing affects retriever initialization, retriever caching affects the same singleton, batching affects the same cross-encoder calls). Applying sequentially ensures each step can be verified independently and the before/after comparison measures cumulative improvement.

### Decision 5: Profiling instrumentation stays in production code permanently

**Chosen**: StepTimer probes remain in the codebase after profiling is done, providing ongoing visibility.
**Alternatives considered**: Remove StepTimer after baseline collected.
**Rationale**: Sub-millisecond overhead per probe is negligible. Keeping them means any future performance regression is immediately visible in test output. The `[PROFILE]` log lines are silent by default (INFO level, not WARNING) and only visible when explicitly requested.

### Decision 6: LangChain retriever cache uses `frozenset[int]` as key

**Chosen**: `dict[frozenset[int], LangChainRetriever]` mapping document ID sets to cached retriever instances, stored alongside the `_qa_chain_instance` singleton.
**Alternatives considered**: Single cache entry (invalidated on any doc change), LRU cache with max size.
**Rationale**: Document sets are immutable after request validation (route handler validates IDs), and `frozenset` is hashable. The number of unique document set combinations a user queries is typically very small (<5). An LRU would add unnecessary complexity for no measurable benefit at this scale.

## Risks / Trade-offs

- **[Risk] Real-model tests are slow and non-deterministic**: Each test may take 1-3 minutes due to real LLM inference. Model output quality varies. → **Mitigation**: Tests assert on timing output `[PROFILE]` lines, not on answer content. Tests marked with `@pytest.mark.slow` to allow fast-mode exclusion.
- **[Risk] StepTimer logging leaks into production**: `[PROFILE]` messages at INFO level could clutter production logs. → **Mitigation**: Log level is configurable; in production, the root logger typically defaults to WARNING. No sensitive data in profile messages.
- **[Risk] Optimization interdependency**: Later optimizations may depend on earlier ones, making the sequence fragile. → **Mitigation**: Each optimization task includes a verification step (tests still pass) before proceeding. If a task breaks something, it's caught before the next one starts.
- **[Risk] Cross-encoder model load on first query**: Eager loading adds startup latency. → **Mitigation**: Acceptable trade-off — startup is a one-time cost vs every-first-query latency tax. Applies to both embedder and cross-encoder models.
