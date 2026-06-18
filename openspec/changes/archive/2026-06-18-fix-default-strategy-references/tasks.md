## 1. Fix Frontend Fallback

- [x] 1.1 In `client/pages/4_📁_Documents.py`, replace `{"Default": "default"}` with `{"Recursive": "recursive"}` on the `strategy_names` fallback assignment (line 200)

## 2. Fix Backend Query Route Fallbacks

- [x] 2.1 In `src/api/routes/query/routes.py`, replace all 6 occurrences of `else "default"` with `else "recursive"` using replaceAll

## 3. Verify

- [x] 3.1 Run `uv run pytest -v` to confirm all tests still pass
