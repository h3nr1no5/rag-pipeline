## Context

The API documentation RAG pipeline ingests AxisVM COM API documentation as DOCX files. The extraction stage (`converter.py`) produces domain objects (interfaces, methods, properties, enums, records, error codes) from classified tables. Paragraphs (prose) between headings and tables are extracted during parsing but only used for heading-context tracking and the first-paragraph interface description — all other prose is silently discarded. Tables that don't match any known type classifier are also silently dropped.

The chunking stage (`builder.py`) builds a parent-child chunk graph from domain objects. Metadata completeness is high for most types, but `enum_value` and `record_field` chunks lack `interface_name`.

The retrieval stage uses a hybrid BM25+embedding pipeline followed by RRF fusion, cross-encoder reranking, and two expansion steps: `LinkTraverser` (follows `I`-prefix COM interface cross-references) and `ParentExpander` (walks the parent chain). `LinkTraverser` only matches `I`-prefix names, missing `E`-prefix enum type cross-references.

The generation stage (`manager.py` `_generate_answer`) uses a minimal prompt: "You are an API documentation assistant. Answer based solely on context." No citation markers, no grounding constraints, no anti-repetition guard, and most critically no instruction to use exact enum values — enabling the LLM to invent plausible-looking but incorrect API values.

Two existing changes have addressed related areas: `fix-api-docs-answer-quality` (DSPy prompt assertions, temperature, verification toggle) and `fix-api-docs-pipeline-core` (embedding double-format, cross-encoder reranking, LinkTraverser race fix). Our 6 areas are complementary and not covered by those changes.

## Goals / Non-Goals

**Goals:**

1. **Paragraph chunks** — All prose paragraphs under an interface heading become retrievable child chunks of the parent interface.
2. **Unknown table handling** — Tables that fail classification are preserved as generic table chunks instead of being dropped.
3. **Metadata completeness** — Every chunk type with a `parent_interface` domain field carries `interface_name` in its metadata.
4. **Enum cross-reference traversal** — `LinkTraverser` follows `E`-prefix enum type names alongside existing `I`-prefix interface names.
5. **Enum value accuracy** — The generation prompt explicitly instructs the LLM to use exact enum values from context.
6. **Prompt enrichment** — The generation prompt gains citation markers (`[Source N]`), grounding requirements, anti-repetition guard, and response structure controls.

**Non-Goals:**

- Redesigning the table detection/classification algorithm for known types (Functions, Properties, Enums, etc.)
- Changing the general chunk-level `link-traversal` system (only the api-docs `LinkTraverser`)
- Altering BM25 or embedding index architecture (new chunk types flow through naturally)
- Adding DSPy assertion changes (already handled by `fix-api-docs-answer-quality`)
- Adding cross-encoder or response verification (already handled by `fix-api-docs-pipeline-core`)
- PDF parsing pipeline (only DOCX extraction)

## Decisions

### D1: Paragraphs as content strings on APIInterface, not a new domain type

**Decision:** Store paragraph texts as a `paragraphs: list[str]` field directly on `APIInterface` rather than creating a new `APIParagraph` domain model class or storing them separately.

**Rationale:** Paragraphs are unstructured prose with no complex attributes (no name, type, parameters). A `list[str]` is the simplest representation and avoids over-engineering. The paragraph text is already available in `RawDocument.paragraphs` — we just need to associate it with the correct interface via the heading context stack.

**Alternatives considered:**
- *New `APIParagraph` model* — Would add unnecessary indirection for what is essentially text content with a heading context.
- *Store paragraphs as separate index in converter* — Would require parallel tracking that's less maintainable than a simple field on `APIInterface`.

### D2: Paragraph chunks are children of interface, not separate roots

**Decision:** Paragraph chunks are created as level-1 children of their parent interface node (same level as methods and properties).

**Rationale:** This connects paragraphs to their owning interface in the chunk graph, enabling `ParentExpander` to pull in the parent interface when a paragraph is matched. The interface itself is the natural grouping boundary.

**Alternatives considered:**
- *Independent root nodes* — Would lose the parent relationship, making it harder for ParentExpander to surface the interface context.
- *Level-0 siblings of interface* — Inconsistent with the hierarchy; paragraphs belong to an interface, they are not top-level entities.

### D3: Generic table chunks store raw markdown-like text, not structured data

