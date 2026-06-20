## 1. Frontend — Sidebar Toggle

- [x] 1.1 Add `include_citations` checkbox widget in the Parameters section, positioned between `response_length` and the "Save Parameters" button, using session state key `rag_include_citations` with default `True`
- [x] 1.2 Add `include_citations` to the `save_params()` dict so it persists to `chat_params.json`

## 2. Frontend — Query Wiring

- [x] 2.1 Add `"include_citations"` to the `params` dict that is passed as `**kwargs` to all three streaming functions (`stream_query_with_placeholder`, `stream_query_langchain_with_placeholder`, `stream_query_llamaindex_with_placeholder`)
- [x] 2.2 Verify the parameter flows through to the API request payload for all three backend endpoints

## 3. Testing

- [ ] 3.1 Manually verify: toggle checkbox, send query, confirm API request includes correct `include_citations` value
- [ ] 3.2 Manually verify: save params, reload page, confirm checkbox state is restored
- [ ] 3.3 Verify no regressions: all three backends still produce responses with citations when checkbox is checked