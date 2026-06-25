## Why

The integration test suite has 71 remaining failures after the `test-fixes` change fixed the WarmupState seeding (eliminating 97 503 errors). The root cause is that `prewarm_models` only seeds the WarmupState gatekeeper but not the actual model singletons (`_embedder_instance`, `_llm_instance`), so background document processing blocks for seconds loading real models. ~58 failures cascade from this single issue, ~6 are global state pollution, and ~7 are genuine bugs in independent tests. Fixing this systemic issue is a prerequisite for trustworthy CI and rapid development iteration.

WarmupState itself introduced a design flaw: the gate and the actual singletons can drift apart (gate says "ready" but singleton is still `None`). This change reverts WarmupState entirely, removing the redundant gate layer and simplifying the architecture.

## What Changes

- **Phase 0 — Revert WarmupState**: Git-revert commit `27952c7` (WarmupState introduction) and related patch commits. Remove `test_query_gate.py` (14 tests), `src/domain/services/gate.py`, `require_models` from route handlers, and all WarmupState references.
- **Phase 1 — Test Doubles**: Create `tests/doubles/` module with `TestEmbedder(Embedder)` and `TestLLM` — proper interface implementations producing deterministic pseudo-embeddings and responses.
- **Phase 2 — Fixture Extension**: Update `prewarm_models` fixture in `tests/integration/conftest.py` to seed actual singletons (`_embedder_instance`, `_llm_instance`) so `get_embedder()` returns immediately without blocking. No WarmupState seeding (it's gone).
- **Phase 3 — Isolation**: Add per-test singleton isolation fixtures in warmup test files to reset `_embedder_instance` before each test.
- **Phase 4 — Production Bug Fix**: Fix `get_embedder()`: wrap `SentenceTransformerEmbedder()` in `asyncio.to_thread()` so synchronous model loading does not block the event loop.
- **Phase 5 — Consolidation**: Consolidate 7 duplicate `upload_and_wait_for_document` helpers into a shared fixture in `tests/integration/conftest.py`.
- **Phase 6 — Investigation**: Investigate and fix the remaining ~7 independent test failures (strategies CRUD, auth validation, chat/query validation).
- Integration test suite goes from 118/208 passing (56%) to 0 expected failures (14 gate tests removed, 71 failures fixed).

## Capabilities

### New Capabilities
- `test-doubles`: Shared deterministic implementations of `Embedder` and LLM interfaces in `tests/doubles/`, producing hash-based pseudo-embeddings and canned LLM responses that pass all downstream validation (dimension checks, normalization, FAISS indexing)
- `test-singleton-isolation`: Per-test fixtures that reset `_embedder_instance` before each warmup test, preventing cross-test pollution from session-scoped fixtures

### Modified Capabilities
- `model-warmup`: The `prewarm_models` fixture behavior changes — it now seeds actual singletons (`_embedder_instance`, `_llm_instance`) instead of WarmupState. This changes the fixture's observable effect from "gate passes" to "model pipeline works without blocking."

### Removed Capabilities
- WarmupState and `require_models` gate: These are reverted. Model readiness is determined by the actual singleton state, not a separate gate layer.

## Impact

- **Code**: `src/domain/services/embedding.py` — `asyncio.to_thread` wrapping; removal of `gate.py`, `warmup.py`, `require_models` from route handlers
- **Tests**: `tests/doubles/` (new directory, 2-3 files), `tests/integration/conftest.py` (fixture changes), `tests/integration/test_dspy_warmup.py`, `tests/integration/test_embedder_warmup.py` (isolation fixtures), removal of `tests/integration/test_query_gate.py`
- **Infrastructure**: No new dependencies. TestEmbedder uses only stdlib math and the existing `Embedder` protocol interface.
- **Risk**: Low. Test doubles are well-understood pattern. The `asyncio.to_thread` fix is a net safety improvement. No production behavior changes other than the event loop no longer blocking.
