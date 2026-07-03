## Why

The DSPy API docs pipeline uses `asyncio.run()` inside sync `forward()` methods to bridge DSPy's synchronous contract with the codebase's async-native retrieval and LLM infrastructure. This causes `RuntimeError: Event loop is already running` in pytest-asyncio tests and prevents running the DSPy pipeline without the `API_DOCS_DSPY_ENABLED` env-var escape hatch. DSPy >=2.6 provides native async support via `aforward()`/`acall()`, making this sync↔async bridging unnecessary.

## What Changes

- Add `async def aforward()` to `APIDocRAG` (module.py) — chain-of-thought generation and fallback run via `acall()` instead of sync `forward()`
- Add `async def aforward()` to `MLXDspyLM` (lm_adapter.py) — delegates directly to `await self._llm.generate()` instead of `asyncio.run()`
- Replace `asyncio.to_thread(module, ...)` in manager.py with `await module.acall(...)`
- `_forward_impl()` retrieval switches from `asyncio.run(retrieve(...))` to `await retrieve(...)`
- Simplify or remove `api_docs_dspy_enabled` env var — the async path works natively in all contexts
- Tests no longer need `API_DOCS_DSPY_ENABLED=false` override in conftest.py

## Capabilities

### New Capabilities
- `dspy-native-async`: Native async DSPy pipeline execution — the APIDocRAG module and MLXDspyLM adapter gain async `aforward()` methods, eliminating `asyncio.run()` from the hot path. The env-var gating becomes unnecessary since the pipeline no longer conflicts with running event loops.

### Modified Capabilities
- `api-docs-rag`: The DSPy pipeline execution model changes from thread-offloaded sync (`asyncio.to_thread` + `forward()`) to native async (`acall()` + `aforward()`). The response shape and quality remain identical.

## Impact

- **3 source files**: `manager.py`, `module.py`, `lm_adapter.py`
- **1 env var**: `API_DOCS_DSPY_ENABLED` — can be simplified or removed
- **Test files**: conftest.py env-var override removed; DSPy warmup tests no longer need to force-enable; integration tests exercise the async path naturally
- **No new dependencies**: DSPy >=2.6 already installed (confirmed by uv.lock)
- **No breaking changes**: The public API (`ApiDocPipelineManager.query()`) is unchanged. DSPy module sync `forward()` is preserved as a dormant code path for compilation scenarios.
