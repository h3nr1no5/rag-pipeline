## Why

When the RAG pipeline server starts, models (LLM, cross-encoder, embedder) take seconds to minutes to download and load into memory. Currently, query endpoints accept requests before models are ready, causing the backend to block on `_ensure_model_loaded()` or fail silently, while the frontend shows spinners that spin indefinitely or a progress bar that jumps from 0 to 100. This creates a confusing, unreliable user experience — users don't know if the system is working, stuck, or broken.

## What Changes

- **Unified WarmupState**: Track all 4 models (llm, cross_encoder, embedder, dspy_lm) in a single registry with status/progress/error tracking
- **Async embedder loading**: Embedder loads asynchronously in `warmup_models()` via `asyncio.to_thread` instead of blocking on first upload
- **Granular progress**: HF Hub `snapshot_download` callbacks for real download percentage (0-100)
- **Smart per-route gating**: Each query/document route checks only the models it actually depends on, returning 503 + `Retry-After` when not ready
- **Auto-retry on error**: Failed model loads retry with exponential backoff (2→4→8→16→30s cap, no max retries)
- **DSPy LM warmup**: Wraps the already-loaded MLX LLM — instant after LLM is ready
- **Frontend gateway**: Disabled inputs with tooltips, per-model status cards, no timeout bypass, error→retry UI
- **Consistent 503**: All loading/error states return 503 — no optimistic passthrough

## Capabilities

### New Capabilities
- `model-readiness-gate`: Backend middleware/decorator that checks model readiness per-route, returning 503 with `Retry-After` header when models are still loading or in error state

### Modified Capabilities
<!-- Existing capabilities whose REQUIREMENTS are changing (not just implementation).
     Only list here if spec-level behavior changes. Each needs a delta spec file.
     Use existing spec names from openspec/specs/. Leave empty if no requirement changes. -->
- `frontend-loading-status`: Changes from simple progress bars above chat to a full gateway screen with per-model cards, disabled radio buttons with tooltips, grayed upload button, no timeout bypass, and retry-progress display for errored models. Scope expands to also cover the Documents page with an integrated model status banner, disabled upload button while embedder is not ready, and proper 503 handling for document operations.

## Impact

- **`src/core/warmup.py`**: Major refactor — `WarmupState` now tracks 4 models with granular progress callbacks, auto-retry logic, error escalation to permanent_error
- **`src/domain/services/embedding.py`**: `get_embedder()` becomes async-aware, loads during warmup instead of lazy sync on first access
- **`src/domain/services/llm.py`**: Minor — `get_llm()` no longer blocks; LLM is always loaded via warmup
- **`src/domain/services/dspy.py`** (or equivalent): DSPy LM warmup added (trivial since it wraps the MLX LLM)
- **`src/api/routes/query/routes.py`**: Each query endpoint gains a `require_models(...)` decorator/guard. LangChain route cross-encoder check removed (replaced by unified gate).
- **`src/api/routes/documents/routes.py`**: Upload route gains `require_models('embedder')` check
- **`src/api/routes/health/`**: `/health/models` now returns all 4 models with more fields (message, error, retry_in)
- **`client/pages/3_💬_Chat.py`**: Major frontend changes — gateway screen replaces previous spinner/progress bar approach
- **`client/pages/4_📁_Documents.py`**: Adds unified model status banner, disables upload button while embedder is loading, handles 503 from document upload endpoint, aligns with the new model-readiness architecture
- **`client/utils/query.py`**: Cleaner error handling for 503 responses
- **`pyproject.toml`**: No new dependencies needed
