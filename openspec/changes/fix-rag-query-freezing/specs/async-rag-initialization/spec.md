## ADDED Requirements

### Requirement: FAISS initialization SHALL NOT block the async event loop

The `LangChainRetriever.initialize()` method SHALL build the FAISS vector store index in a thread pool rather than directly on the asyncio event loop. The system SHALL use `asyncio.to_thread()` to dispatch `FAISS.from_embeddings()` calls for both the normal path (with real embeddings) and the fallback path (with zero embeddings).

#### Scenario: Successful FAISS initialization with embeddings
- **WHEN** `LangChainRetriever.initialize()` is called with valid `chunks` and `chunk_embeddings`
- **AND** the embedding model is available (non-None)
- **THEN** `FAISS.from_embeddings()` SHALL be dispatched via `asyncio.to_thread()` with pre-computed text_embeddings and metadatas
- **AND** the event loop SHALL remain responsive during index building

#### Scenario: FAISS fallback with zero embeddings
- **WHEN** `LangChainRetriever.initialize()` is called with valid chunks
- **AND** the embedding model is NOT available
- **THEN** `FAISS.from_embeddings()` SHALL be dispatched via `asyncio.to_thread()` with zero-vector embeddings
- **AND** the fallback SHALL NOT block the event loop

#### Scenario: FAISS initialization failure
- **WHEN** `FAISS.from_embeddings()` raises an exception inside the thread pool
- **THEN** the exception SHALL be caught in the `except` block wrapping the call
- **AND** `self._faiss_vectorstore` SHALL be set to `None`
- **AND** the retriever SHALL fall back to BM25-only search

### Requirement: RAG query dispatch SHALL be concurrent

The Streamlit frontend SHALL dispatch queries to all enabled RAG backends concurrently, not sequentially. When all 3 RAG backends are enabled, the total user wait time SHALL be bounded by the slowest single backend, not the sum of all three.

#### Scenario: All 3 RAG backends enabled
- **WHEN** a user sends a chat message with all 3 RAG backends checked (cosine, langchain, llamaindex)
- **THEN** the frontend SHALL dispatch all 3 HTTP requests concurrently
- **AND** the total wait time SHALL be approximately the maximum of the 3 individual response times, not the sum

#### Scenario: Single RAG backend enabled
- **WHEN** a user sends a chat message with only 1 RAG backend checked
- **THEN** the frontend SHALL dispatch only that single request
- **AND** behavior SHALL be identical to the pre-change sequential dispatch for that single backend
