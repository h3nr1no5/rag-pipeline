## 1. git revert 27952c7 — ✅ COMPLETED

Commit `25f49b0`: "Revert 'Implement model readiness gate and associated tests'"

- [x] 1.1 Ran `git revert 27952c7` — commit message: `"Revert "Implement model readiness gate and associated tests""`
- [x] 1.2 **Resolved conflict in `src/api/main.py`**: Accepted HEAD — the `dspy.configure()` block was already removed by `4b14543`. The revert's intent (remove `_warmup_task` line) was preserved.
- [x] 1.3 **No conflict in `warmup.py`** (unexpected — the revert cleanly applied). The file reverted to pre-`27952c7` version with only cross-encoder + LLM. Embedder/DSPy loading code from `27952c7`/`198b8f2` was lost — rewritten in Step 3.
- [x] 1.4 **Resolved conflict in `client/pages/3_💬_Chat.py`** (unexpected — `198b8f2` had also modified this). Accepted HEAD (simpler polling logic).
- [x] 1.5 **Resolved conflict in `tests/integration/test_query_gate.py`**: `198b8f2` had added 90 more tests. Accepted deletion.
- [x] 1.6 Completed revert: `git revert --continue` (commit `25f49b0` on top of `93ef669`)

**Revert results:**
- Deleted: `gate.py`, `test_health_models.py`, `test_query_gate.py`, `test_gate.py`, `test_warmup_progress.py`, `test_warmup_state.py`
- Cleaned: `routes.py` (`require_models` removed), `documents.py`, `api_docs/routes.py`, `embedding.py`
- **WARNING**: revert RESTORED inline `get_warmup_state` checks in `routes.py` (4 places) — removed in Step 4
- `warmup.py` still exists with old WarmupState (cross-encoder + LLM only) — deleted in Step 2

## 2. Delete Additional Test Files

- [x] 2.1 `git rm tests/integration/test_document_gate.py`
- [x] 2.2 `git rm tests/unit/test_model_status.py`
- [x] 2.3 `git rm tests/unit/test_dspy_startup_race.py`
- [x] 2.4 `tests/integration/test_health_models.py` — already deleted by revert ✅
- [x] 2.5 `git rm tests/unit/test_warmup.py`

## 3. Inline Model Loading in Lifespan

- [x] 3.1 Extracted model-loading logic (cross-encoder, LLM, embedder, DSPy LM) into module-level `_load_models()` in `src/api/main.py`
- [x] 3.2 Replaced `asyncio.create_task(warmup_models())` with `asyncio.create_task(_load_models())`. Shutdown handler cancels `_warmup_task.cancel()`
- [x] 3.3 Removed `from .domain.services.warmup import warmup_models` import
- [x] 3.4 Verified: `grep -rn "warmup_models\|WarmupState\|get_warmup_state" src/api/main.py` returns nothing

## 4. Remove Restored WarmupState References

- [x] 4.1 `src/api/routes/query/routes.py` — removed 4 inline `get_warmup_state` cross-encoder checks
- [x] 4.2 `src/api/routes/health.py` — replaced `get_warmup_state().to_dict()` with direct singleton checks
- [x] 4.3 `src/api/routes/health.py` — removed `from ..domain.services.warmup import get_warmup_state` import
- [x] 4.4 Verified: `grep -rn "warmup\|WarmupState\|get_warmup_state" src/api/routes/` returns nothing

## 5. Modify Remaining Test Files

- [x] 5.1 `tests/integration/conftest.py` — removed `prewarm_models` fixture and warmup imports
- [x] 5.2 `tests/integration/test_dspy_warmup.py` — rewritten, removed `get_warmup_state()` assertions
- [x] 5.3 `tests/integration/test_embedder_warmup.py` — removed `get_warmup_state()` assertions
- [x] 5.4 `tests/integration/test_llm_loading.py` — removed `state.update()` calls and `get_warmup_state` assertions
- [x] 5.5 `tests/integration/test_api_docs_e2e.py` — patch target updated to `src.api.main._load_models`

## 6. Full Suite Verification

- [x] 6.1 `require_models` — 0 remaining references ✅
- [x] 6.2 WarmupState — 0 remaining references ✅
- [x] 6.3 warmup imports — 0 remaining references ✅
- [x] 6.4 Unit tests: 384 passed, 82 skipped, 1 deselected (pre-existing `test_query_dspy_maps_output_correctly`) ✅
- [x] 6.5 Integration tests: core files 5/5 passed; `test_upload_docx` pre-existing failure (base commit 93ef669 too); `test_get_logging_*` pre-existing flaky failures ✅
- [x] 6.6 Fast suite: 63+ passed, only pre-existing logging test failures ✅

**Pre-existing failures confirmed:**
- Unit: `test_query_dspy_maps_output_correctly` (fails on HEAD 25f49b0 and base 93ef669)
- Integration: `test_upload_docx` (fails on base 93ef669 with AttributeError)
- Integration: `test_get_logging_returns_empty_initially` / `test_get_after_put_returns_override` (flaky DB isolation)

## 7. Commit

- [x] 7.1 `git add -A && git commit -m "fix: remove WarmupState gate architecture"`
- [x] 7.2 Verified with `git status` and `git log --oneline -3`
