## Context

The LlamaIndex non-streaming path has a stale inline prompt that survived the Chroma removal refactoring. During the Chroma era (commit `b99a5f7`), `LlamaIndexRetriever.generate()` used LlamaIndex's `ResponseSynthesizer` which required a `PromptTemplate` with `{context_str}` and `{query_str}` placeholders — making the shared `build_prompt()` from `prompt_builder.py` unusable. When Chroma was removed (commit `c505d74`), `generate()` was rewritten to construct prompts manually but kept the same inline format as the old `PromptTemplate`.

The inline format uses `Source N:\n{text}` (no square brackets, colon-newline separator), while `build_prompt()` uses `[Source N]: {text}` (brackets, colon-space). The `_apply_chat_template()` function in `llm.py` looks for `"\n[Source "` to split system/user messages — it can't find the marker in the inline format, so the entire prompt becomes a single user message. This causes Qwen2.5-1.5B-Instruct to interpret the "I don't have enough information" instruction literally.

The streaming LlamaIndex path was already updated to use `build_prompt()` and `get_llm()` directly (see `routes.py:1048-1055`). The non-streaming path was not.

## Goals / Non-Goals

**Goals:**
- Make the non-streaming LlamaIndex endpoint (`POST /api/v1/query/llamaindex`) return correct answers matching the cosine and LangChain backends
- Eliminate the divergent inline prompt and its associated failures
- Align the non-streaming code path with the already-working streaming code path
- Update the outdated `llamaindex-rewrite` spec to reflect the current architecture

**Non-Goals:**
- Not changing the LlamaIndex streaming endpoint (it already works)
- Not changing the cosine or LangChain backends
- Not altering the public API contract (response format stays identical)
- Not adding new dependencies or third-party libraries
- Not refactoring the `_retrieve_and_rerank` method signature (only `generate()` changes)

## Decisions

### Decision 1: Refactor `generate()` to use `build_prompt()` internally

**Approach:** `generate()` will be restructured to:
1. Retrieve via `self.retrieve()` (which includes `min_relevance_score` filtering) instead of calling `_retrieve_and_rerank()` directly
2. Deduplicate via the shared `deduplicate_chunks()`
3. Build the prompt via the shared `build_prompt()`
4. Generate via the shared `get_llm()` (same as streaming path)
5. Return answer + chunks (matching existing API)

**Why:**
- The streaming path (`routes.py:1048-1055`) already proves this approach works correctly
- `build_prompt()` produces `[Source N]: {text}` format that triggers the proper system/user split in `_apply_chat_template()`
- Eliminates the root cause at the source rather than patching symptoms

**Alternatives considered:**
- *Fix only the chat template*: Making `_apply_chat_template()` also recognize `Source N:\n{text}` without brackets. Rejected because it's fragile — the inline prompt has multiple other issues (no deduplication, no verbosity control, no response_length support).
- *Fix in the route only*: Restructure the route to build the prompt and call the LLM directly (like streaming). This would require changing `generate()` to only return chunks, and moves more logic to the route. Less contained — `generate()` is the right abstraction boundary.

### Decision 2: Add prompt parameters to `generate()` signature

`generate()` will accept `prompt_sources`, `include_citations`, and `response_length` parameters (matching `build_prompt()`'s contract). The route passes these through from the request.

**Why:** `generate()` is a high-level method that produces an answer. The route should not need to know about prompt construction — that's the service layer's job. These parameters are already part of the domain vocabulary (they exist on `QueryRequest`).

### Decision 3: Use `self.retrieve()` instead of `_retrieve_and_rerank()` directly

`generate()` currently calls `_retrieve_and_rerank()` directly, bypassing the `min_relevance_score` filter in `retrieve()`. After the fix, it will call `self.retrieve()` to get pre-filtered, properly scored chunks.

**Why:** Consistency with the streaming path, which uses `retriever.retrieve()`. The `min_relevance_score` filter protects against low-quality context being fed to the LLM.

### Decision 4: Remove `_build_context()` method

Once `generate()` uses `build_prompt()`, the inline `_build_context()` method is dead code. It will be removed.

## Risks / Trade-offs

- **[Risk] Double `clean_response()`**: The route calls `clean_response()` on `generate()`'s output. If `generate()` returns raw LLM output (recommended), no change needed. If `generate()` also cleaned internally, the double-cleaning is idempotent but wasteful.
  → **Mitigation**: `generate()` returns raw LLM output without internal cleaning. The route continues to handle `clean_response()` exclusively.

- **[Risk] `deduplicate_chunks()` double-processing**: Both `generate()` and the route deduplicate. The streaming route already handles this — `deduplicate_chunks()` in `generate()` is purely internal.
  → **Mitigation**: Only call `deduplicate_chunks()` once, in `generate()`. The route receives already-deduplicated chunks.

- **[Risk] Behavior change for empty retrieval**: Currently `generate()` passes all nodes through even with zero `min_relevance_score`. After the fix, `retrieve()` will filter low-score nodes. If all are filtered, the response becomes "I don't have enough information" — which is actually correct behavior, matching the streaming path.
  → **Mitigation**: Add the same empty-retrieval guard used in the streaming route.
