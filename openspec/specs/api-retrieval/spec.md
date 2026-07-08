# API Retrieval

## Purpose

Provide a standalone `HybridRetriever` that is constructable independently of the answer-generation path, enabling reuse across DSPy and fallback retrieval paths without shared mutable state.

## ADDED Requirements

### Requirement: HybridRetriever constructable independently of generation
The `HybridRetriever` SHALL be obtainable as a standalone object from the manager's per-document index store, independent of the answer-generation path. The DSPy `APIDocRAG` module SHALL accept a `HybridRetriever` instance via its constructor and use it for multi-query retrieval inside `forward()`.

The `HybridRetriever` SHALL be fully usable after ingestion completes, without requiring any generation-specific setup.

#### Scenario: DSPy module retrieves via passed retriever
- **WHEN** `APIDocRAG.__init__(hybrid_retriever=retriever)` is called
- **THEN** the module stores the reference and calls `retriever.retrieve(query, top_k=top_k)` during `forward()` for each generated search query

#### Scenario: Retriever reuse across DSPy and fallback paths
- **WHEN** the same document's `HybridRetriever` is used first by `APIDocRAG.forward()` (DSPy path) and then by `_generate_answer()` (fallback path)
- **THEN** the retriever produces consistent results in both paths; no shared mutable state between invocations
