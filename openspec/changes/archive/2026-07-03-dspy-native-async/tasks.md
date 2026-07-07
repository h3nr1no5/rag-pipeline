## 1. LM Adapter — add async aforward

- [x] 1.1 Add `async def aforward()` to `MLXDspyLM` that calls `await self._llm.generate(final_prompt, max_tokens=max_tokens, temperature=temperature)` directly, returning an OpenAI-chat-compatible `SimpleNamespace`
- [x] 1.2 Add `async def _resolve_prompt()` helper (extract from sync `forward()` for reuse) so both sync and async paths share prompt resolution logic

## 2. Module — add async aforward

- [x] 2.1 Add `async def aforward()` to `APIDocRAG` with input validation, temperature/max_tokens override wrapping, and cleanup in a `try/finally` block (mirroring `forward()`)
- [x] 2.2 Add `async def _aforward_impl()` that: (a) `await retrieve()` via hybrid retriever, (b) `await self.response_generator.acall(context=..., question=...)`, (c) validates assertions, (d) on failure `await self.fallback_generator.acall(...)`
- [x] 2.3 Ensure `aforward()` returns the same dict shape as `forward()`: answer, rationale, citations, relevant_functions, relevant_types, confidence, primary_chunk_id, retrieved_chunks, assertions_passed, used_fallback

## 3. Manager — switch dispatch

- [x] 3.1 In `_query_dspy()`, replace `asyncio.to_thread(module, ...)` with `await module.acall(question=query_text, top_k=top_k, temperature=temperature, max_tokens=max_tokens)`
- [x] 3.2 Verify `_build_dspy_response()` handles the output from `acall()` identically to `forward()` (same dict keys)
- [x] 3.3 Confirm the fallback-on-exception path in `query()` (lines 411-434) still works — if `acall()` raises, it logs a warning and delegates to `_query_fallback()`

## 4. Tests — update and add

- [x] 4.1 Remove `API_DOCS_DSPY_ENABLED=false` from `tests/conftest.py` os.environ override
- [x] 4.2 Remove `os.environ["API_DOCS_DSPY_ENABLED"] = "false"` from `tests/integration/test_rag_pipelines_e2e.py` and `tests/integration/test_api_docs_e2e.py`
- [x] 4.3 Update `tests/integration/test_dspy_warmup.py` — remove the function-level env var override (no longer needed; the async path works in pytest-asyncio)
- [x] 4.4 Add unit tests for `MLXDspyLM.aforward()` — verify async generation returns correct response shape
- [x] 4.5 Add unit tests for `APIDocRAG.aforward()` — verify async pipeline produces same results as sync `forward()`

## 5. Config — simplify env var

- [x] 5.1 Remove the now-unnecessary `asyncio` import from `module.py` (only used for `asyncio.run()` which is eliminated from the hot path)

## 6. Verification

- [x] 6.1 Run `uv run pytest -v -m "not slow"` — all tests pass with DSPy enabled in the async path
- [x] 6.2 Run `uv run ruff check .` and `uv run mypy src/` — no lint or type errors
