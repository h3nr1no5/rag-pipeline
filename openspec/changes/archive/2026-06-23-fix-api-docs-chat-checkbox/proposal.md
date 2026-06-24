## Why

The API Docs checkbox does not appear in the Chat page when a user selects a document that was processed with the api-docs engine type. This is because `ChunkingStrategyResponse` is missing the `engine_type` field, so the frontend can never detect api-docs documents. Additionally, the three main RAG backends (Cosine Similarity, LangChain, LlamaIndex) are always shown — even when they are incompatible with api-docs documents (which bypass the regular chunking/embedding pipeline).

## What Changes

- Add `engine_type: str` to `ChunkingStrategyResponse` Pydantic schema so that the API serializes this field from the database model
- In the Chat page sidebar, detect when only api-docs documents are selected and disable the three main RAG backend checkboxes with a tooltip explaining they are not available for API documentation documents
- Ensure the API Docs checkbox itself appears as expected once the schema is fixed

## Capabilities

### New Capabilities

None. This is a bug fix to the existing chat UI and API schema, not a new feature.

### Modified Capabilities

- `chat-interface`: The RAG backend selection behavior is changing — backends incompatible with the selected document type are now disabled with context-aware tooltips

## Impact

- `src/api/schemas/document.py`: Add `engine_type` field to `ChunkingStrategyResponse` (backward-compatible addition)
- `client/pages/3_💬_Chat.py`: Conditional disable logic for the three main RAG checkboxes based on selected document types
- No new dependencies, no breaking API changes, no database migrations required
