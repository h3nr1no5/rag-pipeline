## Context

The project currently has 3 RAG backends (cosine similarity, LangChain hybrid, LlamaIndex hybrid) that all share the same `MLXLLM`, `SentenceTransformerEmbedder`, `CrossEncoderReRanker`, and `ResponseVerifier` singletons. All 3 process PDF-extracted text through `build_prompt()` (210 lines of hand-crafted instructions). None are optimized for semi-structured content like API documentation.

The target domain is **FEA (Finite Element Analysis) COM API documentation** for structural engineering software. The docs originate as **DOCX files** with consistent table templates for:
- Method/function tables (columns: Method, Parameters, Return Type, Description)
- Property tables (columns: Name, Type, Access, Description)
- Enum tables (columns: Value, Description)
- Error code tables (columns: Code, Description)
- Conceptual prose sections (headings, paragraphs, bullet lists)

The DOCX is available at ingest time alongside the PDF. Approximately 10-100 interfaces, 200-2000 functions total.

### Constraints
- Must run alongside existing 3 backends without modification
- MLX Qwen2.5-1.5B-4bit is the only LLM (no external AI API budget)
- No pre-existing labeled Q/A pairs for DSPy compilation (deferred)
- Existing `pydantic-settings` config pattern, SQLite+aiosqlite, FastAPI route structure

## Goals / Non-Goals

**Goals:**
- Extract structured COM API data from DOCX tables losslessly (function→parameters→types)
- Build a parent-child chunk graph supporting multi-granularity retrieval
- Implement hybrid retrieval (BM25 exact + embedding semantic + link cross-reference)
- Build a DSPy-powered generation pipeline with signatures, citations, and assertions
- Expose via `/api/v1/query/api-docs` route
- Provide evaluation metrics for future DSPy compilation
- Reuse existing MLXLLM, embedder, and cross-encoder singletons

**Non-Goals:**
- Replacing or modifying the existing 3 RAG backends (they continue working as-is)
- Supporting non-COM API doc formats in v1 (consider v2: REST, gRPC, OpenAPI)
- DSPy compilation / MIPROv2 optimization (requires labeled Q/A pairs — deferred)
- Real-time DOCX processing (ingestion is batch upload, same as current PDF flow)
- UI changes in Streamlit frontend (v1 is API-only; frontend follows)

## Decisions

### Decision 1: DOCX-first extraction with python-docx
**Choice**: Parse DOCX files directly with `python-docx` instead of extracting tables from PDF.
**Rationale**: DOCX preserves table structure (rows, cells, merged cells) perfectly. PDF extraction loses all table relationships — recovery from `bbox` coordinates is fragile and error-prone for multi-row function entries (one function with N parameters spanning N rows).
**Alternatives considered**:
- PDF-only (current approach) — loses structure, requires fragile heuristic recovery
- Camelot/Camelot-py for PDF table extraction — adds another dependency, still lossy
- Apache Tika — heavy dependency, overkill for structured DOCX

### Decision 2: Parent-child chunking with explicit relationship graph
**Choice**: Store chunks as a directed graph with explicit parent→child→leaf edges. Interface owns methods+properties. Method owns parameters. Enum owns values.
**Rationale**: Multi-granularity retrieval needs to know relationships. When a parameter chunk is retrieved, the system must be able to walk up to the parent method and grandparent interface for context. A flat chunk list (current approach) cannot support this without separate metadata joins.
**Storage**: In-memory graph built at index time (small enough for 2000 functions). Serialized alongside FAISS index for persistence.

### Decision 3: Hybrid retrieval with RRF fusion
**Choice**: BM25 (word-level tokenization for exact names) + embedding similarity (all-mpnet-base-v2 for semantic) + link traversal (follow type cross-references), fused via Reciprocal Rank Fusion (RRF).
**Rationale**: API queries have two distinct modes: exact keyword ("Find CreateUser method") and semantic ("How do I apply a load to a shell element?"). BM25 handles the first, embeddings handle the second. Link traversal enriches results with referenced types.
**Alternatives considered**:
- Embedding-only (current cosine backend) — misses exact matches for `E_INVALIDARG`, `AddNode`, `AnalysisType.Modal`
- Vector-only reranking — same problem
- Learned fusion weights — deferred until labeled Q/A pairs exist for DSPy optimization

### Decision 4: DSPy signatures instead of hand-crafted prompt
**Choice**: Replace `build_prompt()` with typed DSPy signatures: `QueryAnalyzer`, `ContextAssembler`, `APIResponseGenerator`.
**Rationale**: DSPy signatures are self-documenting, testable, and optimizable via compilation. The 210-line hand-crafted prompt in `prompt_builder.py` is the single hardest file to maintain and tune. DSPy signatures make the LM's job explicit and let MIPROv2 optimize the prompt text from data.
**Implementation**: Start with `dspy.Predict` and `dspy.ChainOfThought` without compilation. Add `dspy.MIPROv2` when 20+ labeled Q/A pairs exist.

### Decision 5: Custom LM adapter (dspy.BaseLM)
**Choice**: Wrap existing `MLXLLM` singleton in a `dspy.BaseLM` subclass. Set this as DSPy's default LM.
**Rationale**: DSPy needs a standard LM interface. `MLXLLM` has `generate()` while DSPy expects `forward()`. The adapter is ~30 lines and preserves all existing behavior (model caching, temperature, repetition penalty).
**No additional cost**: MLX Qwen2.5-1.5B runs locally. No OpenAI or API key needed.

### Decision 6: Separate API route
**Choice**: New route at `/api/v1/query/api-docs` with its own request/response models.
**Rationale**: Clean separation from existing query routes. Avoids breaking changes to the existing `/api/v1/query` routing (which dispatches by backend type). Frontend integration can come later.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|---|---|---|
| **DOCX table format variations** | Extraction fails on unexpected column layouts | Validate with `pydantic` models; fall back to PDF text extraction on validation failure |
| **DSPy + MLX compatibility** | DSPy's OpenAI-format API calls may not work with MLX's interface | Thorough integration test with the custom LM adapter before building pipeline |
| **Chunk graph memory usage** | 2000 functions × parent+children → large in-memory graph | Estimate: ~2MB for 2000 functions (each chunk ~200 bytes + edges). If too high, use SQLite-backed graph |
| **No DSPy compilation in v1** | Pipeline not yet optimized — may not outperform existing backends initially | Establish baseline metrics against current backends; compilation is a performance bump, not correctness gate |
| **python-docx version compatibility** | DOCX files created by different Word versions may parse differently | Pin `python-docx>=1.1` and test with representative DOCX samples from the actual doc set |
| **Cross-reference link discovery** | Links between interfaces are implicit in the text ("See INode") rather than marked up | Use LLM-based link extraction on first pass (DSPy `ExtractCrossReferences` signature), then cache |

## Open Questions
- How to version the chunk graph when DOCX documents are updated? Same document hash → rebuild index?
- Should the DSPy pipeline support streaming responses like the existing backends? (Streaming is currently handled by `StreamingResponse` in the API layer)
- Frontend integration timeline — who adds the Streamlit UI for the new route?
