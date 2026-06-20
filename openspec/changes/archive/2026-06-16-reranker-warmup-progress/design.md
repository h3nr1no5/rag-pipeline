## Context

The LangChain backend currently loads the CrossEncoder reranker model synchronously inside the event loop on the first query. The model (`BAAI/bge-reranker-v2-m3`, 2.1GB on disk) takes 30-45s to load from disk, blocking all concurrent requests during that time. The same issue affects the LLM (~500MB, 10-30s load time). With `--reload` (common in development), these singletons reset on every file change, making the first request after each reload painfully slow.

Additionally, the existing reranker outputs raw logit scores (~0-20 range) that require min-max normalization before they're meaningful to API consumers, and its 512-token limit truncates long document chunks.

## Goals / Non-Goals

**Goals:**
- Switch to `Alibaba-NLP/gte-reranker-modernbert-base` for faster loading (~500MB), calibrated [0,1] scores, and 8192-token context
- Preload cross-encoder and LLM on server startup via `asyncio.create_task` so models are ready when the first request arrives
- Wrap all model loading in `asyncio.to_thread` to keep the event loop responsive
- Expose per-model loading status via `GET /health/models` endpoint
- Frontend polls `/health/models` every 200ms and shows progress bars per model
- Remove min-max score normalization from LangChain pipeline (no longer needed with [0,1] scores)
- Graceful error: if cross-encoder fails to load, return an error message in the API response

**Non-Goals:**
- Changing the cosine similarity or LlamaIndex backends
- Changing the caching layer (query cache, response cache)
- Changing authentication or user management
- Frontend redesign beyond model status indicators on the chat page
- Docker or CI/CD changes

## Decisions

### Decision 1: Model Choice — `Alibaba-NLP/gte-reranker-modernbert-base`

**Chosen:** `Alibaba-NLP/gte-reranker-modernbert-base` (149M params, ~500MB)

**Rationale:**
- 3.5x smaller than current model (500MB vs 2.1GB) → faster download and loading
- Native [0,1] softmax scores → no normalization needed, API self-documents
- 8192 token context → no truncation of long document chunks
- BEIR score 56.19 (comparable to current model)
- LoCo benchmark 90.68 (excellent for long-context retrieval)
- No `trust_remote_code` required → fewer compatibility issues

**Alternatives considered:**
- `cross-encoder/ms-marco-MiniLM-L-6-v2`: Smaller (80MB) but only 512 tokens and no softmax [0,1] output
- `BAAI/bge-reranker-v2-m3` (current): 2.1GB, 512 tokens, raw logits, works but slow to load

### Decision 2: Startup Warmup — Non-blocking `asyncio.create_task`

**Chosen:** Launch warmup in the FastAPI lifespan handler via `asyncio.create_task(warmup_models())`. The warmup function calls `asyncio.to_thread()` for each model load, tracking progress in a shared `WarmupState` singleton.

**Rationale:**
- Models load in background while server starts accepting requests immediately
- `asyncio.to_thread` runs the synchronous `CrossEncoder()` and `MLXLLM()` constructors in a thread pool, keeping the event loop free
- Shared state object allows both the loading task and the health endpoint to read/write progress atomically

**Considerations:**
- If a request arrives before warmup completes, the existing lazy-load code path kicks in (with `asyncio.to_thread` wrapper) as a fallback
- After warmup completes, lazy loading is a no-op since the singleton is already set

### Decision 3: Frontend Polling — 200ms interval

**Chosen:** Chat page polls `GET /health/models` every 200ms while any model has `status: "loading"`. Polling stops when all models reach `status: "ready"` or `status: "error"`.

**Rationale:**
- 200ms provides smooth progress bar updates without excessive request volume
- Polling stops automatically when all models are ready (typically after first load or server restart)

### Decision 4: Score Handling — No normalization, no threshold

**Chosen:** Pass `gte-reranker-modernbert-base` scores through as-is in the [0,1] range. Remove min-max normalization from `retrieval_langchain.py`. Do NOT apply a relevance threshold (the `top_k` parameter alone controls result count).

**Rationale:**
- [0,1] scores are already calibrated relevance probabilities
- Filtering by a hidden threshold creates a confusing API where `top_k=5` might return fewer results
- API consumers can apply their own threshold if needed

### Decision 5: Fallback on Cross-Encoder Failure

**Chosen:** If the cross-encoder fails to load during warmup (e.g., model file corrupted, OOM), catch the error and set `status: "error"` in the warmup state. Subsequent LangChain requests check this state and return a 503 response with a clear error message. No silent fallback to non-reranked retrieval.

**Rationale:**
- Silent degradation (passing through un-reranked results) would produce inconsistent quality
- A clear 503 error is more actionable for the user

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Model download on first deploy adds ~500MB to container | Download during Docker build, not at runtime; or use persistent volume |
| Memory increase from keeping both models in memory | Models already loaded on first request; warmup just shifts timing. No net increase |
| Warmup task fails silently if exception is swallowed | Wrap warmup body in try/except + log; store error state in `WarmupState` |
| Frontend polls health endpoint even when models are ready | Stop polling when all models reach `ready`/`error` status; use a `done` flag |
| `--reload` in development resets singletons and re-triggers warmup | Warmup is idempotent — already-loaded models skip re-initialization via singleton guard |
