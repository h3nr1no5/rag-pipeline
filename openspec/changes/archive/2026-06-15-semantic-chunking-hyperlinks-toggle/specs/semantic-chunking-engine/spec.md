## ADDED Requirements

### Requirement: Configurable hyperlink handling via `use_hyperlinks`

The `ChunkingStrategy` SHALL expose a `use_hyperlinks` boolean configuration that controls whether hyperlinks are considered during document processing and query-time retrieval. When disabled, the entire hyperlink pipeline (extraction, resolution, embedding augmentation, and query-time traversal) SHALL be skipped.

#### Scenario: Default is disabled

- **WHEN** a new `ChunkingStrategy` is created without specifying `use_hyperlinks`
- **THEN** the system SHALL default `use_hyperlinks` to `false`

#### Scenario: Disabled hyperlinks skip link extraction

- **WHEN** a document is processed with a strategy where `use_hyperlinks=false`
- **THEN** the system SHALL NOT call `extract_links()` on the document parser
- **AND** SHALL NOT call `resolve_links()` on the chunk data
- **AND** chunks SHALL NOT have `links` or `backlinks` metadata populated

#### Scenario: Disabled hyperlinks skip link-aware embedding augmentation

- **WHEN** a chunk's embedding is computed and the strategy has `use_hyperlinks=false`
- **THEN** the system SHALL use `build_augmented_text()` (COM prefix, section hierarchy, element type) for embedding
- **AND** SHALL NOT call `build_augmented_text_with_links()`
- **AND** no "Links To:" or "Referenced From:" context SHALL be injected into the embedding text

#### Scenario: Disabled hyperlinks force query-time traversal off

- **WHEN** a query targets documents whose strategy has `use_hyperlinks=false`
- **THEN** the system SHALL force `link_decay_factor=0` for the query, regardless of the request parameter
- **AND** SHALL NOT expand retrieval results via link traversal

#### Scenario: Enabled hyperlinks use current behavior

- **WHEN** a document is processed with a strategy where `use_hyperlinks=true`
- **THEN** the system SHALL extract links, resolve them to chunks, include link context in embedding augmentation, and perform query-time link traversal per the existing requirements in the Link Extraction and Link Traversal specs

## MODIFIED Requirements

### Requirement: Embedding augmentation via metadata prefix

The system SHALL support augmenting chunk content before embedding by prepending a domain-specific prefix, to improve retrieval relevance without altering stored chunk content. For COM-enriched chunks, the prefix SHALL include the element type, interface, and element name for optimal retrieval. The prefix SHALL include resolved link target summaries only when the strategy has `use_hyperlinks=true` and link metadata is available.

#### Scenario: Augment COM-enriched chunks with domain-specific prefix

- **WHEN** a chunk has COM enrichment metadata (interface, element_type, element_name)
- **THEN** the embedder SHALL receive a domain-specific prefix:
  - For functions: `"COM API Function: {interface}.{element_name}"`
  - For properties: `"COM API Property: {interface}.{element_name}"`
  - For enums: `"COM API Enum: {element_name}"`
  - For records: `"COM API Record: {element_name}"`
  - For error codes: `"COM API Error Code: {interface}"`
- **AND** the original content in the database SHALL remain unaltered
- **AND** only the augmented version SHALL be used for embedding computation
- **AND** the augmented text SHALL be:
  ```
  COM API Function: IAxisVMApplication.BringToFront
  Interface: IAxisVMApplication
  Section: Functions
  Element Type: function
  Element Name: BringToFront

  long BringToFront()

  Bring AxisVM window to front.
  Returns 1 if successful, 0 otherwise.
  ```

#### Scenario: Augment non-COM chunks with generic section hierarchy

- **WHEN** a chunk does not have COM enrichment but has a non-empty `section_hierarchy`
- **THEN** the embedder SHALL receive: `"[Section: <hierarchy joined by ' > '>]\n<original content>"`
- **AND** the original content SHALL remain unaltered

#### Scenario: Augment with element type when no hierarchy exists

- **WHEN** a chunk has no COM enrichment and empty `section_hierarchy` but a non-empty `element_type`
- **THEN** the embedder SHALL receive: `"[{element_type}]\n<original content>"`
- **WHEN** both hierarchy and type are empty
- **THEN** the original content SHALL be embedded as-is, without prefix

#### Scenario: Augment with link context when link metadata is present and hyperlinks are enabled

- **WHEN** a chunk has non-empty `links` or `backlinks` in `chunk_metadata`
- **AND** the document's strategy has `use_hyperlinks=true`
- **THEN** the augmented text SHALL additionally include a link context block appended after the existing prefix and before the original content, formatted as:
  ```
  Links To:
  - <summary of target chunk content> (type: internal|external)

  Referenced From:
  - <summary of source chunk content>
  ```
- **AND** each link target summary SHALL be limited to 150 characters
- **AND** the augmentation SHALL cap at 3 outgoing links and 3 backlinks (whichever is fewer, most relevant first)
- **AND** SHALL skip external URIs (they have no chunk content to summarize)
- **AND** the original chunk content in the database SHALL remain unaltered
- **AND** only the augmented version SHALL be used for embedding computation
- **WHEN** a chunk has non-empty `links` or `backlinks` but the strategy has `use_hyperlinks=false`
- **THEN** the augmented text SHALL NOT include link context
- **AND** SHALL use the standard `build_augmented_text()` behavior

#### Scenario: Graceful degradation when link target chunks are missing

- **WHEN** a link's `target_chunk_ids` references a chunk ID that no longer exists in the database
- **AND** `use_hyperlinks=true`
- **THEN** the augmentation SHALL include the text `"[deleted chunk]"` as the summary for that link
- **AND** SHALL NOT error or halt augmentation
