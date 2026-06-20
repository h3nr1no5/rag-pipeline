## Context

The Streamlit chat UI (`client/pages/3_💬_Chat.py`) currently exposes five tunable parameters in its sidebar: temperature, max_tokens, top_k, prompt_sources (sliders), and response_length (dropdown). These are persisted to `data/chat_params.json` via `save_params()` and loaded on page load via `load_saved_params()`.

The backend API (`src/api/schemas/query.py:17`) already defines `include_citations: bool = Field(default=True)`, and all three streaming client functions (`stream_query_with_placeholder`, `stream_query_langchain_with_placeholder`, `stream_query_llamaindex_with_placeholder`) accept `**params` kwargs that pass through to the API request payload.

The gap: `include_citations` is not rendered as a UI control, not included in `save_params()`, and not in the `params` dict. Users who want to disable citations have no way to do so from the UI.

## Goals / Non-Goals

**Goals:**
- Users can toggle `include_citations` on/off via a checkbox in the sidebar Parameters section
- The setting is persisted in `chat_params.json` and restored on page load
- All three RAG backends (cosine, LangChain, LlamaIndex) receive the parameter via the existing streaming functions
- Follow the same widget pattern as existing parameters (session state key `rag_include_citations`)

**Non-Goals:**
- Changing the backend API schema (`include_citations` is already defined)
- Changing the streaming client functions (they already pass through kwargs)
- Changing how citations appear or are stripped (handled by `fix-response-citations` change)
- Adding the parameter to the non-streaming `query_sync` calls (they also pass through kwargs — already work)

## Decisions

### Decision 1: Use a checkbox widget

`include_citations` is a boolean, so a checkbox is the natural widget. It will appear in the Parameters section alongside the existing controls, placed between prompt_sources and response_length for logical grouping (citation control relates to response formatting).

**Session state key:** `rag_include_citations`
**Default value:** `True` (matching the API default)

### Decision 2: Persist via existing `save_params` mechanism

The existing `save_params()` function writes to `data/chat_params.json`. Adding `include_citations` to the dict is a one-line change. Loading is handled automatically by `load_saved_params()` which returns all keys from the JSON file — if the key doesn't exist in a saved file from an older session, `.get("include_citations", True)` provides the default.

### Decision 3: Wire into existing `params` dict

The `params` dict at line 340-346 already collects all sidebar parameter values and passes them as `**kwargs` to the streaming functions. Adding `include_citations` to this dict is a one-line change. No changes needed to the streaming functions or API client code — the parameter flows through automatically.

## Placement

Current sidebar parameter order:

```
⚙️ Parameters
├── 🌡️ Temperature         (slider)
├── 📐 Max Tokens          (slider)
├── 🔢 Top-K               (slider)
├── 📚 Sources in Prompt   (slider)
├── 📏 Response Length     (dropdown)
├── [💾 Save Parameters]
```

After change:

```
⚙️ Parameters
├── 🌡️ Temperature         (slider)
├── 📐 Max Tokens          (slider)
├── 🔢 Top-K               (slider)
├── 📚 Sources in Prompt   (slider)
├── 📏 Response Length     (dropdown)
├── 📝 Show Citations      (checkbox)  ← NEW
├── [💾 Save Parameters]
```

## Risks / Trade-offs

- **[Stale saved files]** → If a user saved params before this change, `chat_params.json` won't have `include_citations`. Mitigation: use `.get("include_citations", True)` default when loading — existing saves work seamlessly.
- **[User expectations]** → Disabling citations changes response format significantly (no `[Source N]` markers). The checkbox label and help text should make this clear.
