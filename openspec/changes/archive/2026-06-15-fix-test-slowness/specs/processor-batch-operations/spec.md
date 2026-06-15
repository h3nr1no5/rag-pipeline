## ADDED Requirements

### Requirement: Batch DB commits in chunk saving loop
The document processor SHALL NOT call `await session.commit()` inside the per-chunk loop for individual chunk saves. Instead, all chunk insertions and updates SHALL be accumulated in the session and flushed with a single commit after the loop completes.

This applies to both chunk processing paths:
- **Semantic chunk path** (processor.py, `strategy_name == "semantic"` block): Remove commits at the equivalent of lines 261 and 273 (per-chunk commits in semantic path)
- **Regular chunk path** (processor.py, standard recursive chunking block): Remove commits at lines 383 and 402 (per-chunk save and per-chunk update commits)

Progress-update commits (every 10 chunks, lines 414) and the final status commit SHALL be preserved.

#### Scenario: Chunks inserted in single transaction
- **WHEN** the processor saves chunks for a document
- **THEN** all chunk insertions SHALL be flushed to the database in a single `await session.commit()` call after the loop
- **AND** the number of `session.commit()` calls for chunk operations SHALL NOT exceed 3 total (one progress commit + one optional mid-progress commit + one final status commit)

#### Scenario: Transaction rollback on processing failure
- **WHEN** the processor crashes mid-loop (e.g., embedding fails)
- **THEN** no partial chunks SHALL be persisted (rollback behavior — same as current behavior without savepoints)

#### Scenario: Progress commits preserved for UI feedback
- **WHEN** the processor has saved every 10 chunks
- **THEN** a progress update SHALL still be committed to the database
- **AND** the `saved_chunks` counter on the Document SHALL be updated

### Requirement: Batch embedding with embed_texts
The document processor SHALL use `embedder.embed_texts()` to generate embeddings for all chunks in a single batch call, rather than calling `embedder.embed_text()` per chunk. The `embed_texts` method already exists on the `EmbedderService` interface and supports batch encoding.

#### Scenario: All chunk embeddings computed in one call
- **WHEN** the processor generates embeddings for document chunks
- **THEN** `embedder.embed_texts()` SHALL be called once with a list of all chunk texts
- **AND** the number of `embed_text`/`embed_texts` calls SHALL be exactly 1 for the batch

#### Scenario: Batch embedding error handling
- **WHEN** the batch `embed_texts()` call raises an exception
- **THEN** the processor SHALL log a warning and continue without embeddings (as currently done per-chunk)
- **AND** the document SHALL still be processed and saved
