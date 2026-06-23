## ADDED Requirements

### Requirement: Hybrid BM25 + embedding retrieval
The system SHALL implement a hybrid retriever that combines:
1. **BM25 retrieval** over function names, parameter names, type names, and error code names (exact keyword match)
2. **Embedding similarity retrieval** over chunk text content (semantic match) using the shared `SentenceTransformerEmbedder` (all-mpnet-base-v2, 768d)
3. **RRF (Reciprocal Rank Fusion)** to merge results from both retrievers into a single ranked list

The retriever SHALL convert all queries to lowercase for BM25 matching but preserve original case in result display.

#### Scenario: Exact keyword match dominates
- **WHEN** a user queries "CreateUser"
- **THEN** BM25 ranks the `CreateUser` method chunk at position 1, even if embedding similarity gives it a lower initial rank

#### Scenario: Semantic match fills gaps
- **WHEN** a user queries "how to make a new node in the model"
- **THEN** embedding similarity ranks `AddNode` highly (semantic meaning of "make new node"), even though the query contains no exact function name

#### Scenario: RRF fusion produces combined results
- **WHEN** BM25 and embedding retrievers return overlapping and non-overlapping results
- **THEN** RRF produces a single ranked list with `k=60` fusion constant

### Requirement: Link traversal for cross-references
The system SHALL detect cross-references between COM types (e.g., "See INode" in method docs, or parameter type is another interface). When a chunk is retrieved that references another type, the system MUST append the referenced type's parent chunk to the result set.

#### Scenario: Follow type reference in parameter
- **WHEN** a query matches a function whose parameter type is `INode`
- **THEN** the system includes the `INode` interface chunk in the result set alongside the function chunk

#### Scenario: Avoid infinite reference loops
- **WHEN** two interfaces reference each other (circular reference)
- **THEN** the system limits link traversal to a maximum depth of 2 and tracks visited chunk IDs to avoid duplicates

### Requirement: Chunk parent expansion
When a child chunk (parameter-level or method-level) is retrieved, the system SHALL also include its parent chunk (method-level or interface-level) in the result set, up to a configurable `max_parents` depth (default: 2).

#### Scenario: Parameter retrieval includes parent method
- **WHEN** a specific parameter chunk is matched by BM25
- **THEN** the result set includes both the parameter chunk and its parent method chunk
