# API Docs Cross-Encoder Reranking

## Purpose

Insert a cross-encoder reranking step between RRF fusion and source expansion (link traversal / parent expansion) in the API docs `HybridRetriever`, so that the most contextually relevant chunks — not just those with the best BM25 + embedding fusion score — reach the answer generation stage.

## ADDED Requirements

### Requirement: Rerank hybrid retrieval results with cross-encoder

The API docs `HybridRetriever.retrieve()` SHALL apply cross-encoder reranking to the top candidates produced by RRF fusion, before link traversal and parent expansion, using the shared `CrossEncoderReRanker` from the general pipeline.

#### Scenario: Reranking applied after RRF fusion
- **WHEN** `HybridRetriever.retrieve()` completes RRF fusion of BM25 and embedding results
- **THEN** the top `rerank_k` candidates (default 20) SHALL be reranked using the cross-encoder model
- **THEN** the cross-encoder SHALL compute a relevance score for each `(query, chunk_text)` pair
- **THEN** chunks SHALL be re-sorted by descending cross-encoder score
- **THEN** link traversal and parent expansion SHALL operate on the reranked results

#### Scenario: Cross-encoder scores replace RRF scores
- **WHEN** a chunk passes through cross-encoder reranking
- **THEN** the chunk's `score` in the retrieval result SHALL be the cross-encoder score (min-max normalized to [0, 1]), replacing the original RRF score
- **THEN** the original RRF score SHALL be preserved in an internal field for debugging

#### Scenario: Relevance threshold applied
- **WHEN** a chunk's cross-encoder score falls below `settings.min_relevance_score` (default 0.15)
- **THEN** that chunk SHALL be discarded and SHALL NOT proceed to link traversal or parent expansion

### Requirement: Reuse shared CrossEncoderReRanker singleton

The API docs pipeline SHALL NOT create its own cross-encoder instance. It SHALL import and use the existing `CrossEncoderReRanker` from `src.domain.services.retrieval_langchain`, which provides a lazy-loaded, thread-safe singleton.

#### Scenario: Singleton reused across backends
- **WHEN** the API docs pipeline performs reranking for the first time
- **THEN** it SHALL use the same `CrossEncoderReRanker.get_instance()` that the LangChain and LlamaIndex backends use
- **THEN** the model SHALL be loaded only once, regardless of which pipeline triggers first
- **THEN** the `CrossEncoderReRanker` SHALL be initialized with the same model (`gte-reranker-modernbert-base`) and device configuration

#### Scenario: Rerank count configurable
- **WHEN** the API docs pipeline initializes the hybrid retriever
- **THEN** it SHALL accept a `rerank_k` parameter (default 20) controlling how many RRF-fused candidates are sent to the cross-encoder
- **THEN** `rerank_k` SHALL be at least as large as `top_k` to have an effect
- **THEN** `rerank_k` SHALL be configurable via the `ApiDocQueryRequest` body
