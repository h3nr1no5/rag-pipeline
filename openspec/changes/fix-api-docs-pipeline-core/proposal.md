## Why

The API documentation RAG pipeline (COM interface DOCX/PDF ingestion and querying) has three critical defects that cause queries to fail finding relevant chunks and produce poor answer quality: (1) chunk content is double-formatted, overwriting rich text with impoverished metadata-only text before embedding, (2) the pipeline has no response verification allowing hallucinated answers to reach the user, and (3) no cross-encoder reranking exists between RRF fusion and answer generation. These defects directly impact all users of the API docs query endpoint.

## What Changes

- **Fix double `format_graph()`** — Remove the redundant `format_graph()` call in `ApiEmbeddingIndex.add_graph()` or pass domain objects through it, so embeddings are computed on full formatted text (with parameter names, return types, method/property listings) instead of metadata-only fallback text
- **Add response verification** — Wire the existing `ResponseVerifier` into the API docs `_generate_answer()` flow so hallucinated or unsupported sentences are filtered before the user sees them; fall back to "I don't have enough information" when all sentences fail verification
- **Add cross-encoder reranking** — Insert a cross-encoder reranking step between RRF fusion and link traversal in the `HybridRetriever.retrieve()` pipeline, reusing the existing `CrossEncoderReRanker` from the general pipeline
- **Fix `LinkTraverser` shared mutable state** — Change `_interface_name_to_id` from instance state to a local variable in `traverse()` to eliminate race conditions on concurrent queries against the same document
- **Fix error masking** — Return proper HTTP 500 errors from the query endpoint when LLM generation fails, instead of a 200 response with a misleading error message string

## Capabilities

### New Capabilities
- `api-docs-response-verification`: Post-generation claim verification against source chunks for the API docs query pipeline, reusing the shared `ResponseVerifier` module
- `api-docs-cross-encoder-reranking`: Cross-encoder reranking of hybrid retrieval results in the API docs `HybridRetriever`, improving relevance before source expansion

### Modified Capabilities
- *(No existing specs require requirement-level changes — the modifications are implementation-level fixes to existing code that has no spec coverage yet)*

## Impact

**Affected files:**
- `src/domain/rag/api_docs/retrieval/embedding_index.py` — Fix double-formatted content for embedding
- `src/domain/rag/api_docs/retrieval/hybrid_retriever.py` — Add cross-encoder reranking step
- `src/domain/rag/api_docs/retrieval/link_traverser.py` — Fix shared mutable state race
- `src/domain/rag/api_docs/manager.py` — Add response verification in `_generate_answer()`, fix error masking
- `src/domain/rag/api_docs/routes.py` — Fix error response for LLM failures

**New dependencies:** None — reuses existing `CrossEncoderReRanker` and `ResponseVerifier`

**API surface:** No breaking changes. The query endpoint response schema remains identical.
