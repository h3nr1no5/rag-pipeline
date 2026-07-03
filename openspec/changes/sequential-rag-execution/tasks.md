## 1. Backend: Change execute_rag_query to sequential

- [x] 1.1 Replace `asyncio.gather(*tasks)` at line 517 in `_executor.py` with a sequential `for` loop: `for b in backends_to_run: await run_backend(b)`
- [x] 1.2 Update docstring on `execute_rag_query()` to reflect sequential execution (remove "Runs all configured backends concurrently" language)
- [x] 1.3 Keep the 300s total-timeout guard as a safety net (update the existing timeout check to account for sequential execution)

## 2. Frontend: Simplify fragment polling

- [x] 2.1 Review the `@fragment` in `3_💬_Chat.py` and simplify result processing — results now arrive in predictable order, so out-of-order rendering logic can be removed
- [x] 2.2 Remove or simplify `rendered_backends` dedup set — with sequential execution, each result arrives once, so dedup may not be needed (keep as defensive measure)
- [x] 2.3 Update the timeout guard to use 300s total-timeout (per Decision 4 in design)

## 3. Update tests

- [x] 3.1 Update `test_async_query.py` to verify sequential execution: inject known-delay backends, confirm they execute in order rather than concurrently
- [x] 3.2 Write a sequential-order test: run 3 backends (one with a short delay, one with a medium delay, one with a long delay), verify they complete in the exact order specified
- [x] 3.3 Write a failure-continuation test: inject a failing backend in position 2 of 3, verify backend 1 completes, backend 2 fails, backend 3 still executes
- [x] 3.4 Run existing integration tests to confirm no regression: `uv run pytest tests/integration/ -v -k "query"`

## 4. Verification

- [x] 4.1 Run `uv run pytest tests/unit/ -v` to confirm no regression in unit tests
- [x] 4.2 Run `uv run pytest tests/integration/ -v -k "query"` to confirm query integration tests pass
- [x] 4.3 Manual smoke test: start backend + frontend, submit a query with 3 backends, verify backends execute in order and all results appear correctly
