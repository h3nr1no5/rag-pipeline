# Retrieval

## Purpose

Defines requirements for the chunk retrieval subsystem — how stored embeddings, relevance scoring, and augmented text are used to retrieve relevant document chunks in response to user queries.

## Requirements

### Requirement: Use pre-stored chunk embeddings for retrieval

The retrieval system SHALL use pre-computed `Chunk.embedding` vectors stored in the database during document processing, instead of re-embedding `Chunk.content` at query time. This ensures the embedding captures the augmented text context (COM API metadata, section hierarchy, and optional hyperlink context) that was computed during processing.

#### Scenario: Main cosine path uses stored embeddings

- **WHEN** a query arrives at `POST /api/v1/query`
- **AND** chunks exist for the target document with non-null `Chunk.embedding`
- **THEN** `retrieve_chunks()` SHALL load `Chunk.embedding` vectors directly
- **AND** compute cosine similarity against the single query embedding
- **AND** NOT call `embedder.embed_texts()` on chunk content

#### Scenario: Chunks without embeddings are excluded from retrieval

- **WHEN** loading chunks for query-time retrieval
- **THEN** the SQL query SHALL include `Chunk.embedding.isnot(None)` filter
- **AND** chunks with `NULL` embedding SHALL be silently excluded

#### Scenario: LangChain path uses stored embeddings

- **WHEN** a query arrives at `POST /api/v1/query/langchain`
- **THEN** the LangChain retriever SHALL use pre-stored `Chunk.embedding` vectors
- **AND** NOT re-embed `Chunk.content` via `embedder.embed_texts()`
- **AND** BM25 keyword retrieval still uses chunk content (unchanged)

#### Scenario: LlamaIndex path already correct

- **WHEN** a query arrives at `POST /api/v1/query/llamaindex`
- **THEN** behavior is already correct (uses `Chunk.embedding`)
- **AND** no changes are needed

### Requirement: Minimum relevance score for main cosine path

The main cosine retrieval path SHALL filter out chunks whose cosine similarity to the query is below a configurable `min_relevance_score` threshold, matching the LangChain path behavior.

#### Scenario: Low-relevance chunks are excluded

- **WHEN** `MIN_RELEVANCE_SCORE` is set to `0.15` (default from config)
- **AND** a chunk's cosine similarity to the query is `0.08`
- **THEN** that chunk SHALL be excluded from results
- **AND** not appear in the top-k selection

#### Scenario: Threshold is configurable

- **WHEN** `MIN_RELEVANCE_SCORE` is set to `0.0`
- **THEN** all chunks pass the threshold filter
- **AND** retrieval reverts to pure top-k behavior

### Requirement: Augmented text for recursive chunking path

The recursive chunking path SHALL always inject COM API metadata into embeddings via `build_augmented_text()`, matching the semantic path behavior.

#### Scenario: Recursive path with use_hyperlinks=False

- **WHEN** a document is processed with `engine_type="recursive"` and `use_hyperlinks=False`
- **THEN** the text sent to the embedder SHALL be `build_augmented_text(chunk_info)`
- **AND** NOT raw `chunk_info["content"]`

#### Scenario: Recursive path with use_hyperlinks=True

- **WHEN** a document is processed with `engine_type="recursive"` and `use_hyperlinks=True`
- **THEN** behavior is unchanged: uses `build_augmented_text_with_links()`

### Requirement: Fix internal link target content resolution

The system SHALL correctly resolve internal link target content in augmented text by fixing the type mismatch between `str` keys and `int` lookup values in the `link_target_contents` dictionary.

#### Scenario: Internal link target content appears in augmented text

- **WHEN** a chunk has an internal link to another chunk
- **AND** `use_hyperlinks=True` during processing
- **THEN** the "Links To:" block in the augmented text SHALL contain the target chunk's content excerpt
- **AND** NOT fall back to the URI placeholder

#### Scenario: External links unaffected

- **WHEN** a link is of type `external`
- **THEN** behavior is unchanged (external URI is used in "Links To:" block)
