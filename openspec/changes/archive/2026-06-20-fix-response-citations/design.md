## Context

The RAG pipeline has three query backends — cosine similarity, LangChain (BM25+FAISS hybrid), and LlamaIndex — each with streaming and non-streaming endpoints. All share a common prompt builder (`build_prompt`) and response cleaner (`clean_response`) in `src/domain/services/prompt_builder.py`.

Three interrelated problems exist:

**1. `[Page N]` leaks into responses.** The PDF parser injects `[Page N]\n` at the start of each page's text. These markers persist through chunking and are visible to the LLM in context. The LLM may reproduce them verbatim. While `clean_response` has a regex to strip them (line 159), the LlamaIndex streaming endpoint never re-streams the cleaned output to the client.

**2. `include_citations` is inconsistently respected.** The prompt always asks the LLM to include `[Source N]` citations, regardless of the `include_citations` flag. `clean_response` strips `[Source N]` only when `include_citations=False`, but streaming can bypass this — raw LLM output with `[Source N]` reaches the client before cleaning happens.

**3. Streaming endpoints have different bugs:**
- **Cosine** (`/stream`): Streams raw tokens first, then re-streams cleaned text. Client receives both → duplicated content.
- **LangChain** (`/langchain/stream`): Already buffers, verifies, cleans, then yields. This is the correct pattern.
- **LlamaIndex** (`/llamaindex/stream`): Streams raw tokens, cleans the accumulated text for caching, but **never re-streams the cleaned version**. Client receives only the raw text with artifacts.

## Goals / Non-Goals

**Goals:**
- LLM responses never contain `[Page N]` inline text
- `[Source N]` citations appear in responses **iff** `include_citations=True` was requested
- All three streaming endpoints produce identical response formatting for the same input
- The `include_citations` API parameter is preserved and fully functional
- Zero behavioral change when `include_citations=True` (citations should still appear)

