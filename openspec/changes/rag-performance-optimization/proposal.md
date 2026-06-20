## Why

Document processing and chat responses are unacceptably slow. Three root causes:

1. **Document processing commits to SQLite once per chunk** — with 100+ chunks, each `await session.commit()` triggers a disk write, adding 5–15 seconds to processing.
2. **Chat retrieval re-embeds ALL chunks from scratch** — `retrieve_chunks()` reads chunk *text* and runs `embedder.embed_texts()` on every query, even though `Chunk.embedding` already stores the pre-computed vector. This is the single biggest query-time bottleneck (5–10s per query).
3. **All 3 RAG backends fire on every chat message** — Cosine Similarity, LangChain, and LlamaIndex all run sequentially per user message (3× latency).

## What Changes

1. **Document processing performance** — Batch DB commits (every 50 chunks), batch embeddings via `embed_texts()`, reuse single DB session.
2. **Chat retrieval optimization** — Use pre-stored `Chunk.embedding` vectors + cosine similarity against query embedding instead of re-embedding all chunk texts.
3. **Default to only Cosine Similarity in chat UI** — Set Cosine Similarity as the only checked default. LangChain and LlamaIndex remain available via sidebar opt-in.

## Non-goals

- Removing LangChain or LlamaIndex code/endpoints — they stay for comparison/experimentation.
- Changing the embedding model or LLM.
- Adding a new RAG backend.

## Impact

| File | Change |
|------|--------|
| `src/domain/services/processor.py` | Batch DB commits, batch embeddings, single session reuse |
| `src/api/routes/query/_retrieval.py` | Use stored embeddings instead of re-embedding all chunk texts |
| `client/pages/3_💬_Chat.py` | Change defaults: cosine=true, langchain=false, llamaindex=false |
