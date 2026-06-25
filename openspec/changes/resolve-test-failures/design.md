## Context

The integration test suite has ~58 cascading failures from a single root cause: document upload tests timeout because `get_embedder()` blocks synchronously loading the real SentenceTransformer model (~2-10s cached, >>45s if uncached). This blocks the async event loop, preventing HTTP polling from responding. Tests time out, documents remain "pending", and everything downstream of processed documents fails.

Phase 0 (revert WarmupState) is complete (commit `ee91dde`). The WarmupState gate architecture has been removed entirely — `gate.py`, `warmup.py`, `require_models` route dependencies, and all related test files are deleted. Model loading now runs inline in lifespan as `_load_models()`. Model readiness is determined by the actual singleton state (`_embedder_instance is not None`), eliminating the gate-vs-singleton drift problem.

A secondary issue is global singleton pollution (~6 failures): `_embedder_instance` is a module-level global that persists between tests. The session-scoped seeding fixture runs once and never resets, so warmup tests that depend on clean state fail when run after other tests have modified the global.

A third category (~7 failures) includes independent tests that fail for their own reasons (strategies CRUD, auth/chat/query validation, possible assertion mismatches).

## Goals / Non-Goals

**Goals:**
- Phase 0 already done: WarmupState infrastructure reverted, `_load_models()` in lifespan, singletons as ground truth
- Eliminate all ~71 integration test failures
- Add session-scoped autouse fixture that seeds model singletons with test doubles so background document processing completes in milliseconds
- Provide shared, deterministic, maintainable test doubles (`TestEmbedder`, `TestLLM`) in a discoverable location
- Fix the production event-loop blocking bug in `get_embedder()` via `asyncio.to_thread`
- Add per-test singleton isolation for warmup tests
- Investigate and fix all remaining independent test failures

**Non-Goals:**
- Not rewriting the embedding service or LLM service
- Not adding new test frameworks or dependencies
- Not changing the test marker taxonomy (already done in `test-fixes`)
- Not fixing test failures outside the integration suite (unit tests already pass)
- Not adding CI infrastructure changes

## Decisions

### Decision 0: Revert WarmupState before building (✅ DONE)

Commit `ee91dde` reverts the WarmupState introduction, deletes `gate.py`, `warmup.py`, `require_models` from route handlers, and all WarmupState test files. Model loading inlined as `_load_models()` in `src/api/main.py`.

### Decision 1: Hash-based deterministic pseudo-embedder over zero-vector mock

**Choice**: `TestEmbedder` produces deterministic vectors via `math.sin(hash(text) + i * 0.1) * 0.1` for each of 768 dimensions.

**Alternatives considered:**
- **Zero-vector mock**: Fastest but fails `normalize_embedding` edge case (L2 norm of zero is zero, which is handled but trips `validate_embedding` in some contexts). FAISS can't index all-zero vectors.
- **Real model singleton**: Most realistic but adds 2-10s to session startup and requires model download. Defeats the purpose of fast tests.
- **Random vector**: Non-deterministic — produces flaky tests on rerun.

**Why hash-based**: Deterministic (same input → same vector), passes all downstream validation (numeric, correct dimension 768, no NaN/Inf), FAISS-indexable, and fast (microseconds per call).

### Decision 2: Single seeding fixture over separate fixtures

**Choice**: A single session-scoped autouse fixture sets `_embedder_instance` and `_llm_instance`.

**Alternatives considered:**
- **Separate fixtures**: More orthogonal but requires all tests to add a second `autouse`. More moving parts.
- **Inline in each test file**: Duplication, maintenance burden.

**Why single fixture**: One fixture, one place, done. All tests automatically get seeded singletons.

### Decision 3: Save/restore isolation pattern over clear-only

**Choice**: Warmup test isolation fixtures save the current singleton state before each test and restore it after.

```python
saved = emb_mod._embedder_instance
emb_mod._embedder_instance = None
yield
emb_mod._embedder_instance = saved
```

**Alternatives considered:**
- **Clear-only**: Simpler but breaks if a test needs the session-scoped state afterward.
- **No isolation**: Leaves tests order-dependent.

**Why save/restore**: Compatible with session-scoped fixtures (seeding state is preserved after the test), handles cleanup reliably, and the pattern is explicit and auditable.

### Decision 4: `asyncio.to_thread` over `run_in_executor` or `ThreadPoolExecutor`

**Choice**: `_embedder_instance = await asyncio.to_thread(SentenceTransformerEmbedder)`

**Alternatives considered:**
- **`loop.run_in_executor(None, SentenceTransformerEmbedder)`**: More verbose, requires accessing the event loop.
- **Custom `ThreadPoolExecutor`**: Over-engineered for a single blocking call.
- **Make `SentenceTransformerEmbedder.__init__` async**: Changes the public API, requires all callers to `await`.

**Why `asyncio.to_thread`**: Python 3.9+ built-in, cleanest API (takes a callable, returns a coroutine), uses the default thread pool, and requires no event loop manipulation.

### Decision 5: `tests/doubles/` directory over inline in conftest

**Choice**: Create `tests/doubles/__init__.py`, `tests/doubles/embedder.py`, `tests/doubles/llm.py`.

**Alternatives considered:**
- **Inline in `tests/integration/conftest.py`**: Simple but not importable from other test directories. Blows up conftest.py.
- **In `src/domain/testing/`**: Blurs the line between production and test code. Risk of production imports.
- **Scattered `DoubleEmbedder` classes in each test file**: Max duplication.

