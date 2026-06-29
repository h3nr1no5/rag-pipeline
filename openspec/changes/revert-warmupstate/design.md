## Context

The `WarmupState` system was introduced in commit `27952c7` ("Implement model readiness gate and associated tests") to provide a FastAPI-level gate (`require_models`) that returns 503 when models aren't ready. However, `WarmupState` is a separate concern from the actual model singletons (`_embedder_instance`, `_llm_instance`) — the gate can say "ready" while the singleton is `None`.

This disconnect cascades: `prewarm_models` (a test fixture) seeds `WarmupState` to "ready", `require_models` passes, background document processing starts, `get_embedder()` finds `_embedder_instance is None`, and blocks synchronously loading the real model. ~58 test failures cascade from this single issue.

Removing `WarmupState` eliminates the decoupled gate/singleton pattern. After the revert, `_embedder_instance` is the single source of truth for embedder availability. There's no gate to give a false "ready" signal.

## Goals / Non-Goals

**Goals:**
- Remove `WarmupState`, `ModelStatus`, `get_warmup_state`, `_warmup_state`, `_retry_with_backoff`, `_make_progress_callback`, `all_ready`, `any_loading` properties
- Remove `require_models` FastAPI dependency from all route handlers
- Delete 6 test files and the `prewarm_models` fixture
- Preserve the actual model loading logic from `warmup_models()` — inline it into the FastAPI lifespan without state tracking
- Update health endpoint to check actual singletons instead of `WarmupState`
- Update warmup tests to work without `WarmupState` assertions
- 0 regressions in the test suite after revert

