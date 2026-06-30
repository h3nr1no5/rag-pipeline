## Why

The LangChain RAG pipeline takes ~3 minutes per query, making the UI feel sluggish and unusable for interactive use. Deep code review reveals 4 likely bottlenecks: (1) duplicate SentenceTransformer embedder instance in the LangChain retriever, (2) full chunk+embedding re-load from SQLite on every query, (3) FAISS/BM25 index rebuilt from scratch on document set change, (4) two separate cross-encoder passes (rerank + verification) with suboptimal batching. Before any optimization, we need structured profiling to confirm which bottlenecks actually dominate.

## What Changes

1. **StepTimer profiling utility** — Add async context manager to `src/core/logging.py` that wraps pipeline steps and logs `[PROFILE] step_name: XXXXms` for quantitative timing
2. **Instrument LangChain pipeline** (`chain_langchain.py:generate()`) — Profile 5 steps: `retrieve`, `build_prompt`, `llm_generate`, `verify`, `clean_response`
3. **Instrument LlamaIndex pipeline** (`retrieval_llamaindex.py:generate()` / `_retrieve_and_rerank()`) — Profile 6 steps: `retrieve`, `ensure_components`, `hybrid_search`, `rerank`, `build_prompt`, `llm_generate`
4. **Real-model integration tests** — New `tests/integration/real_models/` directory with conftest that keeps real LLM/embedder/cross-encoder singletons (no mocking), tests exercising both pipelines end-to-end
5. **Capture baseline profile** — Run tests with `--log-cli-level=INFO | grep PROFILE`, save to `before_profile.log`
6. **Optimizations** — Apply 4 optimizations in sequence:
   - Share SentenceTransformer embedder singleton with LangChain retriever
   - Cache retriever by unique document set (avoid rebuild on repeated queries)
   - Batch cross-encoder predictions (single `model.predict()` call)
   - Eager model loading (await in lifespan, not background task)
7. **Capture after profile** — Run same tests, save to `after_profile.log`, diff against baseline
8. **Update AGENTS.md** — Add new test commands for real-model tests

## Capabilities

### New Capabilities
- `pipeline-profiling`: Structured step-level timing for LangChain and LlamaIndex RAG pipelines via StepTimer async context manager. Logs `[PROFILE] step_name: XXXXms` lines for instrumentation points. Includes real-model integration tests that exercise pipelines with live ML models (LLM, embedder, cross-encoder) for accurate profiling.

### Modified Capabilities
*(None — no existing specs in `openspec/specs/`)*

## Impact

- **`src/core/logging.py`** — Add `StepTimer` async context manager class
- **`src/domain/services/chain_langchain.py`** — Instrument `LangChainQAChain.generate()` with StepTimer for 5 steps
- **`src/domain/services/retrieval_llamaindex.py`** — Instrument `LlamaIndexRetriever.generate()` and `_retrieve_and_rerank()` with StepTimer for 6 steps
- **`src/domain/services/retrieval_langchain.py`** — Optimization: share embedder singleton (`_ProjectEmbeddingFunction` uses `embedding.load_embedder_sync()`)
- **`src/domain/services/verification.py`** — Optimization: batch cross-encoder predictions
- **`src/api/routes/query/routes.py`** — Optimization: cache retriever by doc set, eager model loading in lifespan
- **`tests/integration/real_models/`** — New test directory with conftest.py, test_langchain_integration.py, test_llamaindex_integration.py
- **`AGENTS.md`** — Add new test commands for real-model test runs
