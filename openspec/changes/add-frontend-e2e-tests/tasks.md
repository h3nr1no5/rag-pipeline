# Tasks — add-frontend-e2e-tests

## Task 1: Add pytest-playwright to dev dependencies

- [ ] Add `pytest-playwright` to `[tool.uv.dev-dependencies]` in `pyproject.toml`
- [ ] Run `uv sync` to install the new dependency
- [ ] Run `playwright install chromium` to download the Chromium browser binary

## Task 2: (removed — no custom entrypoint needed)

## Task 3: Create frontend e2e test fixtures (conftest.py)

- [ ] Create `tests/frontend/conftest.py` with:
  - `backend_server` fixture (session-scoped):
    - Generate random SQLite path
    - Start `python -m uvicorn src.api.main:app --host 127.0.0.1 --port <random>` subprocess
    - Set `DATABASE_URL=<sqlite_path>` in the subprocess env (isolated DB)
    - Health check: poll `GET /api/v1/documents/strategies/types` until HTTP 200 (30s timeout, no auth, doesn't trigger model loading)
    - Teardown: send SIGTERM, wait for process exit (10s), SIGKILL fallback, clean up SQLite file
  - `frontend_server` fixture (session-scoped, depends on `backend_server`):
    - Start `streamlit run client/app.py --server.port=<random> --server.headless=true`
    - Wait for HTTP 200 on the Streamlit URL (30s timeout)
    - Teardown: send SIGTERM, wait for process exit, SIGKILL fallback
  - `page` fixture (function-scoped):
    - Create Playwright Chromium browser context (headless)
    - Create and yield a `page` object
    - Close context on teardown (isolated cookies per test)

## Task 4: Fix the "answer never appears" rendering bug

- [ ] Investigate the exact root cause in `client/pages/3_💬_Chat.py`:
  - [ ] Add temporary logging to trace the poll cycle when bug manifests
  - [ ] Verify auth token handling in polling requests (`async_query_poll`)
  - [ ] Check the `if r.get("answer"):` guard on line ~618 for falsy values
  - [ ] Trace the `status == "completed"` code path (lines ~681-715) to see if answers are appended before cleanup
  - [ ] Monitor task count in backend logs — verify it doesn't grow unexpectedly across multiple query submissions (could indicate frontend creating duplicate tasks)
- [ ] Implement the fix:
  - **Option A** (likely): Ensure results are appended to `st.session_state.messages` BEFORE the cleanup block clears `task_started`
  - **Option B**: Add a safety re-render pass in the top message loop for backend results that were never rendered
  - **Option C**: Ensure `cache_key` guard does not prevent the final answer from being stored
- [ ] Verify fix by manual test (run the app, submit a query, confirm answer appears)
- [ ] Remove temporary logging

## Task 5: Write the end-to-end test

- [ ] Create `tests/frontend/test_chat_display.py` with:
  - Test fixture uses session-scoped `backend_server` + `frontend_server`, function-scoped `page`
  - `test_full_flow`: login → upload (with api-docs strategy) → query → assert answer in DOM
    - Navigate to Streamlit URL
    - Fill email/password and click Login
    - Verify redirection to chat page (title contains "Chat with Documents")
    - Navigate to Documents page
    - Select the "API Documentation" strategy from the strategy dropdown (`st.selectbox`)
    - Upload `tests/docs/test docx.docx` via the file uploader
    - Wait for document processing to complete (poll for status indicator)
    - Navigate to Chat page
    - Select the uploaded document in the sidebar
    - Type `"how to change logo?"` in the chat input and press Enter
    - Wait for assistant answer to appear in the DOM (180s timeout — real model inference is slow)
    - Assert at least one assistant chat message exists with non-empty text content
    - Note: using real models, so no canned string to match; assertion is "any non-empty answer appeared"

## Task 6: Ensure environment is set up for real models

- [ ] Verify `HF_HUB_OFFLINE=1` is set (models cached from dev use, skip re-download)
- [ ] Verify `HF_TOKEN` is set if using gated models
- [ ] Confirm the MLX model `mlx-community/Qwen2.5-1.5B-Instruct-4bit` is cached locally (~500MB)
- [ ] Confirm the embedder model `sentence-transformers/all-mpnet-base-v2` is cached locally (~1GB)

## Task 7: Verify everything works

- [ ] Run `uv run pytest tests/frontend/ -v` and confirm tests pass
- [ ] Run `uv run pytest tests/unit/ -v` to confirm no regressions
- [ ] Run `uv run pytest tests/integration/ -v` to confirm no regressions
- [ ] Kill any orphaned subprocesses (port cleanup)

## Task 8: Sync delta specs to main specs

- [ ] Run `/openspec.sync` or equivalent to promote `specs/chat-interface/spec.md` delta to main `specs/`
- [ ] Run `/openspec.sync` to promote `specs/frontend-e2e-tests/spec.md` to main `specs/`
