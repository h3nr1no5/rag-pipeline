## Why

The `clean_response()` function applies aggressive post-processing to LLM output — deduplicating near-duplicate lines, removing repetition, truncating by length, and stripping various tokens. This processing can be too aggressive, removing nuance from the LLM's responses. Currently the only way to opt out is a `return text` hack in the source code. We need a proper frontend-configurable toggle so users can choose whether cleaning is applied per-query, with the setting persisted across sessions.

## What Changes

- **New `clean_response` field** on `QueryRequest` schema (boolean, default `True`)
- **Backend routes**: Conditionally skip `clean_response()` in all 3 RAG backends (cosine, LangChain, LlamaIndex) and their streaming variants when `clean_response=False`
- **Client helpers**: Forward `clean_response` parameter in `query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()`
- **Frontend sidebar**: Add "Clean Response" checkbox in Chat.py alongside existing "Show Citations"
- **Parameter persistence**: Save/load `clean_response` via `chat_params.json` alongside temperature, max_tokens, etc.
- **Remove `return text` hack**: Restore `clean_response()` to its working state (as committed in HEAD) since the toggle provides the escape hatch

## Capabilities

### New Capabilities
- `clean-response-toggle`: Frontend-configurable toggle to enable/disable LLM response cleaning, with parameter persistence

### Modified Capabilities
- `response-formatting`: Update spec requirements so `clean_response()` is conditionally applied based on the `clean_response` parameter, rather than being unconditional

## Impact

- **Schema**: `src/api/schemas/query.py` — add `clean_response: bool = True`
- **Backend routes**: `src/api/routes/query/routes.py` — 6 call sites (3 sync + 3 streaming) need conditional gating
- **Client helpers**: `client/utils/query.py` — 3 helper functions need new parameter
- **Frontend**: `client/pages/3_💬_Chat.py` — new checkbox in sidebar, add to `save_params()`/`load_saved_params()`
- **Spec**: `openspec/specs/response-formatting/spec.md` — update requirements to reflect conditional behavior
- **Domain service**: `src/domain/services/prompt_builder.py` — remove `return text` line (line 133)
