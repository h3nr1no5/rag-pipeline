## 1. Create RealisticTestLLM Test Double

- [ ] 1.1 In `tests/doubles/llm.py`, add `RealisticTestLLM` class implementing the `LLM` protocol with `_extract_source_texts()` helper that parses `[Source N]:` lines from the prompt
- [ ] 1.2 Implement `RealisticTestLLM.generate()` — returns `f"Based on the provided material: {sources[0][:200]}"` when sources are found, or `"I don't have enough information to answer this question."` when no sources exist
- [ ] 1.3 Implement `RealisticTestLLM.generate_stream()` — yields the result of `generate()` once
- [ ] 1.4 Add unit tests for `RealisticTestLLM` in `tests/doubles/test_llm_doubles.py` — verify it correctly parses `[Source N]:` chunks from a realistic `build_prompt()` output format and returns fallback when no sources present
- [ ] 1.5 Run unit tests: `uv run pytest tests/unit/`

## 2. Override seed_singletons in E2E Test Module

- [ ] 2.1 In `tests/integration/test_rag_pipelines_e2e.py`, after existing module-level patches, add module-level code to reseed the LLM singleton: `llm_mod._llm_instance = RealisticTestLLM()`
- [ ] 2.2 Remove or bypass the `seed_singletons` contamination by ensuring the reseeding happens after the session-scoped fixture has run but before any test function executes (module-level code runs at import time, which is correct for this pattern)
- [ ] 2.3 Verify the reseeding does not break other tests in the integration test directory — the `seed_singletons` fixture still runs first, but the E2E module overrides it for its own tests only

## 3. Strengthen E2E Test Assertions

- [ ] 3.1 In `test_cosine_pipeline`: replace `assert len(result["answer"]) > 0` with assertion checking answer is NOT the canned `TestLLM` response AND contains the word "material"
- [ ] 3.2 In `test_langchain_pipeline`: same assertion strengthening
- [ ] 3.3 In `test_llamaindex_pipeline`: same assertion strengthening
- [ ] 3.4 In `test_api_docs_pipeline`: add assertion that `result["answer"]` is NOT `"I don't have enough information to answer this question."` (already present — verify it still passes with `RealisticTestLLM`)
- [ ] 3.5 Run slow E2E tests: `uv run pytest tests/integration/test_rag_pipelines_e2e.py -v -m slow` (expect all 4 to pass with meaningful answers)

## 4. Fix Frontend Silent Auth Failure

- [ ] 4.1 In `client/utils/query.py`, update `query_sync()` — change the `if not st.session_state.get("token"):` guard to return a dict with `"error": "not_authenticated"` key
- [ ] 4.2 In `client/utils/query.py`, update `query_langchain_sync()` — same change
- [ ] 4.3 In `client/utils/query.py`, update `query_llamaindex_sync()` — same change
- [ ] 4.4 In `client/utils/query.py`, update `api_docs_query()` — same change
- [ ] 4.5 In `client/pages/3_💬_Chat.py`, in the concurrent dispatch results section (around lines 531-581), add error checking: if `"error" in result`, show `st.error()` instead of rendering a fake answer

## 5. Verify

- [ ] 5.1 Run full test suite excluding slow: `uv run pytest -v -m "not slow"`
- [ ] 5.2 Run slow E2E tests: `uv run pytest tests/integration/test_rag_pipelines_e2e.py -v -m slow`
- [ ] 5.3 Run linting: `uv run ruff check .`
- [ ] 5.4 Run type checking: `uv run mypy src/ tests/doubles/`
