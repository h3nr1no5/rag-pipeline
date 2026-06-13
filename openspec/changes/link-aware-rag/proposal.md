## Why

PDF and DOCX documents frequently contain hyperlinks — internal cross-references ("see §3.2.1", "as noted in Appendix A"), external URLs, and table-of-contents links. The current RAG pipeline silently discards all of these during text extraction, meaning:

- Cross-referenced content is contextually orphaned (an LLM sees "as described above" with no resolution)
- Retrieval relies purely on semantic similarity, missing structural connections that links provide
- Documents with dense internal references (technical specs, manuals, standards) lose their navigational structure

This change introduces **link-aware RAG**: extracting links during parsing, resolving them to target chunks, injecting link context into embeddings, and using link-traversal at query time to retrieve structurally connected chunks.

## What Changes

1. **Link extraction** — new `extract_links()` method on parsers for PDF (internal, external, named destinations via PyMuPDF) and DOCX (external URLs via python-docx relationships)
2. **Link resolution** — a new pipeline stage after chunking that resolves links to target chunk IDs, building forward and reverse link indexes per chunk
3. **Link-aware embedding augmentation** — enriched embedding text that includes resolved link targets, so vectors capture structural relationships
4. **Query-time link traversal** — 1-hop expansion after cosine similarity retrieval, pulling both directly-referenced and backlinked chunks

No schema changes required (links live in the existing `chunk_metadata` JSON column). All changes are additive — no existing behavior breaks.

## Capabilities

### New Capabilities
- `link-extraction`: Parse hyperlinks from PDF (internal page refs, external URIs, named destinations) and DOCX (external URIs), returning structured link metadata attached to source pages
- `link-traversal`: Query-time 1-hop graph expansion that fetches chunks linked to or from cosine-similarity results, with configurable score decay

### Modified Capabilities
- `semantic-chunking-engine`: Augmentation now accepts link context to produce enriched embedding text that includes resolved link target summaries

## Impact

| Area | Impact |
|------|--------|
| `src/infrastructure/parsers/base.py` | NEW: `LinkInfo` dataclass, `extract_links()` on `DocumentParser`, implementations for PDF + DOCX |
| `src/domain/services/processor.py` | NEW: link resolution pass between chunking and embedding |
| `src/pdf_semantic_chunking/augmentation.py` | MODIFIED: `build_augmented_text_with_links()` added alongside existing |
| `src/api/routes/query/_retrieval.py` | MODIFIED: `retrieve_chunks()` gains link traversal step |
| Dependencies | None new (PyMuPDF and python-docx already present) |
| Backward compat | Full — `parse()` still returns `str`, `extract_links()` defaults to `[]` |
