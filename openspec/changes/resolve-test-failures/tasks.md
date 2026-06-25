## 0. Revert WarmupState

- [ ] 0.1 Git revert commit `27952c7` (WarmupState introduction — "Implement model readiness gate and associated tests")
- [ ] 0.2 Git revert patch commits `8dc7579`, `e8de0ea`, `969326c` (WarmupState workaround patches)
- [ ] 0.3 Remove `tests/integration/test_query_gate.py` (14 gate tests, no longer relevant)
- [ ] 0.4 Remove `require_models` dependency and `WarmupState` imports from all route handlers (`src/api/routes/query/routes.py`, `src/api/routes/chat/routes.py`, `src/api/routes/documents/routes.py`)
- [ ] 0.5 Remove `src/domain/services/gate.py` and `src/domain/services/warmup.py` (if no other consumers remain after revert)
- [ ] 0.6 Remove WarmupState seeding from `prewarm_models` fixture in `tests/integration/conftest.py` (fixture still seeds actual singletons — updated in Task 2)
- [ ] 0.7 Verify clean compile: `uv run pytest --collect-only tests/integration/` passes without WarmupState references

## 1. Test Doubles Module (`tests/doubles/`)

- [ ] 1.1 Create `tests/doubles/__init__.py` with package docstring
- [ ] 1.2 Create `tests/doubles/embedder.py` with `TestEmbedder(Embedder)` implementing `embed_text()`, `embed_texts()`, `get_dimension()` — hash-based deterministic 768-dim vectors
- [ ] 1.3 Create `tests/doubles/llm.py` with `TestLLM` implementing `generate()` with default canned response and optional constructor override
- [ ] 1.4 Verify test doubles are importable from `tests/integration/` and `tests/unit/`

## 2. Extended `prewarm_models` Fixture (seed actual singletons)

- [ ] 2.1 In `tests/integration/conftest.py`, add imports for `TestEmbedder` and `TestLLM` from `tests.doubles`
- [ ] 2.2 Extend `prewarm_models` fixture to set `embedding._embedder_instance = TestEmbedder()` and `embedding._embedder_load_time = 0` (remove any remaining WarmupState seeding)
- [ ] 2.3 Extend `prewarm_models` fixture to set LLM singleton (locate correct module global via `src.domain.services.llm`)
- [ ] 2.4 Verify the extended fixture completes in under 100ms
- [ ] 2.5 Run document upload tests in isolation and confirm processing completes in under 5s

## 3. Singleton Isolation (Warmup Tests)

- [ ] 3.1 In `tests/integration/test_embedder_warmup.py`, add `isolate_global_state` autouse fixture that saves/restores `_embedder_instance` (WarmupState no longer exists for this to reset)
- [ ] 3.2 In `tests/integration/test_dspy_warmup.py`, add `isolate_global_state` autouse fixture with same save/restore pattern
- [ ] 3.3 Run each warmup test file in isolation and verify all pass
- [ ] 3.4 Run warmup test files after other integration tests and verify all pass (no global state pollution)

## 4. Production Bug Fix: `asyncio.to_thread` in `get_embedder()`

- [ ] 4.1 In `src/domain/services/embedding.py`, wrap `SentenceTransformerEmbedder()` constructor call in `await asyncio.to_thread(...)`
- [ ] 4.2 Add `import asyncio` at top of `embedding.py` if not already present
- [ ] 4.3 Verify existing unit tests for `get_embedder()` still pass (mocked tests unaffected)
- [ ] 4.4 Run document upload with real server (manual) to verify no regression in startup behavior

## 5. Shared `wait_for_document` Helper Consolidation

- [ ] 5.1 Audit all 7 copy-pasted `upload_and_wait_for_document` implementations across integration test files for behavioral differences (poll interval, timeout, custom assertions)
- [ ] 5.2 Add shared `wait_for_document` helper to `tests/integration/conftest.py` with support for all identified parameter variations
- [ ] 5.3 Replace each local `upload_and_wait_for_document` with import from `tests.integration.conftest` in all 7 test files
- [ ] 5.4 Verify none of the 7 test files have remaining local `async def upload_and_wait` definitions

## 6. Investigate and Fix Remaining Independent Failures

- [ ] 6.1 Run the full integration suite after Tasks 0-5 and collect all remaining failures
- [ ] 6.2 Categorize each remaining failure: test bug (incorrect assertion) or production bug (code defect)
- [ ] 6.3 Fix all confirmed test bugs
- [ ] 6.4 Fix all confirmed production bugs
- [ ] 6.5 If any failure requires a non-trivial fix exceeding this change's scope, document and add `@pytest.mark.skip` with reason

## 7. Full Suite Verification

- [ ] 7.1 Run full integration suite and confirm 0 failures
- [ ] 7.2 Run full test suite (including unit tests) and confirm no regressions
- [ ] 7.3 Run `uv run pytest -m "not slow"` to confirm fast-mode works without smoke tests
- [ ] 7.4 Verify warmup tests pass in both isolation and full-suite contexts