**Decision:** Unknown tables are rendered as a markdown-like text representation (header row + data rows) and stored as `generic_table` chunks, children of the nearest interface in the heading context. No attempt is made to parse unknown table structures.

**Rationale:** Unknown tables have unpredictable structure — attempting to parse them could introduce errors. The LLM can interpret raw table content more flexibly than a rigid structure. The raw text is also equally useful for both BM25 keyword search and embedding similarity.

**Alternatives considered:**
- *Generic table domain object* — Would require maintaining a catch-all structure whose schema varies per table type; fragile and hard to maintain.
- *Silent discard (current behavior)* — Loses potentially valuable content.

### D4: Extend LinkTraverser regex, not add a separate traverser

**Decision:** Modify the existing LinkTraverser regex from `\bI[A-Z][a-zA-Z0-9_]*\b` to also match `\bE[A-Z][a-zA-Z0-9_]*\b` enum type names. Resolve matched names against both interface and enum node IDs.

**Rationale:** The traversal logic (recursive following, dedup, depth limiting) is identical for both interface and enum references. A single traverser with an expanded name resolution set is simpler than two separate traversers.

**Key implementation detail:** The existing `_interface_name_to_id` cache only maps interface names to IDs. We need an analogous `_enum_name_to_id` mapping (or a unified `_type_name_to_id` map) to resolve matched enum names.

**Alternatives considered:**
- *Separate EnumTraverser* — Duplicates traversal logic with no benefit; both types follow the same algorithm.
- *Pre-expand enum values at chunking time* — Would bake enum values into method chunks, increasing storage and reducing flexibility.

### D5: Prompt enrichment reuses the existing prompt template string

**Decision:** The prompt template string in `_generate_answer()` is replaced with an expanded version that includes all guardrails inline, rather than extracting it to a separate file or using DSPy signatures.

**Rationale:** The prompt is specific to the api-docs pipeline. Keeping it inline in `manager.py` avoids premature abstraction into a separate file. The `prompt_builder.py` pattern from the general RAG pipeline serves as a reference but is not directly shared since the api-docs pipeline uses a different generation architecture (direct LLM call, not DSPy).

**Prompt additions:**
```
1. "Use EXACT enum values from context. Do not invent or approximate enum member names."
2. "Cite each source as [Source N] where N is the index of the relevant chunk."
3. "Only use information from the provided context. If the context does not contain the answer, say so."
4. "Do not repeat the same information multiple times."
5. "Structure your answer with clear sections if multiple concepts are discussed."
```

**Alternatives considered:**
- *Extract to external prompt file* — Adds indirection for a prompt that is only used in one place.
- *Use DSPy signatures* — The api-docs pipeline is architected as a direct LLM call; switching to DSPy is out of scope.

## Risks / Trade-offs

1. **[Risk] Paragraph chunks may duplicate content** — If an interface's first paragraph is captured both as the interface `description` field AND as a paragraph chunk, the same text appears in two chunks. → **Mitigation:** The converter's `_build_interface_descriptions()` stores the first paragraph as the interface description. We skip that paragraph when building paragraph chunks to avoid duplication.

2. **[Risk] Unknown tables may add noise** — Some unknown tables may truly be irrelevant (e.g., formatting artifacts). Generic table chunks passed to the LLM could dilute context. → **Mitigation:** Unknown table chunks are indexed and retrievable like any other chunk, but the reranking step (cross-encoder) naturally deprioritizes low-relevance content. No special filtering needed.

3. **[Risk] Enum cross-reference traversal expands retrieval results** — Adding `E`-prefix matching to LinkTraverser could pull in many enum chunks that are not actually referenced by the matched method. → **Mitigation:** The regex match still requires the exact name of an enum type to appear in the chunk content (e.g., the method signature includes `ENationalDesignCode`). Only names that match an actual enum node ID are resolved. The existing max_depth=2 bound still applies.

4. **[Risk] Prompt changes may interact with DSPy assertions** — The `fix-api-docs-answer-quality` change relaxed assertions to advisory mode. Adding citation requirements to the prompt with no assertion enforcement could lead to inconsistent citation formatting. → **Acceptance:** The DSPy assertions were specifically relaxed to avoid fallback to `Predict`. Citation quality is an LLM behavior issue, not a hard requirement. The metadata in the response will indicate whether citations were included.
