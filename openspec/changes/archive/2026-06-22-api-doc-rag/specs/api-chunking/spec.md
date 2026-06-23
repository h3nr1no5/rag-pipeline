## ADDED Requirements

### Requirement: Build parent-child chunk graph
The system SHALL convert structured COM domain objects into a directed acyclic graph of text chunks with explicit parent→child relationships. The graph MUST support:

- **Interface-level** chunks: full interface definition
- **Method-level** chunks: individual function/method with its parameters
- **Property-level** chunks: individual property
- **Parameter-level** chunks: individual parameter
- **Enum-level** chunks: full enum with values
- **Error-code-level** chunks: individual error code
- **Section-level** chunks: free-form prose sections

The hierarchy MUST be: Interface → {Method, Property, Enum} → Parameter.

#### Scenario: Interface chunk contains method children
- **WHEN** an `APIInterface` with 5 methods is chunked
- **THEN** the system produces 1 interface parent chunk + 5 method child chunks, each with a `parent_id` referencing the interface chunk

#### Scenario: Method chunk contains parameter children
- **WHEN** an `APIFunction` with 3 parameters is chunked
- **THEN** the system produces 1 method chunk + 3 parameter leaf chunks, each parameter chunk having a `parent_id` referencing the method chunk

### Requirement: Store chunk metadata
Each chunk SHALL store metadata including:
- `chunk_id`: unique identifier (UUID)
- `parent_id`: ID of parent chunk (null for root/interface chunks)
- `child_ids`: list of child chunk IDs
- `kind`: chunk type (interface, method, property, parameter, enum, enum_value, error_code, section)
- `level`: depth in graph (0=interface, 1=method/property/enum, 2=parameter)
- `source_doc`: source DOCX filename
- `interface_name`: containing interface name (if applicable)
- `function_name`: containing function name (if applicable)

#### Scenario: Chunk metadata is queryable
- **WHEN** a query requests all children of a specific chunk
- **THEN** the system returns all chunks whose `parent_id` matches the given `chunk_id`

### Requirement: Serialize and persist chunk graph
The system SHALL serialize the chunk graph to JSON for persistence alongside the FAISS vector index and BM25 index.

#### Scenario: Chunk graph survives restart
- **WHEN** the application restarts
- **THEN** the chunk graph is loaded from serialized JSON and all parent-child relationships are intact
