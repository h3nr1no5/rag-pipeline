## Why

The existing three RAG backends (cosine, LangChain, LlamaIndex) are optimized for general prose retrieval but struggle with structured API documentation — specifically FEA COM API docs from DOCX sources with table-formatted functions, parameters, types, and cross-references. Query accuracy suffers because table structure is lost during PDF extraction, keyword precision is missing for exact function/type names, and cross-references between interfaces are not systematically followed.

Building a dedicated API-doc-optimized pipeline with DSPy unlocks structured understanding of COM interfaces, parent-child chunking for hierarchical types, and future compilation from labeled Q/A pairs — none of which the current backends can provide without deep rework.

## What Changes

- **New `api-doc-rag` module** at `src/domain/rag/api_docs/` — a self-contained pipeline built alongside the existing 3 backends (zero risk to production)
- **DOCX-first extraction** — parse table-formatted API documentation directly from DOCX files using `python-docx`, preserving function→parameter→type relationships losslessly. PDF fallback for non-DOCX sources.
- **Structured domain model** — typed classes for COM interfaces, methods, properties, parameters, enums, and error codes (replacing current flat `DocumentElement` for API content)
- **Parent-child chunking** — chunks at interface, method, and parameter granularity with explicit parent→child→leaf relationships for multi-level retrieval
- **Hybrid retriever** — BM25 (exact function/type name matching) + embedding similarity (semantic description matching) + link traversal (cross-reference following)
- **DSPy generation pipeline** — replaces the current `build_prompt()` with DSPy signatures (`QueryAnalyzer`, `ContextAssembler`, `APIChainOfThought`) for structured, citation-backed answers
- **Custom DSPy LM adapter** — wraps existing `MLXLLM` singleton as `dspy.BaseLM` subclass (no additional AI subscription needed)
- **Evaluation framework** — metrics for retrieval precision, citation accuracy, and answer completeness (foundation for future MIPROv2 compilation)
- **New API route** — `/api/v1/query/api-docs` for the new pipeline
- **DSPy dependency** added to `pyproject.toml`

## Capabilities

### New Capabilities
- `docx-extraction`: Parse DOCX tables and paragraphs into structured COM API domain objects (interfaces, methods, parameters, enums, error codes)
- `api-chunking`: Build parent-child chunk graph from structured API models, with multi-granularity retrieval support
- `api-retrieval`: Hybrid BM25 + embedding + link-traversal retriever optimized for API documentation queries
- `dspy-pipeline`: DSPy module with signatures for query analysis, context assembly, and structured answer generation with citations
- `dspy-lm-adapter`: Custom `dspy.BaseLM` wrapper around the existing MLXLLM singleton

### Modified Capabilities
- *(None — the new pipeline runs alongside existing backends)*

## Impact

- **New dependency**: `dspy>=2.6` added to pyproject.toml (MIT license, no cost)
- **New dependency**: `python-docx` for DOCX parsing (MIT license)
- **New module**: `src/domain/rag/api_docs/` (~800-1200 lines total)
- **New route**: `/api/v1/query/api-docs` in `src/api/routes/`
- **No changes** to existing 3 backends, existing routes, or existing database schema
- **Shared services**: reuses `MLXLLM`, `SentenceTransformerEmbedder`, `CrossEncoderReRanker` singletons
