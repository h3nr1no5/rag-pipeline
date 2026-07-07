## Why

The current `execute_rag_query()` dispatches all RAG backends concurrently via `asyncio.gather()`. However, this concurrency is illusory — all 3 backends share the same MLXLLM singleton with a `_generate_lock` that serializes GPU inference, making total wall time the sum of all 3 generations (~240s). The parallel structure adds significant complexity: progressive frontend rendering with volatile fragment output, lock contention management, race conditions between backends, and a class of bugs where fast answers appear then disappear. Changing to sequential execution eliminates all of this while keeping the same total wall time.

## What Changes

1. **Change `execute_rag_query()` to sequential backend execution** — Replace `asyncio.gather(*tasks)` at line 517 in `_executor.py` with a simple `async for` or sequential `for` loop that runs each backend one at a time. Each backend still updates progress and stores results independently.

2. **Simplify frontend fragment polling** — With sequential execution, backends complete one at a time in order. The frontend fragment no longer needs to handle out-of-order results or progressive rendering of partial parallel results. Simplify the fragment to poll for completion and display results as they arrive sequentially.

3. **Remove the 120s timeout guard (or extend significantly)** — With sequential execution, each individual backend takes ~80s. The first backend completes well within 120s. The timeout guard can be extended or removed since the risk of a backend hanging for >120s is low for any single backend.

4. **Remove unnecessary `concurrent-generation` complexity** — The `_generate_lock` in `MLXLLM` still serves a purpose (protecting against concurrent non-RAG calls), but the multi-backend contention scenario that drove its design is eliminated.

## Capabilities

### New Capabilities

- `sequential-query-execution`: Backend execution model that runs selected RAG backends one at a time in sequence, eliminating parallel dispatch complexity.

### Modified Capabilities

- *(None — this is a new execution model, no existing specs to modify)*

## Impact

- **Affected code**:
  - `src/api/routes/query/_executor.py` — `execute_rag_query()` change `asyncio.gather()` → sequential loop
  - `client/pages/3_💬_Chat.py` — simplify fragment polling (no progressive rendering of parallel results)
- **Specs affected**: None directly. The `concurrent-generation` spec (`openspec/specs/concurrent-generation/spec.md`) is unchanged — the `_generate_lock` remains in place for other use cases.
- **No new dependencies**
- **No API changes** — `/query/start` and `/query/status` contracts remain the same
- **BREAKING (internal)**: Backend execution model changes from parallel to sequential. This is an internal behavioral change — no external contract is affected.
