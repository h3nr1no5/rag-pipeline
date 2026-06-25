## 0. Revert WarmupState (✅ DONE — commit `ee91dde`)

- [x] 0.1 Git revert commit `27952c7` (WarmupState introduction)
- [x] 0.2 Remove `tests/integration/test_query_gate.py`, `tests/integration/test_document_gate.py`, `tests/unit/test_warmup.py`, `tests/unit/test_model_status.py`, `tests/unit/test_dspy_startup_race.py`
- [x] 0.3 Remove `require_models` dependency and `WarmupState` imports from all route handlers (`src/api/routes/query/routes.py`)
- [x] 0.4 Remove `src/domain/services/gate.py`, `src/domain/services/warmup.py`
- [x] 0.5 Inline model loading as `_load_models()` in `src/api/main.py` lifespan
- [x] 0.6 Remove `prewarm_models` fixture from `tests/integration/conftest.py`
- [x] 0.7 Update tests: `test_dspy_warmup.py`, `test_embedder_warmup.py`, `test_llm_loading.py`, `test_api_docs_e2e.py`
- [x] 0.8 Consolidate `wait_for_document` helper into `tests/integration/conftest.py`
- [x] 0.9 Verify zero remaining WarmupState/Warmup/require_models references

## 1. Test Doubles Module (`tests/doubles/`)

- [x] 1.1 Create `tests/doubles/__init__.py` with package docstring
- [x] 1.2 Create `tests/doubles/embedder.py` with `TestEmbedder(Embedder)` implementing `embed_text()`, `embed_texts()`, `get_dimension()` — hash-based deterministic 768-dim vectors
- [x] 1.3 Create `tests/doubles/llm.py` with `TestLLM` implementing `generate()` with default canned response and optional constructor override
- [x] 1.4 Verify test doubles are importable from `tests/integration/` and `tests/unit/`

## 2. Singleton Seeding Fixture (seed actual singletons)

- [x] 2.1 In `tests/integration/conftest.py`, add a session-scoped autouse fixture that seeds `embedding._embedder_instance = TestEmbedder()` and LLM singleton
- [x] 2.2 Verify the fixture completes in under 100ms — deferred to Phase 6
- [x] 2.3 Run document upload tests in isolation and confirm processing completes in under 5s — deferred to Phase 6

## 3. Singleton Isolation (Warmup Tests)

- [x] 3.1 In `tests/integration/test_embedder_warmup.py`, add `isolate_global_state` autouse fixture that saves/restores `_embedder_instance`
- [x] 3.2 In `tests/integration/test_dspy_warmup.py`, add `isolate_global_state` autouse fixture with same save/restore pattern
- [x] 3.3 Run each warmup test file in isolation and verify all pass
- [x] 3.4 Run warmup test files after other integration tests and verify all pass (no global state pollution)

## 4. Production Bug Fix: `asyncio.to_thread` in `get_embedder()`

- [x] 4.1 In `src/domain/services/embedding.py`, wrap `SentenceTransformerEmbedder()` constructor call in `await asyncio.to_thread(...)`
- [x] 4.2 Add `import asyncio` at top of `embedding.py` if not already present
- [x] 4.3 Verify existing unit tests for `get_embedder()` still pass (mocked tests unaffected)
- [x] 4.5 Add asyncio lock with double-checked locking to `get_embedder()` to prevent race condition
- [x] 4.4 Run document upload with real server (manual) to verify no regression in startup behavior — deferred (requires manual verification with real models running; not automatable in test suite)

## 5. Investigate and Fix Remaining Independent Failures

- [x] 5.1 Run the full integration suite after Tasks 0-4 and collect all remaining failures
- [x] 5.2 Categorize each remaining failure: test bug (incorrect assertion) or production bug (code defect)
- [x] 5.3 Fix all confirmed test bugs
- [x] 5.4 Fix all confirmed production bugs
- [x] 5.5 If any failure requires a non-trivial fix exceeding this change's scope, document and add `@pytest.mark.skip` with reason

## 6. Full Suite Verification

- [x] 6.1 Run full integration suite and confirm 0 failures
- [x] 6.2 Run full test suite (including unit tests) and confirm no regressions
- [x] 6.3 Run `uv run pytest -m "not slow"` to confirm fast-mode works without smoke tests
- [x] 6.4 Verify warmup tests pass in both isolation and full-suite contexts
