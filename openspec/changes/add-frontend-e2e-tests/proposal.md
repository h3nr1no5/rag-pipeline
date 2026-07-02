## Why

The Streamlit chat UI has a rendering bug where the backend successfully returns an answer but the answer never appears on screen — not during polling and not after completion. This breaks the core user workflow. Additionally, the project has no frontend end-to-end test coverage, making it impossible to catch UI-level regressions in CI.

## What Changes

- **Add `pytest-playwright`** to dev dependencies and install Chromium browser
- **Create `tests/frontend/` directory** with Playwright-based server lifecycle fixtures (FastAPI backend + Streamlit frontend in subprocesses)
- **Create `tests/frontend/test_chat_display.py`**: full end-to-end test covering login → document upload → query submission → assert answer appears in the DOM
- **Fix the "answer never appears" rendering bug** in `client/pages/3_💬_Chat.py`:
  - Investigate and fix root cause in the `poll_query_task()` function or the message rendering loop
  - Likely root causes: auth token handling in polling requests, falsy answer content guard, or silent rendering failure in `st.markdown()`

## Capabilities

### New Capabilities
- `frontend-e2e-tests`: Playwright-based browser tests for the Streamlit UI. Provides fixtures to start/stop backend + frontend servers, authenticate, upload documents, submit queries, and verify DOM state.

### Modified Capabilities
- `chat-interface`: Fix the answer rendering path so that completed RAG query answers are always displayed in the chat UI. The current implementation renders answers during polling via `poll_query_task()` but answers may not survive a full-page `st.rerun()` or may be silently skipped due to the answer-content guard.

## Impact

- **Dependencies**: `pytest-playwright` added to dev dependency group; Playwright Chromium browser downloaded (~300MB)
- **New files**: `tests/frontend/conftest.py`, `tests/frontend/test_chat_display.py`
- **Modified files**: `client/pages/3_💬_Chat.py` (rendering fix), `pyproject.toml` (dependency addition)
- **No new production dependencies** — `pytest-playwright` is test-only
