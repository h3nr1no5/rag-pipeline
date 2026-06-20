## Why

The `include_citations` parameter exists in the backend API (`QueryRequest`, default `True`) and controls whether `[Source N]` citations appear in responses, but it has no frontend control. Users cannot toggle citations on/off from the chat UI, and the setting is not persisted between sessions. This limits user control over response formatting.

## What Changes

- **Add `include_citations` checkbox** to the sidebar Parameters section in the Streamlit chat UI
- **Persist the setting** in `chat_params.json` alongside temperature, max_tokens, top_k, prompt_sources, and response_length
- **Include the parameter** in the `params` dict passed to all three streaming query functions (cosine, LangChain, LlamaIndex)
- **No backend changes** — the API already accepts `include_citations` with a default of `True`

## Capabilities

### New Capabilities

- `citation-toggle-frontend`: Controls display of the `include_citations` parameter in the Streamlit chat sidebar, including user toggle interaction and session persistence.

### Modified Capabilities

None — purely additive frontend change. No backend spec requirements change.

## Impact

- **`client/pages/3_💬_Chat.py`** — Add checkbox widget in Parameters section; include `include_citations` in `save_params()` and in the `params` dict passed to streaming functions; restore saved value on load
