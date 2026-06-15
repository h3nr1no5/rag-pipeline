## Purpose

Rewrite the LlamaIndex RAG backend to use actual LlamaIndex libraries (`llama-index-core`, `llama-index-vector-stores-chroma`) with persistent Chroma indexing, hybrid retrieval, cross-encoder reranking, and an MLX LLM adapter.

## Requirements

### Requirement: LlamaIndex backend shall use actual LlamaIndex libraries
The LlamaIndex RAG backend SHALL use `llama-index-core` and `llama-index-vector-stores-chroma` instead of the current custom implementation. The existing route (`POST /api/v1/query/llamaindex`) SHALL be replaced with the new implementation.

#### Scenario: Dependencies are available
- **WHEN** the application starts
- **THEN** `llama-index-core` and `llama-index-vector-stores-chroma` SHALL be importable

#### Scenario: Route returns same API contract
- **WHEN** a client sends a query to `POST /api/v1/query/llamaindex`
- **THEN** the response SHALL contain `answer` (string), `sources` (array of `SourceChunk`), `cached` (boolean), and `latency_ms` (number)

### Requirement: Chroma vector store for index persistence
The LlamaIndex backend SHALL use Chroma as its vector store for persistent indexing across application restarts.

#### Scenario: Index persists across restarts
- **WHEN** the application restarts after documents have been indexed
- **THEN** queries to the LlamaIndex backend SHALL return results from previously indexed documents without requiring re-indexing

#### Scenario: Metadata filtering for document scoping
- **WHEN** a query specifies `document_ids`
- **THEN** the Chroma query SHALL filter results to only those documents using metadata filtering

### Requirement: Index built during document processing
The document processor SHALL build and update the Chroma index when documents are uploaded and chunked.

#### Scenario: Index updated after document upload
- **WHEN** `processor.py` finishes chunking a document
- **THEN** the document's nodes SHALL be indexed into Chroma

#### Scenario: Index updated on document deletion
- **WHEN** a document is deleted
- **THEN** its entries SHALL be removed from Chroma

### Requirement: Hybrid retrieval with cross-encoder reranking
The LlamaIndex backend SHALL perform hybrid retrieval combining embedding similarity and keyword search, followed by cross-encoder reranking.

#### Scenario: Hybrid retrieval returns combined results
- **WHEN** the retriever executes a query
- **THEN** it SHALL return results from both embedding-based and keyword-based retrieval, fused via reciprocal rank fusion

#### Scenario: Cross-encoder reranks candidates
- **WHEN** hybrid retrieval returns candidates
- **THEN** the BGE cross-encoder reranker SHALL re-score the top candidates before returning final results

### Requirement: MLX LLM adapter for LlamaIndex
A thin adapter SHALL wrap the existing `MLXLLM` service as a LlamaIndex-compatible LLM, so the same local MLX-optimized model is used for response synthesis.

#### Scenario: MLX LLM is used for response generation
- **WHEN** the LlamaIndex backend generates a response
- **THEN** it SHALL use the existing `MLXLLM` instance through the adapter

#### Scenario: Adapter supports async and streaming
- **WHEN** the LlamaIndex backend requests a response
- **THEN** the adapter SHALL support both `achat` (async complete) and `stream_chat` (async streaming) interfaces

### Requirement: LlamaIndex owns its response pipeline
The LlamaIndex backend SHALL use LlamaIndex's `ResponseSynthesizer` with its own prompt templates, not the shared `build_prompt`/`clean_response` from `prompt_builder.py`.

#### Scenario: Response synthesis uses LlamaIndex
- **WHEN** generating a response
- **THEN** the LlamaIndex backend SHALL use `ResponseSynthesizer` for response generation

#### Scenario: Custom prompt template produces compatible answers
- **WHEN** the LlamaIndex backend generates a response
- **THEN** the output SHALL be plain text (no markdown formatting) matching the format of other backends
