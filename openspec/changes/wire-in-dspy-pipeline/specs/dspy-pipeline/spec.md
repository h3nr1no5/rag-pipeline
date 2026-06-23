## ADDED Requirements

### Requirement: APIDocRAG callable from ApiDocPipelineManager
The `APIDocRAG` module SHALL be callable from `ApiDocPipelineManager.query()` as the primary answer-generation path. The manager SHALL instantiate `APIDocRAG` per-request with the document's `HybridRetriever` and call `forward()` to produce a structured answer.

The manager SHALL accept a `HybridRetriever` in `APIDocRAG.__init__()` and store it as `self.hybrid_retriever` for use during `forward()`.

#### Scenario: Manager queries via DSPy
- **WHEN** `ApiDocPipelineManager.query()` is called with `api_docs_dspy_enabled=true`
- **THEN** the manager creates an `APIDocRAG` instance with the document's `HybridRetriever`, calls `forward(question=query_text, top_k=top_k)`, and maps the output dict to an `ApiDocQueryResponse`

### Requirement: DSPy output maps to ApiDocQueryResponse
The `APIDocRAG.forward()` output dict SHALL be mapped to `ApiDocQueryResponse` as follows:

| forward() key | ApiDocQueryResponse field |
|---|---|
| `answer` | `.answer` |
| `citations` | `.citations` |
| `relevant_functions` | `.relevant_functions` |
| `relevant_types` | `.relevant_types` |
| `confidence` | `.confidence` |
| `retrieved_chunks` | `.sources` (via lookup in ChunkGraph for content + metadata) |

The `.cached` field SHALL be `false` (caching is not a DSPy responsibility).
The `.latency_ms` SHALL be computed by the manager as wall-clock time of the full `query()` call.
The `.unsupported_sentences` SHALL be populated by running `ResponseVerifier.verify()` on the generated answer.

#### Scenario: Chunk IDs resolved to ApiDocSource
- **WHEN** `retrieved_chunks` contains `("chunk_001", 0.85)`
- **THEN** the manager looks up `chunk_001` in the document's `ChunkGraph`, extracts content and metadata, and builds an `ApiDocSource(chunk_id="chunk_001", content=..., score=0.85, interface_name=..., function_name=...)`

### Requirement: Circuit-breaker fallback to prompt generation
If `APIDocRAG.forward()` raises any exception, the manager SHALL catch it, log a warning, and fall back to the prompt-based `_generate_answer()` path. The user SHALL receive a valid `ApiDocQueryResponse` regardless of which path succeeded. The response MUST NOT indicate which path was used.

#### Scenario: DSPy module throws and fallback succeeds
- **WHEN** `APIDocRAG.forward()` raises an exception (e.g., LM unavailable, assertion crash)
- **THEN** the manager logs a warning with traceback and calls `_generate_answer()` with the retrieved sources. The caller receives a valid `ApiDocQueryResponse`.

#### Scenario: DSPy module throws and fallback also throws
- **WHEN** both `APIDocRAG.forward()` and `_generate_answer()` raise exceptions
- **THEN** the exception propagates to the route handler, which returns HTTP 500

### Requirement: Configuration toggle
The system SHALL support a boolean configuration `api_docs_dspy_enabled` (default `true`) in `src/core/config.py`. When set to `false`, the manager SHALL use the prompt-based `_generate_answer()` path exclusively.

The setting SHALL be readable from the `API_DOCS_DSPY_ENABLED` environment variable and added to `.env.example`.

#### Scenario: Disable DSPy via config
- **WHEN** `api_docs_dspy_enabled=false` is set in the environment
- **THEN** `ApiDocPipelineManager.query()` bypasses `APIDocRAG` entirely and calls `_generate_answer()` directly

### Requirement: Response verification on DSPy output
The generated answer from the DSPy path SHALL be verified by `ResponseVerifier.verify()` against the source chunks, identical to the existing prompt-based path. Unsupported sentences SHALL be recorded in `unsupported_sentences` on the response.

#### Scenario: DSPy answer contains unsupported claim
- **WHEN** the DSPy-generated answer includes a statement not supported by any source chunk
- **THEN** the unsupported sentence is removed from the answer and added to `unsupported_sentences`
