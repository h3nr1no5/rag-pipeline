## Why

When users select all 3 RAG backends (cosine similarity, LlamaIndex, LangChain) for a query, fast answers (cosine, LlamaIndex) appear via progressive rendering but then disappear ~120 seconds later, replaced by a timeout error or leaving empty components. The LangChain answer may take 240+ seconds and never be shown. This breaks the core UX promise of the multi-backend query feature — answers should remain visible once rendered.

The root cause is a combination of two issues: (1) a shared `asyncio.Lock` on the LLM singleton serializes all backends, making total latency the sum of all three, and (2) the frontend's 120-second timeout guard replaces the fragment-rendered answers with an error message without triggering a full page rerun, so the main message loop never picks up the stored results.

A frontend review identified additional refinements: the fragment refactoring requires a mandatory short-circuit guard to prevent infinite rerun loops, the lock investigation can be simplified since LangChain already separates retrieval from generation, and a `FRONTEND_QUERY_TIMEOUT` env var is needed for testable timeout behavior.

## What Changes

1. **Add `st.rerun()` to frontend timeout guard** — When the 120s timeout fires, trigger a full page rerun so the main message loop renders all accumulated results before the error is shown. Minimal change (3 lines).

2. **Add backend timeout to LangChain execution** — The async `_execute_langchain_backend()` has no timeout guard (unlike the synchronous LangChain route which has 160s). Add `asyncio.wait_for()` at 240 seconds with configurable timeout value.

3. **Confirm lock scope and add trace logging** — Investigation confirms the `_generate_lock` in `MLXLLM.generate()` is already scoped correctly (only held during GPU inference, not during retrieval). No restructuring needed. Add trace-level logging to confirm lock acquisition timing across backends.

4. **Refactor fragment to poll-only + main loop rendering** — The `@fragment(run_every=1.0)` currently renders results inline on every poll cycle, creating volatile output that is destroyed on each rerun. Change the fragment to only poll and store results, then use `st.rerun()` to let the main message loop handle stable rendering. A short-circuit guard (return early if no new results) is **mandatory** to prevent infinite rerun loops.

5. **Add `FRONTEND_QUERY_TIMEOUT` env var** — Allow overriding the 120s frontend timeout via environment variable for testability. Default 120s, overrideable to low values (e.g., 5s) in test mode.

6. **Fix `render_message()` expander label** — Update the `st.expander()` label from `"📚 Sources"` to `"📚 Sources ({count})"` to match the dynamic count the fragment was rendering.

## Capabilities

### New Capabilities

- `async-query-execution`: Backend async query flow for multi-backend RAG execution, including timeout handling and concurrent backend management.
- `frontend-query-polling`: Streamlit fragment-based polling mechanism for progressive result rendering, including timeout handling, stable message rendering, and test-mode timeout override.

### Modified Capabilities

- *(None — no existing spec files to modify)*

## Impact

- **Affected code**:
  - `client/pages/3_💬_Chat.py` — fragment polling, timeout guard, rendering logic, `FRONTEND_QUERY_TIMEOUT` env var
  - `client/components/chat_message.py` — `render_message()` expander label update
  - `src/api/routes/query/_executor.py` — timeout guard for LangChain backend, configurable timeout constant
  - `src/api/routes/query/routes.py` — may need minor adjustments for timeout handling propagation
  - `src/core/config.py` — may add `FRONTEND_QUERY_TIMEOUT` or `LANGCHAIN_TIMEOUT` settings
- **No new dependencies** — all fixes use existing infrastructure (asyncio, Streamlit fragments, `asyncio.wait_for`)
- **No API changes** — backend API contract remains identical
- **No breaking changes** — purely additive behavioral fixes
