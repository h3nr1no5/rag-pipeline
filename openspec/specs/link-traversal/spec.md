# Link Traversal

## Purpose

Perform 1-hop link traversal at query time to expand retrieval results with structurally connected chunks — both chunks that the matched chunk links TO and chunks that link TO it (backlinks). Linked chunks receive a configurable score decay to preserve ranking order.

## Requirements

### Requirement: Perform 1-hop link traversal after cosine similarity retrieval

The query pipeline SHALL, after computing cosine similarity between query embedding and all chunk embeddings, expand the top-k results by following links and backlinks stored in `chunk_metadata`.

#### Scenario: Fetch linked chunks from forward links

- **WHEN** a chunk in the top-k results has `links` entries in `chunk_metadata` where `target_chunk_ids` is non-empty
- **THEN** the system SHALL fetch each chunk referenced by `target_chunk_ids` from the database
- **AND** SHALL add those chunks to the retrieval results with a decayed score

#### Scenario: Fetch backlinked chunks

- **WHEN** a chunk in the top-k results has `backlinks` entries in `chunk_metadata`
- **THEN** the system SHALL fetch each chunk identified by `source_chunk_id` in the backlinks from the database
- **AND** SHALL add those chunks to the retrieval results with a decayed score

#### Scenario: Deduplicate linked chunks

- **WHEN** a chunk is reachable via both direct cosine similarity AND link traversal
- **THEN** the system SHALL keep only one copy (the higher score — typically the direct match)
- **AND** SHALL NOT count it twice in the final result set

#### Scenario: Limit traversal to exactly 1 hop

- **WHEN** a linked chunk itself has its own forward links or backlinks
- **THEN** the system SHALL NOT follow those secondary links
- **AND** SHALL bound traversal depth to exactly 1 hop from the direct matches

### Requirement: Score decay for linked chunks

Linked chunks retrieved via traversal SHALL receive a decayed score relative to the chunk they were reached from. Direct cosine similarity scores SHALL remain unchanged.

#### Scenario: Apply default 0.85 decay factor

- **WHEN** a linked chunk is fetched via traversal from chunk C with cosine score S
- **THEN** the linked chunk's score SHALL be `S * 0.85`
- **AND** the score SHALL NOT exceed S

#### Scenario: Configurable decay factor

- **WHEN** the retrieval system exposes a `link_decay_factor` parameter
- **THEN** the default value SHALL be `0.85`
- **AND** setting it to `1.0` SHALL pass through the original score unchanged
- **AND** setting it to `0.0` SHALL effectively disable link traversal (results in score 0)

### Requirement: Maintain existing retrieval interface

The link traversal expansion SHALL integrate into the existing `retrieve_chunks()` function signature and response format without breaking existing callers.

#### Scenario: retrieve_chunks returns expanded results

- **WHEN** `retrieve_chunks()` is called with `top_k=K`
- **THEN** the function SHALL first retrieve K chunks by cosine similarity
- **THEN** SHALL expand via 1-hop traversal
- **THEN** SHALL return `min(expanded_count, top_k * link_expansion_factor)` results, where `link_expansion_factor` defaults to 2 but is configurable
- **AND** each result SHALL include the standard `RetrievedChunk` fields: `chunk` and `score`
- **AND** SHALL include an additional `retrieved_via` field with value `"cosine_similarity"` or `"link_traversal"`

#### Scenario: Backward compatibility with cached results

- **WHEN** a query is served from `QueryCache` and the cached `source_chunk_ids` do not include link-traversal results
- **THEN** the cache SHALL be invalidated for documents with link metadata (non-empty `links` or `backlinks` in any chunk) to ensure fresh results
- **AND** the cache key SHALL incorporate the `link_expansion_factor` and `link_decay_factor` parameters to key separate cache entries for different link settings
