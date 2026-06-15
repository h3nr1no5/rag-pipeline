## 1. Main Cosine Path — Use Stored Embeddings

- [x] 1.1 In `_retrieval.py`, modify `retrieve_chunks()` to load `Chunk.embedding` directly instead of re-embedding `Chunk.content`
- [x] 1.2 Add `Chunk.embedding.isnot(None)` filter to the SQL query that loads chunks
- [x] 1.3 Remove the `embedder.embed_texts(chunk_texts)` call (only `embed_query` remains)
- [x] 1.4 Build `chunk_embeddings` list from `c.embedding` for each chunk
- [x] 1.5 Add fallback for chunks with `None` embedding: skip them from similarity computation

## 2. LangChain Path — Use Stored Embeddings

- [x] 2.1 In `routes.py` (LangChain query handler), modify chunk loading to pass pre-stored embeddings
- [x] 2.2 Update the LangChain FAISS index construction to use stored `chunk_embedding` vectors
- [x] 2.3 Remove the `embedder.embed_texts()` call in the LangChain path
- [x] 2.4 Verify BM25 keyword retrieval still uses chunk content (should be unchanged)

## 3. Fix Internal Link Target Content Resolution

- [x] 3.1 In `augmentation.py` line 95, change `contents.get(tid)` to `contents.get(str(tid))`
- [x] 3.2 Verify internal link target content renders correctly in "Links To:" blocks

## 4. Minimum Relevance Score for Main Cosine Path

- [x] 4.1 In `_retrieval.py`, import or access `settings.MIN_RELEVANCE_SCORE` from config
- [x] 4.2 After computing cosine similarity scores, filter out scores below the threshold
- [x] 4.3 Apply top-k selection on the filtered (score >= threshold) list
- [x] 4.4 Handle edge case: if no chunks pass the threshold, return empty results

## 5. Recursive Path Consistency

- [x] 5.1 In `processor.py`, recursive path's "no hyperlinks" branch: replace `chunk_info["content"]` with `build_augmented_text(chunk_info)`
- [x] 5.2 Verify the import of `build_augmented_text` is available in the recursive path scope
- [x] 5.3 Ensure `build_augmented_text` handles recursive path metadata structure correctly

## 6. Default use_hyperlinks

- [x] 6.1 Verify `use_hyperlinks` default is `False` in `entities.py` ChunkingStrategy dataclass
- [x] 6.2 Verify `use_hyperlinks` default is `False` in `models.py` SQLAlchemy column
- [x] 6.3 Verify `use_hyperlinks` default is `False` in `schemas/document.py` Pydantic model

## 7. Tests

- [x] 7.1 Update `_retrieval.py` tests to mock `Chunk.embedding` (not `embedder.embed_texts`)
- [x] 7.2 Test that `Chunk.embedding.isnot(None)` filter is applied in SQL
- [x] 7.3 Test that chunks with `None` embedding are skipped
- [x] 7.4 Test `min_relevance_score` filtering in the main cosine path
- [x] 7.5 Test recursive path augmented text injection
- [x] 7.6 Test link target content resolution with the str/int fix
- [x] 7.7 Run full test suite: `uv run pytest -v` and fix any failures
- [x] 7.8 Run linter: `uv run ruff check .`
