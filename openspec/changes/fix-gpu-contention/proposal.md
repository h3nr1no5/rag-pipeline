## Why

The frontend Chat page dispatches all 3 RAG backends (cosine, LangChain, LlamaIndex) concurrently via `ThreadPoolExecutor(max_workers=3)`. Each backend calls `MLXLLM.generate()` which runs `mlx_lm.generate()` on the shared GPU model — but there is NO concurrency lock, so all 3 threads hit Metal GPU inference simultaneously. Metal serializes access at the hardware level, causing GPU thrashing that makes the frontend feel disproportionately slower than running pipelines individually. Real-model profiling from Phase 0 of the profiling change shows individual pipeline times of ~13.7s (LangChain) and ~2.7s (LlamaIndex), yet the frontend with all 3 enabled takes 2-3x longer than the slowest single pipeline.

This is the #1 performance bottleneck identified during profiling investigation.

## What Changes

1. **Add `asyncio.Lock` to `MLXLLM.generate()` and `generate_stream()`** — prevents concurrent GPU access by serializing generation calls at the Python level. When 3 backends hit the LLM simultaneously, the first acquires the lock, the others queue until it completes. This matches the Metal accelerator's actual concurrency model (single inference stream).

2. **Profile comparison** — Run the existing real-model profiling tests before and after the fix to measure improvement. Expected: frontend wall-clock time with 3 backends ≈ max(individual pipeline times) rather than sum + contention overhead.

## Capabilities

### New Capabilities
- `concurrent-generation`: Serializes concurrent LLM generation calls on the shared MLXLLM singleton via `asyncio.Lock`, preventing GPU-level contention when multiple RAG backends or concurrent requests hit the model simultaneously.

### Modified Capabilities
*(None — no existing specs are affected. This is a performance fix within the existing LLM singleton.)*

## Impact

- **`src/domain/services/llm.py`** — Add `self._generate_lock = asyncio.Lock()` in `MLXLLM.__init__()`. Acquire in `generate()` and `generate_stream()` before calling `asyncio.to_thread()` with MLX inference. The lock scope covers the full `asyncio.to_thread(generate, ...)` call so threads are never spawned concurrently.
- **`src/core/config.py`** — Optionally add `LLM_GENERATION_LOCK_TIMEOUT` setting (default 300s) to prevent deadlock.
- **No API contract changes, no database schema changes, no new dependencies.**
