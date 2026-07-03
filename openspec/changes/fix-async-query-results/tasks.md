## 1. Fix: Fragment timeout guard calls st.rerun()

- [ ] 1.1 Add `st.rerun()` call in the 120-second timeout guard block in `3_💬_Chat.py` before the `return` statement, ensuring the main message loop re-renders accumulated results.
- [ ] 1.2 Verify ordering: `st.error()` → `st.session_state.task_started = False` → `st.rerun()` → `return`. Add a comment noting `return` after `st.rerun()` is defensive (rerun exits the fragment).
- [ ] 1.3 Add `_FRONTEND_QUERY_TIMEOUT` constant backed by `FRONTEND_QUERY_TIMEOUT` env var (default 120s) and use it in the timeout guard instead of hardcoded `120`.
- [ ] 1.4 Handle invalid env var value: catch `ValueError` from `int()` conversion and fall back to 120s default.

## 2. Fix: Add backend timeout to LangChain execution

- [ ] 2.1 Add a `LANGCHAIN_TIMEOUT` constant (default 240) in `_executor.py` — make it configurable via module-level constant.
- [ ] 2.2 Wrap the `qa_chain.generate()` call in `_execute_langchain_backend()` with `asyncio.wait_for(..., timeout=LANGCHAIN_TIMEOUT)`.
- [ ] 2.3 Add `except asyncio.TimeoutError` handler that returns a timeout error dict with `backend="langchain"`, `answer=null`, `error="LangChain backend timed out"`.
- [ ] 2.4 Write integration test: inject a slow LLM double that exceeds timeout, verify LangChain returns timeout error without affecting other backends.

## 3. Confirm: Lock scope verification (no restructuring needed)

- [ ] 3.1 Confirm (code review) that all 3 backend executors separate retrieval from LLM generation: `_execute_cosine_backend` → retrieval first, generate later; `_execute_llamaindex_backend` → retrieval first, generate later; `_execute_langchain_backend` → `retriever.retrieve()` (line 265 in chain_langchain.py) before `llm.generate()` (line 289).
- [ ] 3.2 Add trace-level logging (`logger.debug`) at `_generate_lock` acquire/release points in `MLXLLM.generate()` to verify concurrent retrieval execution in production.
- [ ] 3.3 Write integration test: instrument retrieval phases with timestamps, run all 3 backends via `asyncio.gather()`, verify retrieval timestamps overlap (and `generate()` calls do not).

## 4. Fix: Refactor fragment to use main-loop rendering (stable messages)

- [ ] 4.1 Remove inline `st.chat_message()` and `st.expander()` rendering from inside the fragment's result-processing loop in `3_💬_Chat.py` (lines ~606-671). The fragment must NOT render volatile UI elements.
- [ ] 4.2 Change the fragment to only poll for results, store new answers in `st.session_state.messages` with proper `role` and `content` fields, and call `st.rerun()` when new results are available.
- [ ] 4.3 Update the `rendered_backends` tracking set (keyed on `f"{task_id}_{backend_name}"`) to prevent duplicate message entries when `st.rerun()` cycles.
- [ ] 4.4 **Mandatory**: Add a short-circuit guard at the end of the fragment's poll-processing logic: if no new results since last poll (compare `len(results)` against `rendered_backends` count), return without calling `st.rerun()`. This prevents infinite rerun loops.
- [ ] 4.5 Update `render_message()` in `chat_message.py` to show dynamic source count in the expander label: `f"📚 Sources ({count})"` instead of static `"📚 Sources"`.
- [ ] 4.6 Verify the main message loop (lines ~460-512) renders all `st.session_state.messages` entries via `render_message()` — confirm it handles the stored message format (including `sources`, `reasoning_hint`, `confidence`, `relevant_functions`, `relevant_types`).

## 5. Update tests

- [ ] 5.1 Add `SlowTestLLM` test double (or `delay` parameter to `TestLLM`) in `tests/doubles/llm.py` that injects configurable sleep before returning, for testing timeout behavior.
- [ ] 5.2 Write unit test for `_execute_langchain_backend` timeout: inject `SlowTestLLM` that sleeps >240s, verify `asyncio.TimeoutError` is caught and returns error dict.
- [ ] 5.3 Write integration test for backend result isolation: execute 3 backends with one configured to fail, verify the other 2 return normally.
- [ ] 5.4 Write integration test for concurrent retrieval overlap: instrument retrieval phases with timestamps, verify they run concurrently under `asyncio.gather()`.
- [ ] 5.5 Write E2E test (via Playwright) for timeout behavior: use `FRONTEND_QUERY_TIMEOUT=5`, submit query with 3 backends, wait for timeout error, verify completed answers persist alongside the error.

## 6. Verification

- [ ] 6.1 Run `uv run pytest tests/unit/ -v` to confirm no regression in unit tests.
- [ ] 6.2 Run `uv run pytest tests/integration/ -v -k "query"` to confirm query integration tests pass.
- [ ] 6.3 Run `uv run pytest tests/frontend/ -v --headed` to confirm E2E tests pass.
- [ ] 6.4 Manual smoke test: start backend + frontend, submit a query with 3 backends, verify all answers appear and persist.
- [ ] 6.5 Manual edge case: submit query where LangChain exceeds 120s but other backends complete, verify timeout behavior shows partial results.
