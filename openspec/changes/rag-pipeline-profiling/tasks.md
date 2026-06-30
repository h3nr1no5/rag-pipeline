## 0a. Instrumentation & Test Setup

- [x] 0a.1 Add `StepTimer` async context manager to `src/core/logging.py` — logs `[PROFILE] <name>: <duration_ms>ms` at INFO level, handles exceptions gracefully
- [x] 0a.2 Instrument `LangChainQAChain.generate()` in `src/domain/services/chain_langchain.py` — wrap 5 steps: `retrieve`, `build_prompt`, `llm_generate`, `verify`, `clean_response`
- [x] 0a.3 Instrument `LlamaIndexRetriever.generate()` and `_retrieve_and_rerank()` in `src/domain/services/retrieval_llamaindex.py` — wrap 6 steps: `retrieve`, `ensure_components`, `hybrid_search`, `rerank`, `build_prompt`, `llm_generate`
- [x] 0a.4 Create `tests/integration/real_models/` directory with `conftest.py` that overrides `seed_singletons` to no-op and keeps real ML models
- [x] 0a.5 Create LangChain integration test in `tests/integration/real_models/test_langchain_integration.py` — uploads a real doc, calls `LangChainQAChain.generate()`, asserts on 5 `[PROFILE]` lines
- [x] 0a.6 Create LlamaIndex integration test in `tests/integration/real_models/test_llamaindex_integration.py` — uploads a real doc, calls `LlamaIndexRetriever.generate()`, asserts on 6 `[PROFILE]` lines
- [x] 0a.7 Create test runner script `scripts/run_profile.sh` that runs real-model tests with `--log-cli-level=INFO` and pipes output through `grep PROFILE`
- [x] 0a.8 Add real-model test commands to `AGENTS.md` (fast-mode and full-profile variants)

## 0b. Baseline Profile Capture

- [x] 0b.1 Run `scripts/run_profile.sh` to save baseline profile to `before_profile.log`
- [x] 0b.2 Verify `before_profile.log` contains all expected `[PROFILE]` lines for both LangChain and LlamaIndex pipelines

## 1. Optimization — Share SentenceTransformer Embedder Singleton

- [ ] 1.1 Add `load_embedder_sync()` function to `src/domain/services/embedding.py` — synchronous variant that returns existing singleton (or loads synchronously if not yet loaded)
- [ ] 1.2 Modify `_ProjectEmbeddingFunction.embed_query()` in `src/domain/services/retrieval_langchain.py` to use the shared embedder singleton instead of creating its own `SentenceTransformer` instance
- [ ] 1.3 Verify unit tests still pass: `uv run pytest tests/unit/ -q`

## 2. Optimization — Cache Retriever by Document Set

- [ ] 2.1 Add `doc_set_cache: dict[frozenset[int], LangChainRetriever]` to `chain_langchain.py` alongside the `_qa_chain_instance` singleton
- [ ] 2.2 In `get_qa_chain()`, check cache before reinitializing — only rebuild BM25/FAISS if document set is not cached
- [ ] 2.3 Verify unit tests still pass: `uv run pytest tests/unit/ -q`

## 3. Optimization — Batch Cross-Encoder Predictions

- [ ] 3.1 Modify `LangChainRetriever.retrieve()` to collect all rerank candidate pairs and call `CrossEncoderReRanker.rerank()` once instead of per-candidate
- [ ] 3.2 Modify `ResponseVerifier.verify()` in `src/domain/services/verification.py` to collect all sentence-source pairs and call `cross_encoder.model.predict()` once, then assign scores back to individual (sentence, source) pairs
- [ ] 3.3 Verify unit tests still pass: `uv run pytest tests/unit/ -q`

## 4. Optimization — Eager Model Loading

- [ ] 4.1 In `src/api/main.py` lifespan handler, await `_load_models()` synchronously during startup instead of dispatching as `asyncio.create_task`
- [ ] 4.2 If not already called from lifespan, trigger `get_embedder()` and `get_llm()` eagerly at startup to pre-load models
- [ ] 4.3 Verify unit tests still pass: `uv run pytest tests/unit/ -q`

## 5. After Profile & Comparison

- [ ] 5.1 Run `scripts/run_profile.sh` to save after-optimization profile to `after_profile.log`
- [ ] 5.2 Run `diff before_profile.log after_profile.log` to compare per-step timings
- [ ] 5.3 Verify `ruff check` passes, `mypy src/` passes
