## Why

The current PDF processing pipeline flattens all PDFs to raw text via PyMuPDF `page.get_text()`, discarding all structural information — page boundaries, headings, code blocks, tables, and interface/function definitions. For technical documentation like COM interfaces, API references, and SDK guides, this lossy extraction produces low-quality chunks that dilute retrieval precision. A dedicated semantic chunking pipeline is needed to parse PDFs with structure awareness, producing clean, semantically rich chunks at function-level granularity that vector embeddings can effectively retrieve against.

For **COM API documentation specifically** (e.g., AxisVM COM API Reference), queries demand function/property-level precision — "How do I bring AxisVM window to front?", "What is the return type of ChangeUnitSystem?", "List all error codes in IAxisVMApplication". Achieving this requires not just structure-aware extraction, but domain-specific enrichment that recognizes COM constructs (interfaces, methods, properties, enums, records, error codes) and chunks them at the natural atomic boundary for each element type.

The existing "API Documentation" chunking strategy (`id: "api-docs"`) uses simple markdown-style separators applied to flat text — it offers no real structure awareness. The semantic chunker **replaces this strategy entirely**, routing through a layout-aware pipeline when users select this strategy on upload.

## What Changes

- Create a new **`pdf-semantic-chunking`** module that replaces the behavior of the existing "API Documentation" chunking strategy
- Implement a **structure-aware PDF parser** that extracts text with layout context: headings, code blocks, tables, lists, and page regions
- Implement a **COM structure enrichment stage** that identifies interfaces, methods, properties, enums, records, and error codes from C# COM interop patterns, producing a hierarchical tree of Interfaces → Sections → Elements
- Build a **semantic chunking engine** that identifies natural boundaries (function signatures, interface definitions, section headings, COM element types) and produces atomic chunks per element type — never splitting a function from its parameters, an enum block, or a record definition
- Implement **per-element-type token-based chunk sizing** with defaults tuned to each COM element type (functions 400-800t, properties 150-400t, enums 300-600t, records 200-500t, error codes 200-400t)
- Attach **rich COM metadata** per chunk: `interface`, `section`, `element_type`, `element_name`, `signature`, `return_type`, `parameters` (with direction/type/description), `error_codes`, `keywords`, `token_count`
- Implement a **domain-specific embedding prefix strategy**: `"COM API Function: IAxisVMApplication.BringToFront"` for improved retrieval relevance
- Implement **validation gates**: automated required-field checks, token distribution analysis, and human sampling workflows
- Expose a **CLI entrypoint** for standalone usage and an **async API** for programmatic integration
- **Wire into `processor.py`** — when the "API Documentation" strategy is selected, route through the semantic chunker instead of the recursive splitter
- On **partial failure** (e.g., pdfminer fails on page 30/100), perform a **full rollback** with a detailed structured error report

## Capabilities

### New Capabilities
- `pdf-structure-parser`: Structure-aware PDF parsing that extracts text with layout context — headings, code blocks, tables, lists, and hierarchical section boundaries. Handles multi-column layouts and preserves reading order.
- `semantic-chunking-engine`: Produces semantically coherent chunks at function/method/interface granularity. Uses structural boundaries (headings, function signatures, blank pages) as natural split points, with COM-enriched per-element-type token sizing, overlap, and metadata. Outputs chunks with the full COM metadata schema.
- `com-structure-enrichment`: Identifies COM constructs (interfaces, methods, properties, enums, records, error codes) from the parsed document tree by recognizing C# COM interop patterns — attribute clusters (`[ComImport]`, `[Guid(...)]`), interface declarations, method signatures, error code groupings. Produces an Interface → Section → Element hierarchy consumable by the chunking engine.

### Modified Capabilities
- **API Documentation chunking strategy** (`id: "api-docs"`): Its behavior is replaced by the semantic chunker. Users who select this strategy on PDF upload now get structure-aware extraction + COM enrichment + token-based semantic chunking instead of separator-based recursive splitting.
- **`processor.py`**: Modified to detect when the active strategy requires semantic chunking and route to the new pipeline.

## Impact

- **New module**: `src/pdf-semantic-chunking/` with its own package structure including `extraction/`, `enrichment/`, `detection/`, `chunking/`, and `pipeline/` subpackages
- **New dependency**: `pdfminer.six` for layout-aware PDF parsing (quality preferred over raw speed); recommended embedding model update to `text-embedding-3-large` or `voyage-code-2` for COM API retrieval
- **New spec**: `specs/com-structure-enrichment/spec.md` defining the COM enrichment layer
- **Modified**: `specs/semantic-chunking-engine/spec.md` — expanded significantly with COM-specific scenarios, token-based sizing, rich metadata schema, embedding prefix strategy, and validation gates
- **Modified**: `src/domain/services/processor.py` — adds routing logic to dispatch to semantic chunker when the "API Documentation" strategy is active
- **Optional**: `ChunkingStrategy` model may gain an `engine_type` field (`"recursive"` / `"semantic"`) for clean routing extensibility
- **No changes** to database models or vector store schema (chunk metadata is forward-compatible; embedding augmentation is done at the processor level before storage)
- New tests in `tests/pdf-semantic-chunking/`
