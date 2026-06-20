## 1. Schema — Add `clean_response` to QueryRequest

- [ ] 1.1 Add `clean_response: bool = Field(default=True, description="Apply response cleaning pipeline")` to `QueryRequest` in `src/api/schemas/query.py`

## 2. Backend Routes — Conditionally gate `clean_response()` calls

- [ ] 2.1 Gate `clean_response()` in cosine sync route (`src/api/routes/query/routes.py` around line 143)
- [ ] 2.2 Gate `clean_response()` in cosine stream route (`routes.py` around line 251)
- [ ] 2.3 Gate `clean_response()` in LangChain sync route (`routes.py` around line 314)
- [ ] 2.4 Gate `clean_response()` in LangChain stream route (`routes.py` around line 642)
- [ ] 2.5 Gate `clean_response()` in LlamaIndex sync route (`routes.py` around line 872)
- [ ] 2.6 Gate `clean_response()` in LlamaIndex stream route (`routes.py` around line 997)

Each route follows the same pattern:
```python
answer = raw_response
if request.clean_response:
    answer = clean_response(answer, request.response_length, request.include_citations)
```

## 3. Client Helpers — Forward `clean_response` parameter

- [ ] 3.1 Add `clean_response: bool = None` parameter to `query_sync()` in `client/utils/query.py`, include in payload when not None
- [ ] 3.2 Add same parameter to `query_langchain_sync()` in `client/utils/query.py`
- [ ] 3.3 Add same parameter to `query_llamaindex_sync()` in `client/utils/query.py`

## 4. Frontend — Add checkbox and persistence

- [ ] 4.1 Add "Clean Response" checkbox to Chat.py sidebar (`client/pages/3_💬_Chat.py`) alongside "Show Citations", defaulting to `saved_params.get("clean_response", True)`
- [ ] 4.2 Add `"clean_response"` key to `save_params()` dict and `load_saved_params()` restore
- [ ] 4.3 Include `clean_response` in the `params` dict built for query calls (around line 350-357)

## 5. Cleanup — Remove the `return text` hack

- [ ] 5.1 Remove `return text` line (line 133) from `clean_response()` in `src/domain/services/prompt_builder.py` to restore normal function

## 6. Verification

- [ ] 6.1 Run existing unit tests (`tests/unit/test_prompt_builder.py`) to verify `clean_response()` works correctly after removing `return text`
- [ ] 6.2 Run integration tests (`tests/integration/test_response_formatting.py`) to verify gating works end-to-end
- [ ] 6.3 Manually verify: toggle checkbox off → raw output includes deduplicated text that would otherwise be cleaned
