## Context

The RAG pipeline currently extracts plain text from PDFs (via PyMuPDF's `page.get_text()`) and DOCX files (via python-docx), then chunks and embeds that text. PDF hyperlinks — both internal cross-references ("see §3.2.1") and external URIs — are silently discarded because neither parser requests them.

PyMuPDF provides `page.get_links()` and `doc.resolve_link()` for free (no new dependencies). python-docx stores hyperlinks as OpenXML relationships. Both are available but unused.

The existing `chunk_metadata` JSON column on the `Chunk` model can store link data without schema migration. The existing augmentation layer in the semantic chunking pipeline already injects metadata prefixes into embedding text, and can be extended to inject resolved link targets.

## Goals / Non-Goals

**Goals:**
- Extract all hyperlinks from PDFs (internal page refs, external URIs, named destinations) and DOCX files (external URIs)
- Resolve internal links to target chunk IDs via a two-pass pipeline (chunk first, then resolve)
- Inject resolved link context into embeddings so vectors capture structural relationships
- Expand retrieval at query time with 1-hop link traversal to surface structurally connected chunks
- All changes additive — no existing behavior breaks, no schema changes

**Non-Goals:**
- Anchor text extraction (linking link bounding rects to specific text spans — complex, deferred)
- DOCX internal bookmark resolution (requires raw XML parsing of `w:bookmarkStart`)
- Markdown link parsing (text-level links are a different problem)
- Multi-hop traversal (>1 hop — bounded at 1 to prevent topic drift)
- Index rebuild for existing documents (links can only be extracted at parse time)
- Graph databases or dedicated link storage (links live in JSON metadata)

## Decisions

### Decision 1: Two-pass processing (chunk → resolve → embed)

**Choice:** Run link resolution as a separate pass between chunking and embedding, instead of resolving links inline during chunking.

**Rationale:**
- Links are page-based but chunks may span pages (semantic pipeline) or split mid-page (recursive pipeline). You can't resolve a link to a chunk until all chunks exist.
- Named destinations need the TOC/heading map, which only exists after extraction + enrichment.
- Separting concerns: chunking doesn't need to know about links, and link resolution doesn't need to know about chunking strategies.

**Alternative considered:** Resolve during parsing by recording link target page numbers, then match to chunks after chunking — this is essentially the two-pass approach but with data flowing through parse results instead of a dedicated pass. Rejected because it couples parsing logic to chunking concerns.

### Decision 2: Both pre-embedding augmentation AND query-time traversal

**Choice:** Inject resolved link targets into embedding text AND do 1-hop link traversal at retrieval.

**Rationale:**
- Pre-embedding augmentation ensures the vector representation of "See §3.2.1" is close to the vector of "Proof of termination: ..." — semantic proximity for structural relationships.
- Query-time traversal catches cases the vector misses (e.g., when the linked content uses different terminology than the reference).
- They complement each other: augmentation improves recall, traversal improves precision of structural connections.

**Alternative considered:** Only one or the other. Rejected because each addresses a different failure mode.

### Decision 3: No new data model — links in chunk_metadata JSON

**Choice:** Store link data and backlinks in the existing `chunk_metadata` JSON column.

**Schema per chunk:**
```json
{
  "...existing fields...": "...",
  "links": [
    {"type": "internal", "target_chunk_ids": ["uuid-..."], "target_page": 12, "uri": null},
    {"type": "external", "uri": "https://example.com", "target_chunk_ids": []}
  ],
  "backlinks": [
    {"source_chunk_id": "uuid-...", "anchor_text": null}
  ]
}
```

**Rationale:** No migration, no new tables, no ORM changes. The JSON column is already in use. Query-time traversal reads this metadata to find related chunks.

**Alternative considered:** New `chunk_links` SQLAlchemy table with source/target FKs. Rejected because it adds migration complexity and the link data is small (< 1KB per chunk).

### Decision 4: 0.85 score decay for linked chunks at retrieval

**Choice:** Linked chunks retrieved via traversal get their score multiplied by 0.85 (the score of the chunk they were reached from).

**Rationale:** Linked chunks are structurally relevant but should rank below the direct hit they were reached from. 0.85 is a heuristic that preserves ordering while keeping linked chunks visible above unrelated chunks. Configurable via parameter.

### Decision 5: Named destinations resolve to page number only

**Choice:** Resolve PDF named destinations to their target page number (via `doc.resolve_link()`) and let the page→chunk map determine which chunk(s) the link hits.

**Rationale:** PDF named destinations often target arbitrary y-positions on pages rather than specific headings. Resolving to page is reliable; resolving to a specific heading requires bounding-box matching against the element tree, which is complex and fragile.

### Decision 6: Additive parser interface

**Choice:** Add `extract_links()` as an optional method on `DocumentParser`, defaulting to empty list. Keep `parse()` returning `str` unchanged.

**Rationale:** Zero breakage for existing parsers. The registry propagates `extract_links()` alongside `parse()`. All existing callers continue to work.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Named destination resolution is imprecise** | Links may point to wrong chunk if multiple chunks share a page | Page→chunk mapping with multiple candidates is fine — 1-hop traversal pulls all candidate chunks. The relevant one typically has higher cosine similarity. |
| **Backlink explosion in dense documents** | A single chunk could accumulate dozens of backlinks | Cap `backlinks` array at 10 entries in metadata (first-come-first-served, or most-relevant-first via anchor text matching) |
| **Augmented embedding text exceeds chunk size limits** | Embedding quality degrades if augmented text is too long | Cap injected link target text at 150 chars per link, max 3 outgoing links and 3 backlinks in augmentation |
| **One-hop misses indirect relationships** | If A links to B and B links to C, C won't be retrieved | Intentionally bounded at 1 hop. 2-hop analysis shows diminishing returns in similar graph-based retrieval systems. |
| **DOCX hyperlink XML parsing fragility** | Malformed DOCX could break extraction | Wrap DOCX link extraction in try/except per paragraph; skip unparseable hyperlinks silently |
