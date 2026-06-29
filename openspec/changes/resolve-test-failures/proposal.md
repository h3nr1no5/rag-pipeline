## Why

The integration test suite has ~58 cascading failures from a single root cause: document upload tests timeout because `get_embedder()` blocks synchronously loading the real SentenceTransformer model (~2-10s if cached, >>45s if not). This blocks the async event loop, preventing HTTP polling responses. Tests time out, documents remain "pending", and everything downstream of processed documents fails.

The WarmupState gate architecture that was added to mitigate this has been reverted (commit `ee91dde`), removing the redundant gate layer. Model readiness is now determined by the actual singleton state (`_embedder_instance is not None`), which is the always-correct ground truth.

Fixing the systemic issue (test doubles + `asyncio.to_thread`) is a prerequisite for trustworthy CI and rapid development iteration.

## What Changes

- **Phase 0 — Revert WarmupState**: ✅ COMPLETED (commit `ee91dde`). Git-revert `27952c7`, delete `gate.py`, `warmup.py`, `require_models` from routes, delete gate/warmup test files. Inline model loading as `_load_models()` in lifespan.
- **Phase 1 — Test Doubles**: Create `tests/doubles/` module with `TestEmbedder(Embedder)` and `TestLLM` — proper interface implementations producing deterministic pseudo-embeddings and responses.
- **Phase 2 — Singleton Seeding Fixture**: Add a session-scoped autouse fixture in `tests/integration/conftest.py` that seeds `_embedder_instance` with `TestEmbedder()` and the LLM singleton with `TestLLM()`. No WarmupState (it's gone).
- **Phase 3 — Isolation**: Add per-test singleton isolation fixtures in warmup test files to reset `_embedder_instance` before each test.
- **Phase 4 — Production Bug Fix**: Fix `get_embedder()`: wrap `SentenceTransformerEmbedder()` in `asyncio.to_thread()` so synchronous model loading does not block the event loop.
- **Phase 5 — Fix remaining independent failures**: Investigate and fix the remaining ~7 independent test failures (strategies CRUD, auth validation, chat/query validation).
- Integration test suite goes from ~118/208 passing to ~0 expected failures.

## Capabilities

### New Capabilities
- `test-doubles`: Shared deterministic implementations of `Embedder` and LLM interfaces in `tests/doubles/`, producing hash-based pseudo-embeddings and canned LLM responses that pass all downstream validation (dimension checks, normalization, FAISS indexing)
- `test-singleton-isolation`: Per-test fixtures that reset `_embedder_instance` before each warmup test, preventing cross-test pollution from session-scoped fixtures

### Modified Capabilities
- `test-seeding`: New session-scoped autouse fixture seeds actual singletons (`_embedder_instance`, `_llm_instance`) so `get_embedder()` returns immediately without blocking

### Removed Capabilities
- WarmupState and `require_models` gate: Reverted in Phase 0. Model readiness is determined by the actual singleton state, not a separate gate layer.

## Impact

- **Code**: `src/domain/services/embedding.py` — `asyncio.to_thread` wrapping; `gate.py`, `warmup.py`, `require_models` already removed
- **Tests**: `tests/doubles/` (new directory, 2-3 files), `tests/integration/conftest.py` (singleton-seeding fixture), `tests/integration/test_dspy_warmup.py`, `tests/integration/test_embedder_warmup.py` (isolation fixtures)
- **Infrastructure**: No new dependencies. TestEmbedder uses only stdlib math and the existing `Embedder` protocol interface.
- **Risk**: Low. Test doubles are well-understood pattern. The `asyncio.to_thread` fix is a net safety improvement. No production behavior changes other than the event loop no longer blocking.
