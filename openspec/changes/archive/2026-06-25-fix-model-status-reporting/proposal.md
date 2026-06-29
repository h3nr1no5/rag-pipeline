## Why

The `revert-warmupstate` change removed the decoupled `WarmupState` gate and simplified `/health/models` to check actual singletons. However, the endpoint was trimmed to only report `llm` and `embedder` status — dropping `cross_encoder` and `dspy_lm`. Both the Chat page and Documents page frontend components poll for these missing models, default their status to `"loading"`, and enter an infinite `st.rerun()` loop that never terminates. Additionally, the LLM reports `"ready"` when `mlx_lm` is importable, not when model weights are actually loaded — the same class of decoupled-signal bug that WarmupState had.

## What Changes

- **`/health/models`**: Add `cross_encoder` and `dspy_lm` status keys so the response matches frontend expectations
- **LLM readiness semantics**: Change from `_model_loaded` (package importable) to `_model is not None` (weights actually loaded)
- **Frontend polling backoff**: Increase poll interval from 200ms to 1s; add a maximum of 50 polls (~50s ceiling) with permanent error display on exhaustion

## Capabilities

### New Capabilities
- `model-status-reporting`: Accurate backend model status endpoint that reports all four models (cross-encoder, LLM, embedder, DSPy LM) with honest readiness checks against actual loaded state, plus frontend polling with bounded retry and error handling

### Modified Capabilities

None — no existing specs to modify.

## Impact

**Backend — `src/api/routes/health.py`**:
- `/health/models` response shape changes — adds two new keys (`cross_encoder`, `dspy_lm`)
- LLM readiness check changes semantics — stricter (weights-loaded instead of importable)

**Backend — model state tracking**:
- May need minor additions to expose cross-encoder and DSPy LM state to the health endpoint (e.g., import `CrossEncoderReRanker` class, check `_dspy_lm_instance`)
- No new service layer or state machine needed — existing singletons suffice

**Frontend — `client/pages/3_💬_Chat.py`**:
- Poll interval: 0.2s → 1.0s
- Max polls guard: infinite → 50 with error state
- Polling logic simplified: no longer needs to guess missing model statuses

**Frontend — `client/components/model_status.py`**:
- Same polling interval and max-polls changes
- Permanent error state when max polls exhausted

**No breaking API changes** — `/health/models` is additive (new keys added). Existing consumers that ignored unknown keys will work unchanged.
