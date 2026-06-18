## Why

The three RAG pipelines produce inconsistent response formatting. LlamaIndex streaming passes raw LLM tokens directly to the client, including leaked `[Page N]` artifacts from chunk content. The `include_citations` flag is inconsistently respected: the prompt always asks for `[Source N]` citations, and `clean_response` only strips them based on the flag, but streaming bypasses this entirely for LlamaIndex. The result is that users see inline page numbers and citations that should either be controlled by the flag or stripped entirely.

## What Changes

- **Always strip `[Page N]`** from LLM output — these are content artifacts, not intentional citations. Page information lives in structured `sources` metadata.
- **Respect `include_citations` flag in the prompt** — only ask the LLM to use `[Source N]` citations when `include_citations=True`.
- **Respect `include_citations` flag in `clean_response`** — strip `[Source N]` markers only when `include_citations=False`.
- **Fix all three streaming endpoints** to buffer the full response, clean it, then stream — eliminating the double-stream bug (cosine) and the missing re-stream bug (LlamaIndex).
- **Fix client-side display** to also respect `include_citations` for display formatting.
- **Keep the `include_citations` API parameter** unchanged.

## Capabilities

### New Capabilities
- `response-formatting`: Controls how LLM responses are cleaned and formatted before delivery — prompt instruction assembly, `[Page N]` stripping, `[Source N]` citation control, and deduplication pipeline for streaming.

### Modified Capabilities
None — this is net-new behavior, not changing existing spec requirements.

## Impact

- **`src/domain/services/prompt_builder.py`** — `build_prompt()`: conditionally include citation instruction; optionally strip `[Page N]` from context. `clean_response()`: always strip `[Page N]`; conditionally strip `[Source N]`.
- **`src/api/routes/query/routes.py`** — All three streaming endpoints (`/stream`, `/langchain/stream`, `/llamaindex/stream`): buffer then stream cleaned text.
- **`src/domain/services/chain_langchain.py`** — `generate_stream()`: already buffers and cleans (no change needed).
- **`client/utils/query.py`** — Client helpers: no functional change (they just accumulate tokens).
- **`client/components/chat_message.py`** — `strip_markdown_formatting()`: add conditional `[Source N]` stripping based on `include_citations`.
- **`src/api/schemas/query.py`** — No schema changes. `include_citations` parameter already exists.
