## Context

The LangChain hybrid retriever (`LangChainRetriever` in `retrieval_langchain.py`) creates a FAISS vector store via `FAISS.from_embeddings()` during initialization, passing a `_ProjectEmbeddingFunction` instance as the `embedding_function` parameter. This adapter was introduced in the `fix-faiss-embedding-mismatch` change to route query embeddings through the project's SentenceTransformer model (matching the vector space of stored embeddings).

The adapter class has an `embed_query()` method but does NOT inherit from LangChain's `Embeddings` abstract base class (`langchain_core.embeddings.Embeddings`). LangChain >=0.3 validates the `embedding_function` parameter during `FAISS.similarity_search_with_relevance_scores()` and raises an Exception if it doesn't conform to the `Embeddings` interface. This causes `retrieve()` to catch the exception in its outer `try/except` and return an empty result list.

The cosine and LlamaIndex backends are unaffected — only the LangChain path has this issue.

## Goals / Non-Goals

**Goals:**
- Make `_ProjectEmbeddingFunction` conform to LangChain's `Embeddings` abstract interface
- Restore LangChain FAISS querying so `POST /api/v1/query/langchain` returns results
- Zero changes to the HTTP API, route handlers, or frontend

**Non-Goals:**
- Replacing `_ProjectEmbeddingFunction` with the project's `SentenceTransformerEmbedder` singleton (larger refactor, out of scope)
- Changing how FAISS indexes are built or queried
- Fixing the event-loop blocking issue in `_ProjectEmbeddingFunction.embed_query()` (pre-existing)

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Inheritance vs composition | Inherit from `Embeddings` | LangChain expects `isinstance(embedding_function, Embeddings)` to pass. Composition would require a wrapper class anyway — inheritance is the simplest path. |
| `embed_documents()` implementation | Raise `NotImplementedError` | `FAISS.from_embeddings()` receives pre-computed embeddings from the database and never calls `embed_documents()`. A stub that fails fast is cleaner than returning silent garbage. |
| Fix scope | Minimal — one class, two lines | The bug is a missing base class. Adding it is the smallest possible change. Larger refactors (unifying embedders, async-safe model loading) should be separate changes. |

## Risks / Trade-offs

- **[Low] `_ProjectEmbeddingFunction` still creates a separate `SentenceTransformer` instance**: It doesn't share the project's singleton embedder. If memory is constrained, a second model instance could cause OOM. Mitigation: The embedding model (`all-mpnet-base-v2`) is ~400MB, and two instances fit within the current resource profile.
- **[Low] `embed_documents()` raises at runtime if ever called**: Any code path that calls `embed_documents()` instead of using pre-computed embeddings will fail. Mitigation: `FAISS.from_embeddings()` never calls `embed_documents()` (all docs are pre-embedded). This is a defensive stub, not a risk in practice.
- **[Low] LangChain API evolution**: Future LangChain versions could change the `Embeddings` interface again. Mitigation: `Embeddings` is a stable abstract base in `langchain_core` — the interface has been consistent since langchain 0.1.