**Non-Goals:**
- Not changing the model loading behavior itself (what gets loaded, in what order)
- Not changing the `Embedder` or LLM interfaces
- Not fixing the remaining 71 test failures (that's the next change)
- Not adding any new test infrastructure
- Not changing server startup sequencing

## Decisions

### Decision 1: Inline `warmup_models()` into the lifespan, not a new module

**Choice**: The model loading logic from `warmup_models()` is inlined directly into the lifespan handler in `src/api/main.py`, stripped of all `state.update()` calls. The background task creation and shutdown patterns are preserved.

**Why**: After removing all `WarmupState` update calls (~70 lines), what remains is simple enough (4 model loads with try/except) that a separate module adds indirection without benefit. The lifespan already manages startup sequencing; model loading is part of startup.

**What the stripped-down function looks like:**
```python
# Inside lifespan(), replacing the warmup_models() import + create_task:
async def _load_models():
    """Load models in background — sets module-level singletons directly."""
    try:
        cross_encoder = CrossEncoderReRanker()
        await cross_encoder._ensure_model()
        logger.info("Cross-encoder loaded")
    except Exception as e:
        logger.error(f"Cross-encoder failed: {e}")

    try:
        llm = await get_llm()
        llm._ensure_model_loaded()
        logger.info("LLM loaded")
    except Exception as e:
        logger.error(f"LLM failed: {e}")

    try:
        from .embedding import SentenceTransformerEmbedder
        embedder = SentenceTransformerEmbedder()
        emb_mod._embedder_instance = embedder
        logger.info("Embedder loaded")
    except Exception as e:
        logger.error(f"Embedder failed: {e}")

    try:
        if settings.api_docs_enabled:
            from ..rag.api_docs.pipeline.lm_adapter import get_mlx_dspy_lm
            import dspy
            dspy.configure(lm=get_mlx_dspy_lm())
            logger.info("DSPy LM configured")
    except Exception as e:
        logger.error(f"DSPy LM failed: {e}")

_warmup_task = asyncio.create_task(_load_models())
```

### Decision 2: Health endpoint checks singletons directly

**Choice**: The health endpoint currently calls `get_warmup_state().to_dict()` to report model status. After the revert, it checks `_embedder_instance is not None`, `_llm_instance` is loaded, etc.

**Why**: This is more honest — it reports whether models are ACTUALLY loaded, not whether a separate state tracker thinks they are. The information is still useful for health monitoring.

### Decision 3: Route handler removal — `Depends(require_models(...))` stripped, not replaced

**Choice**: Remove `require_models` import and all `Depends(require_models(...))` usages from route handlers. No replacement gate — if the model isn't loaded, the endpoint produces a natural error (which can be enhanced separately if needed).

**Why**: The gate added complexity without real protection — it could report "ready" when the singleton was still `None`. The model loading happens in the lifespan background task and sets singletons directly. If a request arrives before loading completes, it gets the natural error from the missing model, which is more honest and debuggable.

### Decision 4: Test migration — delete gate tests, simplify warmup tests

**Choice**: 
- Delete `test_query_gate.py` (14 tests), `test_document_gate.py`, `test_warmup.py` (22 tests), `test_gate.py` (7 tests), `test_dspy_startup_race.py` — all test WarmupState or require_models behavior that no longer exists
- Simplify `test_embedder_warmup.py` and `test_dspy_warmup.py` — remove `get_warmup_state()` assertions, keep assertions about singleton assignment
- Simplify `test_llm_loading.py` — remove `state.update("llm", ...)` calls
- Remove `prewarm_models` fixture from conftest.py entirely

**Why**: ~550 lines of tests that test removed functionality are deleted. Remaining warmup tests focus on what matters: did the model loading code set the singletons? The test suite shrinks and simplifies.

### Decision 5: Use `git revert 27952c7` as the primary undo mechanism

**Choice**: The primary undo is `git revert 27952c7` rather than manually deleting and editing files. After the revert, remaining cleanup tasks (files created by subsequent commits, inlining model loading) are applied manually on top.

**Why**: `git revert` is the correct tool for undoing a commit's changes. It cleanly handles:
- Deleting files that `27952c7` created: `gate.py`, `test_health_models.py`, `test_gate.py`, `test_warmup_progress.py`, `test_warmup_state.py`
- Removing `require_models` imports from `query/routes.py`, `documents.py`, `api_docs/routes.py`
- Reverting `embedding.py` to the original `if _embedder_instance is None` pattern
- Reverting client files (`Chat.py`, `query.py`) to pre-gate-polling state

**Actual conflicts encountered and resolution:**
| File | Conflict cause | Resolution |
|------|---------------|------------|
| `client/pages/3_💬_Chat.py` | `198b8f2` simplified the polling logic on top of `27952c7`'s changes | Accept **HEAD** (simpler `time.sleep(0.2); st.rerun()` — keeps the later, cleaner version) |
| `src/api/main.py` | `4b14543` removed the `dspy.configure()` block that `27952c7` touched | Accept **HEAD** (empty — the dspy block was intentionally removed) |
| `tests/integration/test_query_gate.py` | `198b8f2` added 90 more tests to this `27952c7`-created file | Accept **deletion** (removing all gate tests) |

**Surprise: `warmup.py` had NO conflict.** The revert cleanly applied, undoing both `27952c7`'s massive WarmupState rewrite AND `198b8f2`'s embedder/DSPy additions. The file is back to the pre-`27952c7` version with only `cross_encoder`/`llm` fields and the simpler `warmup_models()`. This is **fine** — the embedder/DSPy loading code will be rewritten as part of the inlined `_load_models()`.

**Surprise: `routes.py` RESTORED inline `get_warmup_state` checks.** Before `27952c7`, `routes.py` had inline cross-encoder error checks using `get_warmup_state()`. The revert restored these (4 places). They must be removed manually.

**What the revert already handled (6 files deleted):**
- `src/api/gate.py`, `tests/integration/test_health_models.py`, `tests/integration/test_query_gate.py`
- `tests/unit/test_gate.py`, `tests/unit/test_warmup_progress.py`, `tests/unit/test_warmup_state.py`

**What the revert did NOT handle (manual steps remain):**
- Delete `test_document_gate.py`, `test_model_status.py` (created by `198b8f2`)
- Delete `test_dspy_startup_race.py` (created by `4b14543`)
- Delete `test_warmup.py` (24 WarmupState tests were restored by revert)
- Remove `prewarm_models` fixture from `conftest.py` (added by `93ef669`)
- Remove 4 inline `get_warmup_state` checks restored in `routes.py`
- Replace `get_warmup_state()` in `health.py` with direct singleton checks
- Create inlined `_load_models()` in lifespan (new code)
- Delete `warmup.py` entirely (still has old WarmupState)
- Clean up remaining WarmupState references in test files

## Execution Order

```ascii
Step 1: ┌── git revert 27952c7 ────────────────────────┐
         │  ✅ COMPLETED                                │
         │  Run: git revert 27952c7                     │
         │  Resolved 3 conflicts:                       │
         │  • Chat.py: accept HEAD (simpler polling)    │
         │  • main.py: accept HEAD (block already gone) │
         │  • test_query_gate.py: accept deletion       │
         │  Result: 6 files deleted, routes cleaned of  │
         │  require_models, embedding.py reverted       │
         └──────────────────────────────────────────────┘

Step 2: ┌── Delete additional test files ──────────────┐
         │  test_document_gate.py   (git rm — 198b8f2)  │
         │  test_model_status.py    (git rm — 198b8f2)  │
         │  test_dspy_startup_race.py  (git rm — 4b14543)│
         └──────────────────────────────────────────────┘

Step 3: ┌── Inline model loading in lifespan ──────────┐
         │  src/api/main.py: create _load_models()      │
         │  stripped of ALL WarmupState tracking:       │
         │  • Remove state.update() calls               │
         │  • Remove progress callbacks                 │
         │  • Remove retry/backoff logic                │
         │  • Keep: model init + try/except per model   │
         │  See Decision 1 for the code skeleton        │
         └──────────────────────────────────────────────┘

Step 4: ┌── Remove restored WarmupState refs ──────────┐
         │  src/api/routes/health.py:                   │
         │  Replace get_warmup_state().to_dict() with   │
         │  direct singleton checks                     │
         │  src/api/routes/query/routes.py:             │
         │  Remove 4 inline get_warmup_state checks     │
         │  that revert restored (lines 485-492,        │
         │  691-698)                                    │
         └──────────────────────────────────────────────┘

Step 5: ┌── Modify remaining test files ───────────────┐
         │  conftest.py: remove prewarm_models          │
         │  test_dspy_warmup.py: remove state asserts   │
         │  test_embedder_warmup.py: remove state       │
         │  test_llm_loading.py: remove state.update    │
         │  test_api_docs_e2e.py: remove patch target   │
         └──────────────────────────────────────────────┘

Step 6: ┌── Full suite verification ───────────────────┐
         │  grep for remaining WarmupState/require_refs │
         │  Run: pytest tests/unit/                     │
         │  Run: pytest tests/integration/ -x           │
         │  Run: pytest -m "not slow"                   │
         └──────────────────────────────────────────────┘
```

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Missing a `require_models` import or `Depends()` in a route handler | Low | Medium | After deletion, grep for `require_models` and `WarmupState` — test suite will catch any missed references (import error at module load time) |
| Inlined model loading has a bug that wasn't in the original `warmup_models()` | Low | Medium | Review the extracted code carefully. The logic is unchanged — only `state.update()` calls removed. The loading sequence and error handling stay the same. |
| Health endpoint returns "unhealthy" during model loading (before, it returned 503 with model status) | Medium | Low | This is more correct behavior — the server isn't fully healthy until models are loaded. Accept as a net improvement. |
| Some test that depends on `prewarm_models` still exists | Low | Medium | After deletion, run full suite — any test importing `prewarm_models` will fail immediately with import error. |
| The DSPy warmup tests still import from `src.domain.services.warmup` after deletion | Medium | Medium | The test files import `warmup_models` and `get_warmup_state`. After deletion, these imports must be updated. Step 5 handles this explicitly. |
