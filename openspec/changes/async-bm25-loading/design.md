## Context

LangChain and LlamaIndex query endpoints return 180s read timeouts while the main cosine path works fine. Investigation revealed two compounding causes:

1. **Synchronous BM25 building**: `BM25Retriever.from_documents()` (LangChain) and `BM25Okapi(tokenized_docs)` (LlamaIndex) run synchronously in async handlers, freezing the event loop during CPU-bound tokenization.
2. **Sequential model warmup**: `_load_models()` loads cross-encoder → LLM → embedder sequentially. If cross-encoder takes long, downstream models are delayed, pushing first-request response past the 180s timeout.

The model readiness gate (previously removed in commits `25f49b0`/`ee91dde`) had been protecting against this by blocking requests until warmup completed. With the gate gone, requests arrive mid-warmup and hit the synchronous BM25 code path.

## Goals / Non-Goals

**Goals:**
- Eliminate 180s read timeouts on `/api/v1/query/langchain` and `/api/v1/query/llamaindex`
- Keep the event loop responsive during BM25 index building
- Reduce effective cold-start latency

**Non-Goals:**
- Restoring the model readiness gate or WarmupState architecture (not needed if BM25 is async and warmup is concurrent)
- Changing the public API or request/response contracts
- Changing cosine-backend behavior (already works)

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| BM25 offloading | `asyncio.to_thread()` | Python 3.11+ native API, no new dependencies. Runs CPU-bound tokenization in default thread pool. `run_in_executor` is equivalent but more verbose. |
| Concurrent warmup | `asyncio.gather()` | Standard library, trivial to apply. Reduces cold-start from `sum(all tasks)` to `max(slowest task)`. |
| No readiness gate | Skip | Async BM25 + concurrent warmup eliminates the race. If all models load concurrently, and BM25 runs in a thread, the request path never blocks. |

## Risks / Trade-offs

- **Thread safety of BM25Retriever.from_documents**: Reads from a list of text strings (not mutated). Safe.
- **Cross-encoder re-ranker in LangChain**: `CrossEncoderReRanker` is only created during warmup, not per-request. Not affected.
- **Model loading order**: `gather()` means any model can finish first. `get_llm()` and `get_embedder()` are idempotent singletons — concurrent calls are safe.
