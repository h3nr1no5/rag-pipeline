## Context

The DSPy API docs pipeline currently bridges DSPy's synchronous `forward()` contract with the codebase's async-native retrieval and LLM infrastructure via `asyncio.run()` inside `asyncio.to_thread()` workers. This produces 2-3 `asyncio.run()` calls per query (retrieval + 1-2 LLM generations). The calls crash in pytest-asyncio tests because `asyncio.run()` cannot nest inside a running event loop. The current mitigation is the `API_DOCS_DSPY_ENABLED=false` env var that skips the DSPy path entirely in tests.

DSPy >=2.6 provides native async support via `acall()` / `aforward()`, enabling the entire pipeline to run asynchronously without sync↔async bridging.

## Goals / Non-Goals

**Goals:**
- Eliminate all `asyncio.run()` calls from the DSPy query hot path
- Enable the DSPy pipeline to run natively in pytest-asyncio tests without env-var gating
- Simplify or remove the `API_DOCS_DSPY_ENABLED` env var
- Preserve identical response shape and quality
- Retain sync `forward()` as a dormant code path for DSPy compilation scenarios

**Non-Goals:**
- No changes to the public query API (`ApiDocPipelineManager.query()`)
- No new external dependencies
- No changes to the response format or frontend
- No changes to non-DSPy query paths (fallback, LangChain, LlamaIndex)

## Decisions

### Decision 1: Use DSPy native async vs. dedicated event-loop thread

**Choice**: Use DSPy's built-in `acall()` / `aforward()` API.

**Rejected alternative**: A dedicated DSPy event-loop thread with `run_coroutine_threadsafe`. This approach had a deadlock risk (sync DSPy internals blocking the dedicated loop), required a new thread lifecycle with cleanup complexity, and introduced cross-loop resource sharing issues with `asyncio.Lock` in the shared `MLXLLM` singleton on Python 3.11.

**Rationale**: DSPy >=2.6's async support is the architecturally correct solution — it aligns with the framework's intended API, introduces zero new threads or event loops, and has minimal code change surface (3 files).

### Decision 2: `MLXDspyLM` async adapter design

**Choice**: Add `async def aforward()` to `MLXDspyLM` that calls `await self._llm.generate()` directly. Keep sync `forward()` for backward compatibility.

**Rationale**: DSPy's async path (`Predict.acall()`) checks if the LM adapter defines a coroutine-compatible forward method. If not, it falls back to `asyncify` (thread pool). By providing `aforward()`, we get direct `await` — no sync bridge needed. The sync `forward()` is only used by DSPy's compilation internals, which we don't use at runtime.

### Decision 3: `APIDocRAG` async module design

**Choice**: Add `async def aforward()` to `APIDocRAG` that replaces:
- `asyncio.run(retrieve(...))` → `await retrieve(...)`
- `response_generator(...)` → `await response_generator.acall(...)`
- `fallback_generator(...)` → `await fallback_generator.acall(...)`

**Rationale**: This eliminates all `asyncio.run()` from the pipeline. The sync `forward()` delegates to `_forward_impl()` as before (preserving temperature/max_tokens wrapping logic). The async `aforward()` has its own `_aforward_impl()` that mirrors the logic but uses `await`.

### Decision 4: Manager dispatch path

**Choice**: Replace `asyncio.to_thread(module, ...)` with `await module.acall(...)`.

**Rationale**: With the entire pipeline async, thread offloading is unnecessary. The DSPy module runs directly on the caller's event loop — whether that's the FastAPI server loop or pytest-asyncio's test loop.

### Decision 5: `API_DOCS_DSPY_ENABLED` env var handling

**Choice**: Keep the setting but change its default to `true` and remove the root-conftest override. The setting now guards DSPy enablement at the feature level rather than working around a runtime crash. If DSPy's sync `forward()` is ever needed at runtime (not currently the case), the old `asyncio.run()` conflict could resurface — but the hot path no longer triggers it.

**Rationale**: The env var still serves a purpose for disabling the DSPy pipeline entirely (e.g., if DSPy itself has issues). But it no longer needs to be `false` in tests, since the async path works natively with pytest-asyncio.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| DSPy 2.6 async support (`acall()` → `lm.aforward()`) may have edge cases with custom `ChainOfThought` subclasses | Sync `forward()` + env-var fallback remains available. The async path mirrors the sync logic identically. |
| `MLXLLM.generate()` uses `asyncio.Lock` (`_generate_lock`) — must work correctly on the same event loop as the caller | The lock is acquired on the caller's event loop. Since both DSPy and non-DSPy paths now run on the same loop (no thread offloading), there is no cross-loop lock conflict. |
| Sync `forward()` still uses `asyncio.run()` for compilation paths | DSPy compilation is not used at runtime. The sync path is tested separately and only triggers `asyncio.run()` in contexts without a running loop (CLI scripts, compilation). |
| Test coverage gap for the new async code path | Integration tests with `API_DOCS_DSPY_ENABLED=true` exercise the async path directly. Unit tests for `aforward()` added alongside existing `forward()` tests. |
