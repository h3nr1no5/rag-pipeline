## Why

The LangChain backend suffers from a ~30-60s timeout on first request because the 2.1GB BGE reranker model (`BAAI/bge-reranker-v2-m3`) loads synchronously in the event loop during the first query, blocking all concurrent requests. Additionally, the current reranker's raw logit scores (~0-20) are opaque to API consumers and require normalization, while its 512-token limit truncates long documents.

This change replaces the heavy reranker with a smaller, faster alternative; moves model loading to startup with non-blocking I/O; and adds frontend-visibile loading progress.

## What Changes

- **Switch enterprise reranker**: Replace `BAAI/bge-reranker-v2-m3` with `Alibaba-NLP/gte-reranker-modernbert-base` (149M params, ~500MB, [0,1] softmax scores, 8192 tokens, no `trust_remote_code`)
- **Async startup warmup**: Preload cross-encoder and LLM models on server startup via `asyncio.create_task` with `asyncio.to_thread`, exposing per-model status via a new health endpoint
- **New `/health/models` endpoint**: Returns loading status, model name, and progress percentage for each lazily-loaded model (cross-encoder, LLM)
- **Frontend model status polling**: Chat page polls `/health/models` every 0.2s and shows per-model progress bars while models are loading
- **Remove min-max normalization from LangChain pipeline**: The new model outputs calibrated [0,1] probabilities — no normalization needed
- **Graceful error fallback**: If cross-encoder fails to load, return an error message in the API response rather than silently degrading
- **Update `.env.example`**: Change `RERANKER_MODEL` default to the new model and add startup warmup toggle

## Capabilities

### New Capabilities
- `model-warmup`: Server-side async model preloading with per-model status tracking, progress reporting, and `/health/models` endpoint
- `frontend-loading-status`: Client-side polling of model loading progress with per-model status bars on the chat page

### Modified Capabilities
*(None — no existing specs to modify)*

## Impact

- **Backend**: `src/domain/services/retrieval_langchain.py` — CrossEncoder instantiation moved from lazy `_ensure_model()` to startup warmup; `_ensure_model()` wrapped in `asyncio.to_thread()`; score normalization removed
- **Backend**: `src/api/main.py` — lifespan handler updated with `asyncio.create_task(warmup_models())`
- **Backend**: `src/api/routes/health/routes.py` — new `GET /health/models` endpoint added
- **Backend**: `src/domain/services/llm.py` — LLM warmup registration (optional, non-blocking)
- **Backend**: `src/core/config.py` — potential new settings for warmup toggle
- **Frontend**: `client/app.py` or a new status component — polling logic and progress bar UI
- **Dependencies**: Reduced — `BAAI/bge-reranker-v2-m3` (2.1GB) removed from cache, replaced by `Alibaba-NLP/gte-reranker-modernbert-base` (~500MB)
