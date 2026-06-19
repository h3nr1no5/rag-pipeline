## 1. Add `include_citations` to sync client helpers

- [ ] 1.1 Add `include_citations` parameter to `query_sync()` in `client/utils/query.py` and forward it in the request payload
- [ ] 1.2 Add `include_citations` parameter to `query_langchain_sync()` in `client/utils/query.py` and forward it in the request payload
- [ ] 1.3 Add `include_citations` parameter to `query_llamaindex_sync()` in `client/utils/query.py` and forward it in the request payload

## 2. Replace streaming calls with sync calls in Chat page

- [ ] 2.1 Update imports in `client/pages/3_💬_Chat.py`: replace streaming imports with sync imports (`query_sync`, `query_langchain_sync`, `query_llamaindex_sync`)
- [ ] 2.2 Replace cosine streaming call (`stream_query_with_placeholder`) with `query_sync()` call, adapting the return value (dict) to match the existing destructuring
- [ ] 2.3 Replace LangChain streaming call (`stream_query_langchain_with_placeholder`) with `query_langchain_sync()`, adapting return value
- [ ] 2.4 Replace LlamaIndex streaming call (`stream_query_llamaindex_with_placeholder`) with `query_llamaindex_sync()`, adapting return value
- [ ] 2.5 Verify `include_citations` is passed through in the `**params` dict for all three sync calls
- [ ] 2.6 Verify the history message rendering loop (`render_message`) still works correctly with the stored response data

## 3. Remove unused streaming functions

- [ ] 3.1 Remove `_strip_display_text()` function from `client/utils/query.py`
- [ ] 3.2 Remove `stream_query()` function from `client/utils/query.py`
- [ ] 3.3 Remove `stream_query_with_placeholder()` function from `client/utils/query.py`
- [ ] 3.4 Remove `stream_query_langchain()` and `stream_query_langchain_with_placeholder()` functions from `client/utils/query.py`
- [ ] 3.5 Remove `stream_query_llamaindex()` and `stream_query_llamaindex_with_placeholder()` functions from `client/utils/query.py`

## 4. Verify and test

- [ ] 4.1 Run `uv run pytest -v` to confirm all tests pass (streaming endpoint tests should still pass since endpoints are unchanged)
- [ ] 4.2 Start the backend (`uvicorn src.api.main:app --reload --port 8000`) and frontend (`streamlit run client/app.py --server.port 8501`) and verify formatting is preserved in chat responses
- [ ] 4.3 Verify citation toggle works with sync endpoints (test `include_citations=True` and `include_citations=False` render correctly)
- [ ] 4.4 Verify error handling works (bad document IDs, server errors map to proper user-facing messages)
- [ ] 4.5 Verify historical message replay preserves formatting on page refresh
