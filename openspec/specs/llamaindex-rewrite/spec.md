## Purpose

Rewrite the LlamaIndex RAG backend to use actual LlamaIndex libraries (`llama-index-core`) with SQLite-backed hybrid retrieval, cross-encoder reranking, and direct MLX LLM response generation.

## Requirements

### Requirement: LlamaIndex backend shall use actual LlamaIndex libraries
The LlamaIndex RAG backend SHALL use `llama-index-core` instead of the current custom implementation. The existing route (`POST /api/v1/query/llamaindex`) SHALL be replaced with the new implementation.

#### Scenario: Dependencies are available
- **WHEN** the application starts
- **THEN** `llama-index-core` SHALL be importable

#### Scenario: Route returns same API contract
- **WHEN** a client sends a query to `POST /api/v1/query/llamaindex`
- **THEN** the response SHALL contain `answer` (string), `sources` (array of `SourceChunk`), `cached` (boolean), and `latency_ms` (number)



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

### Requirement: LlamaIndex uses shared prompt builder

The LlamaIndex backend SHALL construct its response prompt using the shared `build_prompt()` from `prompt_builder.py` instead of LlamaIndex's `ResponseSynthesizer`. The backend SHALL use the shared `get_llm()` singleton (from `llm.py`) for response generation.

#### Scenario: Response synthesis uses shared prompt builder

- **WHEN** `LlamaIndexRetriever.generate()` is called
- **THEN** the backend SHALL use `build_prompt()` from `prompt_builder.py` for prompt construction
- **AND** route response generation through the shared `get_llm()` singleton

#### Scenario: Custom prompt template produces compatible answers

- **WHEN** the LlamaIndex backend generates a response
- **THEN** the output SHALL be plain text (no markdown formatting) matching the format of other backends
