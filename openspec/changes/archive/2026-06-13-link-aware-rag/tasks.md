## 1. Data Structures and Parser Interface

- [x] 1.1 Add `LinkInfo` dataclass to `src/infrastructure/parsers/base.py` with fields: `type`, `source_page`, `target_page`, `uri`, `named_dest`, `bbox`, `anchor_text`
- [x] 1.2 Add `extract_links()` method to `DocumentParser` abstract base class with default implementation returning `[]`
- [x] 1.3 Update `ParserRegistry` to propagate `extract_links()` alongside `parse()`

## 2. PDF Link Extraction

- [x] 2.1 In `src/infrastructure/parsers/base.py` `PDFParser`, implement `extract_links()` using `fitz.Page.get_links()` — handle `LINK_GOTO` (internal page refs), `LINK_URI` (external URIs), and named destinations via `doc.resolve_link()`
- [x] 2.2 Add debug-log fallthrough for unsupported link types (`LINK_LAUNCH`, `LINK_FILE`)
- [x] 2.3 Write unit tests for PDF link extraction in `tests/unit/test_pdf_link_extraction.py`

## 3. DOCX Link Extraction

- [x] 3.1 In `src/infrastructure/parsers/base.py` `DocxParser`, implement `extract_links()` iterating over paragraphs and extracting `run.hyperlink` elements with relationship resolution
- [x] 3.2 Wrap per-paragraph link extraction in try/except with warning-level logging for malformed hyperlinks
- [x] 3.3 Write unit tests for DOCX link extraction in `tests/unit/test_docx_link_extraction.py`

## 4. Link Resolution Pass in Processor

- [x] 4.1 Create `resolve_links(chunks: list[dict], all_links: list[LinkInfo]) -> None` function in `src/domain/services/link_resolver.py` that:
  - Builds a `page → chunk_index` map from the chunk list (all chunks know their source page from metadata or page markers)
  - For each `LinkInfo` with `type == "internal"` and known `target_page`, resolves to target chunk IDs
  - Writes `links` and `backlinks` arrays into each chunk's `chunk_metadata`
  - Caps backlinks at 10 entries per chunk
- [x] 4.2 Integrate resolution pass into `process_document_async()` in `processor.py` — call `resolve_links()` between chunking and embedding, passing extracted links from `parser_registry.extract_links()`
- [x] 4.3 Ensure semantic pipeline path also flows extracted links through to the resolution step
- [x] 4.4 Write unit tests for link resolution in `tests/unit/test_link_resolution.py`

## 5. Link-Aware Embedding Augmentation

- [x] 5.1 Add `build_augmented_text_with_links(chunk_content, chunk_metadata, link_target_contents) -> str` function to `src/pdf_semantic_chunking/augmentation.py`
  - Appends "Links To:" and "Referenced From:" sections after existing prefix
  - Caps at 3 outgoing links and 3 backlinks
  - 150-char max per link target summary
  - Graceful fallback for missing target chunks (`"[deleted chunk]"`)
- [x] 5.2 Update the embedding loop in `processor.py` to gather link target chunk content and call `build_augmented_text_with_links()` when link metadata is present
- [x] 5.3 Write unit tests in `tests/unit/test_link_augmentation.py`

## 6. Query-Time Link Traversal

- [x] 6.1 Implement `_expand_with_links(chunks: list[tuple], db_session, decay_factor=0.85, expansion_factor=2) -> list[tuple]` helper in `src/api/routes/query/_retrieval.py`
  - Reads `links`/`backlinks` from `chunk_metadata`
  - Fetches target chunks from DB by ID
  - Applies score decay: `linked_score = source_score * decay_factor`
  - Deduplicates: keeps highest score per unique chunk
  - Caps final result set at `len(cosine_results) * expansion_factor`
- [x] 6.2 Integrate `_expand_with_links()` into `retrieve_chunks()` after cosine similarity computation
- [x] 6.3 Add `retrieved_via` field to result chunks (`"cosine_similarity"` or `"link_traversal"`)
- [x] 6.4 Expose `link_decay_factor` and `link_expansion_factor` as configurable query parameters
- [x] 6.5 Update query cache to incorporate `link_expansion_factor` and `link_decay_factor` in cache key
- [x] 6.6 Write unit tests for link traversal in `tests/unit/test_link_traversal.py`

## 7. Integration and Verification

- [x] 7.1 Run full test suite: `uv run pytest -v`
- [x] 7.2 Add integration test: upload PDF with internal cross-references, verify linked chunks appear in query results
- [x] 7.3 Run `uv run ruff check .` and `uv run mypy src/` to ensure no regressions
