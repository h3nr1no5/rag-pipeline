## 1. Backend — Add cross-encoder and DSPy LM to /health/models

- [x] 1.1 Add cross-encoder status check to `/health/models`: import `CrossEncoderReRanker`, check `_instance is not None and _instance._model is not None`, return `"ready"` or `"loading"`
- [x] 1.2 Add DSPy LM status check to `/health/models`: import `_dspy_lm_instance` from `lm_adapter.py`, check `is not None`, return `"ready"` or `"loading"`. Omit the key entirely when `api_docs_enabled` is `False`.
- [x] 1.3 Update the response dict in `/health/models` to include both new keys alongside existing `llm` and `embedder`
- [x] 1.4 Verify with `curl http://localhost:8000/api/v1/health/models` that all four models appear with correct status values

## 2. Backend — Fix LLM readiness semantic

- [x] 2.1 In `/health/models` (line 56 of `health.py`), change `getattr(_llm_instance, "_model_loaded", False)` to `getattr(_llm_instance, "_model", None) is not None`
- [x] 2.2 Verify with `curl` that LLM reports `"loading"` during weight download (between server start and model loading completion) and `"ready"` after loading finishes

## 3. Frontend — Fix Chat page polling

- [x] 3.1 In `client/pages/3_💬_Chat.py`, change `time.sleep(0.2)` to `time.sleep(1.0)` in the model polling block
- [x] 3.2 Add max-polls guard: check `st.session_state.models_poll_count` against 50, increment on each poll cycle, show permanent error message and stop rerunning when exhausted
- [x] 3.3 Verify the Chat page no longer enters an infinite rerun loop when models take long to load

## 4. Frontend — Fix model_status_banner component

- [x] 4.1 In `client/components/model_status.py`, change `time.sleep(0.2)` to `time.sleep(1.0)` in the polling loop (line 138)
- [x] 4.2 Add max-polls guard: add `models_poll_count` to session state, check against 50, set `models_permanent_error = True` and stop rerunning when exhausted
- [x] 4.3 Verify the Documents page model status banner respects the same polling bounds

## 5. Verification

- [x] 5.1 Run full test suite: `uv run pytest tests/unit/ -v`
- [x] 5.2 Run integration tests: `uv run pytest tests/integration/ -v -x`
- [x] 5.3 Verify no regressions in health endpoint tests
- [x] 5.4 Manual smoke test: start backend + frontend, verify Chat page shows loading state and transitions to ready state once models load