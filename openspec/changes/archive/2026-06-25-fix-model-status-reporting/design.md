## Context

The `revert-warmupstate` change (commit `25f49b0`) removed the `WarmupState` gate system and rewrote `/health/models` to check actual LLM and embedder singletons instead. However, the endpoint was trimmed to two models, while the frontend polls for four (`cross_encoder`, `llm`, `embedder`, `dspy_lm`). The two missing models default to `"loading"` in frontend code, causing an infinite `st.rerun()` loop.

This design adds proper tracking for the two missing models and fixes the LLM readiness semantic, then adjusts frontend polling to be bounded and less aggressive.

## Goals / Non-Goals

**Goals:**

- Add `cross_encoder` and `dspy_lm` status reporting to `/health/models` using actual singleton/model state
- Change LLM readiness from `_model_loaded` (package importable) to `_model is not None` (weights loaded)
- Reduce frontend polling frequency from 200ms to 1s
- Add a maximum of 50 polls (~50s ceiling) with permanent error display on exhaustion
- Preserve the honest no-separate-state approach from revert-warmupstate — no reintroduction of `WarmupState` or similar

**Non-Goals:**

- Not adding WebSocket/SSE push for model status (polling is sufficient for this use case)
- Not changing the model loading logic itself (what loads, in what order, timeouts)
- Not adding a formal model registry or state machine
- Not changing any other health endpoints (`/health`, `/health/detailed`)
- Not unifying the two polling implementations (Chat inline + model_status_banner) — defer to future cleanup

## Decisions

### Decision 1: Check cross-encoder via class-level singleton attribute

**Choice**: The `/health/models` endpoint checks `CrossEncoderReRanker._instance._model is not None` to determine cross-encoder readiness.

**Why**: `CrossEncoderReRanker` is already a class-level singleton (`_instance`, `_model`). After `_load_models()` runs `reranker._ensure_model()`, `_model` is set on the singleton instance. No new global variables or state trackers needed — we read the existing singleton.

**Alternative considered**: Adding a module-level `_cross_encoder_ready` bool. Rejected because it's redundant state that can drift from reality (the same class of bug as `WarmupState`).

### Decision 2: Check DSPy LM via existing singleton

**Choice**: The `/health/models` endpoint checks `_dspy_lm_instance is not None` from `lm_adapter.py` to determine DSPy LM readiness.

**Why**: The `get_mlx_dspy_lm()` factory lazily creates `_dspy_lm_instance`. After `_load_models()` calls `get_mlx_dspy_lm()`, the singleton is set. Checking `_dspy_lm_instance is not None` directly avoids triggering lazy creation and honestly reports whether the LM has been instantiated.

**Conditional reporting**: When `api_docs_enabled` is `False`, the `dspy_lm` key is omitted from the response (no point reporting a model that isn't configured).

### Decision 3: LLM readiness uses `_model is not None`

**Choice**: Change line 56 of `health.py` from:
```python
llm_ready = _llm_instance is not None and getattr(_llm_instance, "_model_loaded", False)
```
to:
```python
llm_ready = _llm_instance is not None and getattr(_llm_instance, "_model", None) is not None
```

**Why**: `_model_loaded` is set to `True` when `mlx_lm` is importable (in `__init__`), but model weights may still be downloading. `_model` is only set to a non-None value after `_ensure_model_loaded()` completes successfully. This is the same principle as the WarmupState fix — check the actual state, not a proxy signal.

### Decision 4: Bounded polling at 1s interval, max 50

**Choice**: Update both polling implementations (Chat page inline and `model_status_banner`) to use a 1-second sleep with a maximum of 50 poll attempts. On exhaustion, display a permanent error message and stop rerunning.

**Why**: 
- 200ms is unnecessarily aggressive for model loading that typically takes 5-60s
- 1s is responsive enough (user sees status updates within ~1s of changes)
- 50 polls × 1s = ~50s max, which is close to the per-model 120s backend timeout — if the frontend gives up after 50s, the models are unlikely to load in the remaining ~70s either
- Without a max, a connection error or backend crash causes infinite CPU-spinning reruns

**Implementation approach for max polls**:
- Check against `st.session_state.models_poll_count` (already exists in Chat page)
- In `model_status_banner`, add a similar counter to session state
- When max reached, set `st.session_state.models_permanent_error = True` and stop rerunning

### Decision 5: Keep two polling implementations separate

**Choice**: The Chat page inline polling and `model_status_banner` component remain separate. Both get the same interval/max-polls changes, but are not merged.

**Why**: Unifying them is a worthwhile cleanup but out of scope for this fix. The Chat page checks only 2 models (`cross_encoder`, `llm`), while `model_status_banner` checks all 4 — they have different consumers and would need a shared abstraction that isn't justified by the complexity.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `CrossEncoderReRanker._instance` is `None` (no one called the singleton yet) | Low | Low | Guard with `_instance is not None` check before accessing `_model` |
| `dspy_lm` reported as "loading" forever when `api_docs_enabled` but DSPy fails silently | Low | Low | The 50-poll frontend timeout handles this — user sees error and can investigate |
| Checking `_model is not None` for LLM may be too strict if there's a gap between object creation and weight loading | Medium | Low | The gap is by design — we WANT to report "loading" during that window. It's more honest |
| Two polling implementations drift further apart | Medium | Low | Acceptable trade-off. The interval and max-polls constants should be kept in sync manually, or extracted to a shared constant in a follow-up |
