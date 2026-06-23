## 1. Backend Schema Fix

- [x] 1.1 Add `engine_type: str` field to `ChunkingStrategyResponse` in `src/api/schemas/document.py` (after `is_system`, before `created_at`)
- [x] 1.2 Run existing tests (`uv run pytest tests/ -v`) to confirm schema change doesn't break anything

## 2. Frontend — Chat Page RAG Backend Selection

- [x] 2.1 In `client/pages/3_💬_Chat.py`, compute `all_api_docs` flag: `True` when selected documents exist and all have `engine_type == "api-docs"`
- [x] 2.2 Add `disabled=all_api_docs` and `help="Not available for API documentation documents"` to the Cosine Sim, LangChain, and LlamaIndex checkboxes
- [x] 2.3 Exclude disabled backends from `selected_rags` list so no query is sent to incompatible endpoints when `all_api_docs` is true

## 3. Testing

- [x] 3.1 Add integration test verifying `ChunkingStrategyResponse` includes `engine_type` field in GET /api/v1/strategies response
- [x] 3.2 Add unit test for `all_api_docs` detection logic (mixed selections, all-api-docs, no-api-docs)
- [x] 3.3 Manually verify: upload an api-docs docx/pdf, select it in chat, confirm API Docs checkbox appears and main 3 are disabled with tooltip

## 4. Security & Code Review

- [x] 4.1 Security review: confirm no auth bypass, no data exposure (engine_type is non-sensitive)
- [x] 4.2 Code review: verify selected_rags exclusion logic, disabled state interaction, mixed-selection edge cases

## 5. Final Verification

- [x] 5.1 Run full test suite: `uv run pytest tests/ -v`
- [x] 5.2 Run linter: `uv run ruff check .`
- [x] 5.3 Run type checker: `uv run mypy src/`
