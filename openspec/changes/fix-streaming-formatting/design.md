## Context

The Chat page (`client/pages/3_💬_Chat.py`) calls streaming endpoints (`/api/v1/query/stream`, `/langchain/stream`, `/llamaindex/stream`) but does not display tokens incrementally — it collects all SSE word-tokens via `stream_query_with_placeholder()` and only renders once the full response arrives.

The streaming endpoints internally do `answer.split()` (Python's default whitespace split), which collapses all newlines, tabs, and spacing. This destroys the Markdown structure (headings, lists, paragraphs) that the LLM is instructed to generate. The same response via the sync endpoints returns the text with all formatting intact.

The sync endpoints already exist, produce identical answers (same retrieval, same LLM, same `clean_response()`), and the frontend already uses `st.spinner()` for the waiting state — the only missing piece is the function call.

## Goals / Non-Goals

**Goals:**
- Preserve Markdown formatting (headings, bold, lists, paragraphs) in all chat responses
- Replace streaming endpoint calls with sync endpoint calls in the Chat page
- The `st.spinner()` pattern continues to serve as the "response is being produced" indicator
- Remove unused streaming client functions to reduce code surface

**Non-Goals:**
- Removing or modifying the backend streaming endpoints (keep for any API consumers that rely on SSE)
- Changing the `clean_response()` function (already confirmed as not the cause)
- Changing the `strip_markdown_formatting()` client function (already correct)
- Changing the message replay/display for historical messages (already correct)

## Decisions

### Decision 1: Use sync endpoints instead of fixing streaming

| Option | Rationale |
|--------|-----------|
| **✅ Fix streaming `answer.split()`** | Could use `re.split(r'(\s+)', answer)` to preserve whitespace. But the streaming provides zero UX value (no incremental display). More complex, more surface area. |
| **Switch to sync endpoints** | Simpler. The sync path returns the exact same data without the destructive `split()`. Removes SSE parsing code. The spinner already handles the waiting UX. |

**Chosen:** Sync endpoints. Less code, same UX, fixes the bug.

### Decision 2: Add `include_citations` to sync client helpers

The streaming helpers pass `include_citations` to the API, but the sync helpers `query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()` lack this parameter. The backend already supports it — the frontend just needs to forward it.

### Decision 3: Remove unused streaming functions

The following are confirmed unused by the Chat page and will be removed:
- `_strip_display_text()` (only used by `stream_query()` which is itself unused)
- `stream_query()` (the simple version, not used by Chat page)
- `stream_query_with_placeholder()` (replaced by `query_sync()`)
- `stream_query_langchain()` / `stream_query_langchain_with_placeholder()` (replaced by `query_langchain_sync()`)
- `stream_query_llamaindex()` / `stream_query_llamaindex_with_placeholder()` (replaced by `query_llamaindex_sync()`)

## Risks / Trade-offs

- **[Risk] Sync timeout on slow LLM**: The sync request has a 180s timeout, same as streaming. The `st.spinner()` shows "Cosine Similarity..." / "LangChain..." / "LlamaIndex..." during the wait. If one backend is slow, it blocks subsequent backends from rendering. **Mitigation:** The existing spinner blocks are sequential anyway (same pattern as current code). Can be mitigated later with concurrent requests if needed.
- **[Risk] Error handling**: Streaming handles errors inline via SSE events. Sync returns HTTP errors as JSON. The `query_sync()` helpers already convert errors to `{"answer": "Error: ...", ...}`. The rendering code already handles this.
- **[Trade-off] No per-word reveal**: The streaming architecture was intended for incremental reveal but was never wired to display incrementally. Switching to sync removes this capability entirely, but since it was never implemented on the frontend, there's no regression.
