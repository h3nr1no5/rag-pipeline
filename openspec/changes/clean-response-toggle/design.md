## Context

The `clean_response()` function in `src/domain/services/prompt_builder.py` is a multi-stage post-processing pipeline applied to all LLM responses:

1. Strip special tokens (`<|endoftext|>`, `[INST]`, etc.)
2. Strip chat template markers (`Human:`, `Assistant:`)
3. Strip leaked phrases (`"You Can Ask"`, `"Test Questions"`)
4. Strip tokenization artifacts (`: rgan:`)
5. Strip `[Page N]` / `[Section N]` (always)
6. Strip/keep `[Source N]` (conditional on `include_citations`)
7. Deduplicate near-duplicate lines
8. Remove repeated text (3+ consecutive copies)
9. Truncate by response_length (concise/normal/detailed)

**Current state**: A `return text` on line 133 disables the entire function, making it a no-op. This was added locally because stage 7 (dedup) was too aggressive, removing nuance from responses. The HEAD commit restores the function, but then there's no way to opt out.

**Existing pattern**: `include_citations` already demonstrates the pattern of a boolean toggle on `QueryRequest` → forwarded by client helpers → conditionally used in routes → persisted in `chat_params.json`. This change follows the same pattern.

## Goals / Non-Goals

**Goals:**
- Add a `clean_response` boolean to `QueryRequest` (default `True`)
- When `False`, skip the entire `clean_response()` call — raw LLM output passes through
- Frontend checkbox in the sidebar, saved with other parameters
- Remove the `return text` hack so `clean_response()` works when toggled on
- `[Source N]` behavior remains independently controlled by `include_citations`

**Non-Goals:**
- No granular control inside `clean_response()` — it's all or nothing
- No changes to what `clean_response()` does internally — the existing cleaning pipeline stays as-is
- No changes to client-side `strip_markdown_formatting()` — it still runs as defense-in-depth for `[Page N]` and `[Source N]`
- No new persistence mechanism — reuse the existing `chat_params.json` pattern

## Decisions

### Decision 1: Simple boolean, not granular flags

**Chosen**: Single `clean_response: bool` on `QueryRequest`. When `False`, the function is skipped entirely.

**Alternatives considered**:
- Multiple toggles per stage (e.g., `deduplicate`, `strip_tokens`) — rejected as over-engineering for the current need
- A "minimal safety" mode that strips tokens but skips dedup — rejected by user preference (Option A: completely raw)

**Rationale**: The user's core complaint is that dedup is too aggressive. Rather than making dedup smarter (which could introduce new bugs), a master toggle lets users choose: either get the full pipeline, or get the raw output. The `include_citations` toggle already handles the citation-specific concern independently.

### Decision 2: Condition at the call site, not inside the function

**Chosen**: Gate the call in `routes.py` — not add a parameter to `clean_response()` itself.

```python
# In each route handler:
answer = raw_response
if request.clean_response:
    answer = clean_response(answer, request.response_length, request.include_citations)
```

**Alternatives considered**:
- Add `enabled: bool` parameter to `clean_response()` — rejected because it makes the function aware of its own "should I run" state, which is a caller concern

**Rationale**: The `clean_response()` function stays pure — it always cleans when called. The caller decides whether to call it. This is simpler, doesn't change the function signature, and keeps the toggle logic visible at each call site.

### Decision 3: Reuse existing persistence pattern

**Chosen**: Add `"clean_response"` key to `save_params()` / `load_saved_params()` in `Chat.py`, stored in `data/chat_params.json`.

**Rationale**: Same mechanism already used for temperature, max_tokens, top_k, prompt_sources, include_citations. No new infrastructure needed.

## Data Flow

```
                    QueryRequest.clean_response (default: True)
                              │
                    ┌─────────▼─────────┐
                    │   POST /api/v1    │
                    │   /query          │
                    │                   │
                    │  raw = llm(...)   │
                    │                   │
                    │  if clean_resp:   │
                    │    answer =       │
                    │     clean_resp()  │
                    │  else:           │
                    │    answer = raw   │
                    │                   │
                    └─────────┬─────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
    Cosine route        LangChain route     LlamaIndex route
    (routes.py:143)     (routes.py:314)     (routes.py:872)
    + streaming:251     + streaming:642     + streaming:997

Chat.py sidebar
  ┌─────────────────────────────┐
  │ ☑ Clean Response            │  ← new
  │ ☑ Show Citations            │
  │                             │
  │ [ 💾 Save Parameters ]      │
  └─────────────────────────────┘
        │
        ▼
  save_params({
      "clean_response": True,   ← new
      "include_citations": True,
      "temperature": 0.5,
      ...
  })
        │
        ▼
  client/utils/query.py
  query_sync(question, doc_ids, clean_response=True, ...)
    → POST body: { "clean_response": True, ... }
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Raw output may contain `[Page N]` markers** — When `clean_response=False`, `[Page N]` is not stripped server-side | Client-side `strip_markdown_formatting()` in `chat_message.py` still strips `[Page N]` unconditionally as defense-in-depth |
| **Raw output may contain control tokens** (`<|endoftext|>`, `[INST]`, etc.) — These are not stripped when off | This is the intended behavior (Option A — completely raw). The user accepts this trade-off. Tokens are unlikely with the current prompt template but could appear. |
| **Response_length truncation won't apply** — "concise" and "detailed" modes are inside `clean_response()` | This is expected — when cleaning is off, the LLM's verbosity is determined solely by the prompt instruction for response length, not by post-processing truncation |
| **`return text` must be removed** — Forgetting to remove line 133 means `clean_response()` remains a no-op even when toggled on | Include this as a task item and verify with a test |
| **Default `True` maintains backward compatibility** — Existing behavior is preserved for users who don't touch the setting | Correct — the default in both the schema and the frontend checkbox is `True` |

## Open Questions

None. All decisions are resolved from the exploration conversation.
