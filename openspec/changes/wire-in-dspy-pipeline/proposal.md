## Why

The DSPy pipeline (`APIDocRAG` module with `QueryAnalyzer`, `ContextAssembler`, `APIResponseGenerator`) was built in the initial API doc RAG effort but **never wired into the live query flow**. The `manager.py` `query()` method calls `_generate_answer()` which uses a simple hardcoded prompt template instead of the DSPy module. This means all the investment in DSPy signatures, ChainOfThought reasoning, citation assertions, and structured output extraction is sitting idle — the actual user experience is indistinguishable from a raw-prompt baseline.

Wiring the DSPy module into the query path unlocks:
- **Structured query analysis** — decomposing questions into search queries, target types, and intent before retrieval
- **Context assembly** — LLM-guided selection and ordering of relevant chunks (vs. naive top-k concatenation)
- **Citation-backed answers** — generated with inline `[FunctionName]` citations, validated by assertions
- **Retry with fallback** — if ChainOfThought output fails assertions, retry with plain Predict
- **Future optimization** — the pipeline becomes compilation-ready (MIPROv2, BootstrapFewShot) once wired

## What Changes

- **Manager integration**: `ApiDocPipelineManager.query()` calls `APIDocRAG.forward()` as the primary generation path, with the current prompt-based generation as a true fallback
- **Routing update**: The `query_api_docs` route constructs and passes the `HybridRetriever` to the DSPy module
- **Configuration toggle**: An `api_docs_dspy_enabled` setting (default `true`) allows operators to fall back to prompt-based generation if needed, without code changes
- **Two code paths unified**: The current `_generate_answer()` stays as a fallback with reduced responsibilities
- **No new dependencies** — DSPy v3.2.1 already installed

## Capabilities

### New Capabilities
- *(None — no entirely new capability introduced)*

### Modified Capabilities
- `dspy-pipeline`: Add integration requirement — the APIDocRAG module MUST be callable from `ApiDocPipelineManager.query()` and produce the `ApiDocQueryResponse` format. The module's `forward()` output mapping becomes part of the spec.
- `api-retrieval`: Update interface — the `HybridRetriever` instance MUST be obtainable by the DSPy pipeline (currently it's only consumed by the manager's `_generate_answer`). The spec gains a requirement that the retriever can be passed to `APIDocRAG.__init__()`.

## Impact

- **Modified files**: `src/domain/rag/api_docs/manager.py` — replace `_generate_answer()` call with DSPy pipeline call
- **Modified files**: `src/domain/rag/api_docs/routes.py` — no changes (routes already call `manager.query()`)
- **Modified files**: `src/core/config.py` — add `api_docs_dspy_enabled` setting (default `true`)
- **No changes** to `src/api/main.py` (DSPy LM already configured at startup)
- **No changes** to existing 3 RAG backends, database schema, or frontend
- **Regression risk**: low — DSPy circuit-breaks to fallback on failure; the current prompt remains as a backup
