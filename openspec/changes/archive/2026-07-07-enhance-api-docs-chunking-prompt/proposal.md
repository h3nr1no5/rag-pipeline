## Why

The API documentation RAG pipeline (AxisVM COM API, DOCX source) drops two valuable content types — prose paragraphs and unclassified tables — and lacks critical metadata on enum values and record fields. The retrieval step does not follow enum-type cross-references, and the generation prompt has no guardrails against enum value hallucination. Together these defects cause the model to miss relevant context and invent plausible-looking but incorrect API values.

## What Changes

1. **Index prose paragraph chunks** — Paragraphs between headings and tables are converted into retrievable chunks, linked as children of their parent interface.
2. **Preserve unknown tables** — Table types that don't match any known pattern (Functions, Properties, Enums, Records, ErrorCodes) are no longer silently dropped; they become generic table chunks.
3. **Add missing metadata** — `interface_name` is injected into `enum_value` and `record_field` chunk metadata so their owning interface is always available.
4. **Cross-reference enum types in LinkTraverser** — The `LinkTraverser` (api-docs pipeline) currently only follows `I`-prefix COM interface references; extend it to also follow `E`-prefix enum type names so enum definitions are pulled into retrieval results alongside the methods that reference them.
5. **Enforce exact enum values in prompt** — The generation prompt is augmented with an explicit instruction: *"Use EXACT enum values from context. Do not invent or approximate."*
6. **Enrich generation prompt** — Add `[Source N]` citation markers, grounding instructions, anti-repetition guard, and response structure controls (matching the pattern from `prompt_builder.py`).

## Capabilities

### New Capabilities

- `api-docs-paragraph-chunks`: Prose paragraphs from API documentation DOCX files are indexed as retrievable chunks, linked to their parent interface. This captures interface descriptions and explanatory prose that were previously discarded.
- `api-docs-unknown-table-handling`: Table blocks that do not match any known COM type classifier produce generic table chunks instead of being silently dropped, preserving potentially valuable documentation content.

### Modified Capabilities

- `com-structure-enrichment`: The `interface_name` metadata field is now populated on `enum_value` and `record_field` chunk nodes (previously missing). The `LinkTraverser` retrieval step is extended to follow `E`-prefix enum type cross-references in addition to `I`-prefix interface references.
- `api-docs-rag`: The generation prompt is enriched with exact-enum-value instructions, `[Source N]` citation markers, grounding requirements, and anti-repetition guards to reduce hallucination and improve answer quality.

## Impact

- **src/domain/rag/api_docs/extraction/converter.py** — Paragraph extraction logic modified to produce domain objects; unknown table type handling added.
- **src/domain/rag/api_docs/chunking/builder.py** — Add `interface_name` to `enum_value` and `record_field` metadata; add paragraph chunk type and generic table chunk type.
- **src/domain/rag/api_docs/chunking/text_formatter.py** — Support formatting for paragraph and generic-table chunk kinds.
- **src/domain/rag/api_docs/retrieval/link_traverser.py** — Extend regex to match `E`-prefix enum type names; add enum node ID resolution.
- **src/domain/rag/api_docs/manager.py** — Enrich prompt template with enum accuracy instruction, citations, grounding, and guardrails.
- **src/domain/rag/api_docs/model/models.py** — Minor: no changes expected unless new domain types needed for paragraphs/tables.
- **src/domain/rag/api_docs/retrieval/bm25_index.py** — May need update if paragraph/table chunks require different keyword text construction.
- **src/domain/rag/api_docs/retrieval/embedding_index.py** — No structural changes expected (already indexes all chunks).
- **openspec/specs/api-docs-paragraph-chunks/spec.md** — New spec.
- **openspec/specs/api-docs-unknown-table-handling/spec.md** — New spec.
- **openspec/specs/com-structure-enrichment/spec.md** — Delta spec for metadata + link traversal changes.
- **openspec/specs/api-docs-rag/spec.md** — Delta spec for prompt improvements.
