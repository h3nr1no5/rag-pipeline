## Why

Every RAG chat response has all Markdown formatting stripped — headings, bold, lists, and paragraph breaks are destroyed. The root cause is the streaming endpoint splitting the answer into individual words (`answer.split()`), which collapses all whitespace structure. Streaming provides zero UX benefit since the frontend already waits for the full response before displaying it.

## What Changes

- **BREAKING**: The Chat page (`client/pages/3_💬_Chat.py`) stops calling streaming endpoints and switches to sync (buffered) endpoints
- Streaming endpoints remain available for API consumers but are no longer used by the primary chat UI
- Sync endpoints return the full response as-is, preserving all Markdown formatting and structure
- The `st.spinner()` pattern already in use provides the waiting indicator — no new UX component needed
- The `_strip_display_text()` function (which also strips Markdown) is confirmed unused by the chat page and will be removed

## Capabilities

### New Capabilities

*(none — this is a migration of existing capability, not a new one)*

### Modified Capabilities

- **response-formatting**: The "streaming endpoints buffer then stream cleaned text" requirement is relaxed — the primary frontend no longer uses streaming, so the `answer.split()` streaming path no longer affects user-facing output. The line-deduplication in `clean_response()` (already confirmed as non-culprit by testing) is also preserved as-is.

## Impact

| File | Change |
|------|--------|
| `client/pages/3_💬_Chat.py` | Replace `stream_query_with_placeholder()` calls with `query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()` |
| `client/utils/query.py` | Remove unused `stream_query()`, `stream_query_with_placeholder()`, `stream_query_langchain()`, `stream_query_langchain_with_placeholder()`, `stream_query_llamaindex()`, `stream_query_llamaindex_with_placeholder()`, and `_strip_display_text()` |
| `openspec/specs/response-formatting/spec.md` | Add delta spec clarifying the frontend no longer depends on streaming formatting |
| `client/components/chat_message.py` | Verify `strip_markdown_formatting()` is already correct (it only strips `[Page N]` / `[Source N]`, not Markdown — confirmed) |