**Non-Goals:**
- Changing the chunk storage format (`[Page N]` stays in chunk content in the DB)
- Changing the API schema or response model
- Adding new API parameters
- Removing the `include_citations` parameter (it works, just wasn't fully wired)
- Modifying the non-streaming endpoints (they already call `clean_response` correctly)

## Decisions

### Decision 1: Strip `[Page N]` from context before prompting the LLM

Rather than relying solely on `clean_response` to strip `[Page N]` from output, strip it from the context text that the LLM sees in `build_prompt`. This prevents the LLM from ever reproducing it.

**Rationale:** Defense in depth. The `[Page N]` marker is not meaningful to the LLM — it's a parser artifact. Removing it from context eliminates the root cause. `clean_response` remains as a safety net.

**Alternative considered:** Keep `[Page N]` in context and only strip in `clean_response`. Rejected because this relies on the regex catching all possible formatting variations (the LLM might format it as `[page 3]`, `Page 3:`, `(page 3)`, etc.).

### Decision 2: Conditionally include citation instruction in prompt

The prompt system message currently always includes: *"CRITICAL — For EVERY factual statement you make, you MUST include a source citation in brackets like [Source 1]..."*

Change: Include this instruction only when `include_citations=True`. When `False`, omit it entirely.

**Rationale:** The LLM follows instructions. If we tell it to cite, it will. If we don't, it won't (reducing token usage and avoiding hallucinated citation markers). This is more reliable than generating citations and stripping them post-hoc.

### Decision 3: Buffer, clean, then stream — all three pipelines

Replace the current streaming strategy where raw tokens are streamed first and cleaned text is optionally re-streamed after. Instead, all three streaming endpoints will:
1. Buffer the full LLM response (accumulate tokens)
2. Apply `clean_response` (strip `[Page N]`, conditionally strip `[Source N]`)
3. Stream the cleaned text to the client

**Rationale:** This eliminates the cosine double-stream bug and the LlamaIndex missing re-stream bug with a single uniform pattern. The LangChain path already works this way.

**Trade-off:** No "real-time" token-by-token display during generation. The user waits for the full generation before seeing any text. This is acceptable because:
- The local LLM is fast (1.5B param model, ~500MB)
- Generation for typical responses takes 2-5 seconds
- The current "stream raw then cleaned" pattern is broken (duplicated content in cosine)
- The alternative (streaming raw with post-hoc cleaning) is complex and error-prone

**Alternative considered:** Stream raw tokens to a WebSocket for real-time preview while the backend prepares the cleaned version. Rejected as over-engineered for a local-first RAG tool.

### Decision 4: `clean_response` always strips `[Page N]`, conditionally strips `[Source N]`

Current behavior: `[Page N]` stripped unconditionally (line 159). `[Source N]` stripped only when `include_citations=False` (line 172-173).

Change: Keep both behaviors. The `include_citations` flag already controls `[Source N]` stripping in the non-streaming path — we're just ensuring the streaming path also respects it by buffering before cleaning.

**Rationale:** No functional change to `clean_response` itself. The fix is in the streaming data flow (Decision 3).

### Decision 5: Client-side `strip_markdown_formatting` also respects `include_citations`

The client's `strip_markdown_formatting` function (in `chat_message.py`) strips `[Source N]` markers using a hardcoded regex. Since the server now conditionally includes citations, the client function can also be conditional — but it needs the `include_citations` value at render time.

**Approach:** The server already returns the `include_citations` value in the response for non-streaming endpoints. For streaming, the server includes it in the initial SSE event. The client can use it to control whether to strip `[Source N]` for display.

**Rationale:** Defense in depth. Even if the server fails to strip citations (e.g., a new pipeline is added without proper cleaning), the client can strip them. But with server-side cleaning working correctly, this is a belt-and-suspenders measure.

## Data Flow Diagram

```
┌──────────┐     build_prompt()     ┌─────────────────────────────┐
│  Chunks   │────────────────────────▶│  Context text for LLM       │
│ [Page 3]  │                         │  - [Page N] stripped        │
│ content   │                         │  - [Source N] markers added │
└──────────┘                         │  - Citation instruction     │
                                      │    (only if include=True)   │
                                      └────────────┬────────────────┘
                                                   │
                                                   ▼
                                      ┌─────────────────────────────┐
                                      │      LLM generates          │
                                      │   (full response buffered)  │
                                      └────────────┬────────────────┘
                                                   │
                                                   ▼
                                      ┌─────────────────────────────┐
                                      │     clean_response()         │
                                      │  - Always strip [Page N]    │
                                      │  - Strip [Source N] if      │
                                      │    include_citations=False  │
                                      │  - Dedup, truncate, etc.   │
                                      └────────────┬────────────────┘
                                                   │
                                                   ▼
                                      ┌─────────────────────────────┐
                                      │  Stream cleaned text to     │
                                      │  client via SSE             │
                                      │  (all 3 pipelines uniform)  │
                                      └────────────┬────────────────┘
                                                   │
                                                   ▼
                                      ┌─────────────────────────────┐
                                      │  Client display             │
                                      │  strip_markdown_formatting  │
                                      │  - Strip [Source N] if not  │
                                      │    include_citations=False  │
                                      └─────────────────────────────┘
```

## Risks / Trade-offs

- **[No real-time streaming]** → Users see a spinner during generation instead of streaming tokens. For short responses with a local 1.5B model, this adds 2-5s of perceived latency. Acceptable for correctness.
- **[Prompt change may affect LLM behavior]** → Removing the citation instruction might cause the LLM to produce different response styles (e.g., more verbose, less precise). Mitigation: test with a representative set of queries before/after.
- **[Client-side `strip_markdown_formatting` needs `include_citations` context]** → The streaming SSE protocol doesn't currently carry the `include_citations` flag in events. Mitigation: add it to the initial SSE event (alongside `sources`), or accept that the client-side strip is unconditional (belt: already strips `[Source N]`).
- **[Edge case: LLM hallucinates [Source N] even without instruction]** → `clean_response` handles this by stripping when `include_citations=False`. The server always cleans.
- **[Edge case: LLM outputs [Page N] in unexpected format]** → The regex handles `[Page N]`, `[Page N]:`, and surrounding whitespace. If the LLM produces `Page 3:` (no brackets), a follow-up fix may be needed.
