## Context

The Chat page (`client/pages/3_💬_Chat.py`) has a sidebar with checkboxes for selecting RAG backends. Three main backends (Cosine Similarity, LangChain, LlamaIndex) are always shown unconditionally. A fourth "API Docs" backend is conditionally shown when a selected document has `engine_type == "api-docs"`.

Two bugs exist:
1. **API Docs checkbox never appears**: `ChunkingStrategyResponse` schema is missing `engine_type`, so the frontend cannot detect api-docs documents.
2. **Main RAG backends always active**: They appear even when only api-docs documents are selected, but api-docs documents skip the regular chunking/embedding pipeline — queries against them return nothing.

The backend routes are:
- Cosine: `POST /api/v1/query` (and `/stream`)
- LangChain: `POST /api/v1/query/langchain` (and `/stream`)
- LlamaIndex: `POST /api/v1/query/llamaindex` (and `/stream`)
- API Docs: `POST /api/v1/query/api-docs`

## Goals / Non-Goals

**Goals:**
- API Docs checkbox appears in the sidebar when any selected document has `engine_type == "api-docs"`
- When only api-docs documents are selected, the three main RAG checkboxes are disabled with a tooltip explaining why
- When both api-docs and regular documents are selected, all four backends remain available
- Non-disabled behavior (for regular documents) is unchanged

**Non-Goals:**
- No changes to the backend query routes or their logic
- No new API endpoints or database schema changes
- No changes to the document upload or processing flow

## Decisions

### Decision 1: Add `engine_type` to `ChunkingStrategyResponse`

**Chosen:** Add `engine_type: str` field to the Pydantic model.

The `ChunkingStrategy` database model already has `engine_type` (string column, default `"recursive"`), and the response model already uses `from_attributes=True`. This is a pure serialization fix — the value exists in the database but was never exposed.

**Alternatives considered:**
- Check `processing_config.engine_type` instead: That model already has `engine_type`, but the frontend reads `doc.chunking_strategy` (the strategy relationship), not `doc.processing_config`. Changing the frontend to read a different field would be more fragile than fixing the schema.
- Hardcode a mapping on the frontend: Would require maintaining the mapping in sync with the backend — brittle and unnecessary when the data exists on the backend model.

### Decision 2: Disable (not hide) incompatible backends

**Chosen:** Set `disabled=True` on the three main RAG checkboxes with a tooltip "Not available for API documentation documents" when all selected documents are api-docs type.

Also exclude disabled backends from the `selected_rags` list to prevent query attempts.

**Alternatives considered:**
- Hide the checkboxes entirely: User chose "disable with tooltip" — better UX as it shows users what options exist and why they're unavailable.
- Keep checkboxes enabled but add validation at query time: Worse UX because the error would appear after the user submits a question rather than proactively.

### Decision 3: Mixed selection keeps all backends enabled

**Chosen:** When both api-docs and regular documents are selected, all four backends remain enabled.

This allows users to query regular documents via Cosine/LangChain/LlamaIndex and api-docs documents via the API Docs backend, all in the same session.

## Risks / Trade-offs

- **No risk**: Adding a field to a Pydantic response model with `from_attributes=True` is backward-compatible — existing API consumers that don't read `engine_type` will simply ignore it.
- **No risk**: The checkbox disable logic is purely client-side (Streamlit); if the schema fix is deployed without the frontend change, the API Docs checkbox still won't appear (status quo). If the frontend change is deployed without the schema fix, `all_api_docs` will never be True, so nothing changes. The two changes are independent and safe in any deployment order.
- **Trade-off**: Users who select only api-docs documents and want to use the main RAG backends for some other reason (unlikely, since those backends aren't compatible) lose that option. Acceptable because the backends return no useful results for api-docs docs anyway.