**Why `tests/doubles/`**: Standard pattern. Clearly test-only code. Importable from any `tests/` subdirectory. Addable to `sys.path` via the existing `chdir` in `pyproject.toml` (pytest already runs from project root).

## Architecture

```ascii
┌──────────────────────────────────────────────────────────────────┐
│  Phase 0: Revert WarmupState (✅ DONE — ee91dde)                  │
│                                                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐ │
│  │ git revert    │    │ Remove gate.py   │    │ Remove         │ │
│  │ 27952c7      │───▶│ warmup.py        │───▶│ require_models │ │
│  │ + patches    │    │ test files       │    │ from routes    │ │
│  └──────────────┘    └──────────────────┘    └────────────────┘ │
│                                                                  │
│  Result: One source of truth for model readiness: the singleton  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                        tests/doubles/                             │
│                                                                  │
│  embedder.py                                                     │
│  ┌─────────────────────────────────────────┐                    │
│  │ class TestEmbedder(Embedder):           │                    │
│  │   dimension = 768                        │                    │
│  │   async def embed_text(text) → list[float]                    │
│  │   async def embed_texts(texts) → list[list[float]]           │
│  │   def get_dimension() → int                                   │
│  └─────────────────────────────────────────┘                    │
│                                                                  │
│  llm.py                                                          │
│  ┌─────────────────────────────────────────┐                    │
│  │ class TestLLM:                           │                    │
│  │   async def generate(prompt) → str       │                    │
│  │   # Returns deterministic canned response│                    │
│  │   # Overridable per-test via constructor │                    │
│  └─────────────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────┘
                           │ imports
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│               tests/integration/conftest.py                      │
│                                                                  │
│  seed_singletons (session-scoped, autouse):                      │
│    1. emb_mod._embedder_instance = TestEmbedder()               │
│    2. llm_mod._llm_instance = TestLLM()                         │
│                                                                  │
│  wait_for_document (shared helper, already consolidated)          │
└──────────────────────────────────────────────────────────────────┘
                           │ autouse
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Tests run → get_embedder() returns instantly                    │
│  → Document processes in <100ms                                  │
│  → Polling succeeds → "completed" status                         │
│  → ~58 cascading failures eliminated                             │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Singleton isolation (per warmup test file):                     │
│                                                                  │
│  isolate_global_state (autouse):                                 │
│    1. Save emb_mod._embedder_instance                            │
│    2. Reset to defaults (None)                                   │
│    3. yield (test runs)                                          │
│    4. Restore saved state                                        │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ Production fix (src/domain/services/embedding.py):              │
│                                                                  │
│  async def get_embedder():                                       │
│    if _embedder_instance is not None: return it                  │
│    _embedder_instance = await asyncio.to_thread(                 │
│        SentenceTransformerEmbedder                               │
│    )                                                             │
│    return _embedder_instance                                     │
└──────────────────────────────────────────────────────────────────┘
```

## Execution Order

```ascii
Step 0: ┌── Revert WarmupState (DONE) ──┐  (ee91dde)
         │ git revert 27952c7            │
         │ Remove tests/routes/gate      │
         └───────────────────────────────┘
                  │
Step 1: ┌── tests/doubles/ ──┐  (no deps)
         │ TestEmbedder       │
         │ TestLLM            │
         └────────────────────┘
                  │
Step 2: ┌── conftest.py ─────────────┐  (depends on Steps 0 + 1)
         │ seed_singletons fixture   │
         └───────────────────────────┘
                  │
Step 3: ┌── Test isolation fixtures ──┐  (independent of Step 2)
         │ test_dspy_warmup.py        │
         │ test_embedder_warmup.py    │
         └────────────────────────────┘
                  │
Step 4: ┌── Production fix ──────────┐  (independent)
         │ embedding.py: to_thread    │
         └────────────────────────────┘
                  │
Step 5: ┌── Full suite run ──────────┐  (depends on Steps 1-4)
         │ Observe remaining failures │
         └────────────────────────────┘
                  │
Step 6: ┌── Fix remaining ~7 ────────┐  (depends on Step 5)
         │ Investigate and fix each   │
         └────────────────────────────┘
```

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| TestEmbedder dimension doesn't match expected model dimension | Low | Medium | Parameterize dimension; set to 768 (all-mpnet-base-v2). Update if `EMBEDDING_MODEL` env var changes. |
| TestLLM canned response causes assertion failures in tests expecting specific output | Low | Low | Make response customizable via constructor kwarg; use a generic sentence by default. |
| Production `asyncio.to_thread` change introduces regression | Low | Medium | Only affects model load path (first call per process). After singleton is set, all calls return immediately. Unit tests with mocked singletons unaffected. |
| Some of the ~7 remaining failures require non-trivial production code fixes | Medium | Medium | Design explicitly includes investigation phase. Scope is limited to this change; if any fix is too large, it can be deferred with a documented skip. |

## Open Questions

1. Does the LLM service have a similar synchronous blocking issue in `generate()`? (Worth investigating but out of scope if not causing test failures.)
2. Should `TestEmbedder` support configurable failure modes for negative testing (e.g., `embed_text` raises exception)? (Nice-to-have, can add when needed.)
3. Does the cross_encoder singleton need the same treatment (seeding + isolation)? (Check if cross_encoder is used in test code paths.)
