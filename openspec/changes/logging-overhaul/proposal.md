## Why

RAG pipeline logging in development is drowning in noise. A single query generates ~15 log lines (~3,000 bytes at INFO, ~5,000 at DEBUG), dominated by repetitive stage gates in `_retrieval.py`, a full prompt dump from `llm.py`, and duplicate request tracking from the middleware. This makes it impossible to spot real signals during development — latency spikes, verification failures, error patterns — without drowning in ceremony.

We need logging to serve the developer, not the other way around. This change cuts per-query log volume by ~60% while adding runtime drill-in capability when specific modules need debugging.

## What Changes

- **New toggle endpoint** `GET/PUT /api/v1/debug/logging` — auth-gated, runtime control of per-module log levels. Developers can pin a specific module to DEBUG without restarting or touching `.env`.
- **DevModeFilter** — static `logging.Filter` that reduces uvicorn access log verbosity and suppresses noisy framework-level messages at MODERATE+ levels.
- **Collapse retriever logging** — merge 7 INFO-level log lines in `_retrieval.py` into a single structured event with context (top_k, results count, latency).
- **Replace prompt dump** — remove the raw prompt dump at DEBUG level in `llm.py`. Replace with `prompt_hash + prompt_length` for debuggability without bloat.
- **Remove middleware redundant lines** — drop the "request started" log line in `MonitoringMiddleware`. The uvicorn access log already covers request entry.
- **Consolidate init celebration logs** — retriever and embedder initialization logs (e.g., "BM25 built", "FAISS built", "Embedder loaded") collapse into 1 structured event per subsystem instead of N individual lines.
- **Demote "Embedder loaded" to DEBUG** — this fires per-query and has no place at INFO.

## Capabilities

### New Capabilities
- `debug-logging`: Runtime per-module log level control via auth-gated API endpoint. Provides GET (current levels) and PUT (set module:level mappings) with persistence only in-memory (resets on restart). Includes logging filter infrastructure for dev-mode noise reduction.

### Modified Capabilities
<!-- None — all remaining changes are internal implementation improvements that do not change spec-level behavior of existing capabilities -->

## Impact

- **New route**: `GET /api/v1/debug/logging` and `PUT /api/v1/debug/logging`
- **New module**: `src/core/logging.py` — `DevModeFilter`, toggle mechanism, structured event helpers
- **Modified files**:
  - `src/api/routes/query/routes.py` — middleware logging removal
  - `src/domain/services/retrieval/_retrieval.py` — collapse 7→1
  - `src/domain/services/llm.py` — replace prompt dump
  - `src/domain/services/embedding.py` — demote "Embedder loaded"
  - `src/domain/services/processor.py` — deduplicate branches
  - `src/infrastructure/retrieval/**` — consolidate init logs
- **No new dependencies** — uses stdlib `logging` only
- **No config changes** — `.env` `LOG_LEVEL` remains as default; overrides are runtime-only
