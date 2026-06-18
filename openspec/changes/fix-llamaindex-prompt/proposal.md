## Why

The LlamaIndex non-streaming endpoint (`POST /api/v1/query/llamaindex`) returns `"I don't have enough information to answer this question."` for queries that the cosine and LangChain backends answer correctly. The root cause is that `LlamaIndexRetriever.generate()` uses an inline prompt format (`Source N:\n{text}`) that doesn't match what `_apply_chat_template()` expects (`[Source N]: {text}`), causing the entire prompt to become a single user message rather than a proper system/user split. This makes the Qwen2.5-1.5B-Instruct model overly cautious.

The streaming path was already fixed to use the shared `build_prompt()`, but the non-streaming path was not.

## What Changes

- **`retrieval_llamaindex.py` — `generate()` method**: Replace the inline prompt with the shared `build_prompt()` from `prompt_builder.py`, matching what the streaming path already does
- **`retrieval_llamaindex.py` — `generate_stream()` method**: Same fix (uses the same inline prompt)
- **`retrieval_llamaindex.py` — `_build_context()` method**: Remove — no longer needed once `generate()` uses `build_prompt()`
- **`retrieval_llamaindex.py` — `retrieve()` and `generate()` alignment**: Ensure both paths use the same `min_relevance_score` filtering
- **Routes (`routes.py`)**: Remove the duplicate inline prompt handling in the non-streaming LlamaIndex route
- **`llamaindex-rewrite/spec.md`**: Update outdated requirement #6 ("LlamaIndex owns its response pipeline") to reflect the current architecture — no longer uses `ResponseSynthesizer`

## Capabilities

### New Capabilities
- `llamaindex-prompt-unification`: Standardize the LlamaIndex backend to use the shared prompt builder, eliminating the divergent inline prompt that causes silent failures

### Modified Capabilities
- `llamaindex-rewrite`: Update the requirement that mandates `ResponseSynthesizer` with its own prompt templates — the Chroma-based architecture was removed and the backend now constructs prompts manually. The spec must reflect that `build_prompt()` is the correct approach.

## Impact

- **File**: `src/domain/services/retrieval_llamaindex.py` — rewrite `generate()` and `generate_stream()` to use `build_prompt()`; remove `_build_context()`
- **File**: `src/api/routes/query/routes.py` — simplify non-streaming LlamaIndex route (no change to streaming route, which already works)
- **File**: `openspec/specs/llamaindex-rewrite/spec.md` — update requirement #6 to remove the outdated `ResponseSynthesizer` mandate
- **No API contract changes**: All three backends continue to return the same response format
- **No new dependencies**: `build_prompt()` is already used by cosine and LangChain backends
