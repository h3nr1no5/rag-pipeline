# Semantic Chunking Engine — Link-Aware Delta

## MODIFIED Requirements

### Requirement: Embedding augmentation via metadata prefix

The system SHALL support augmenting chunk content before embedding by prepending a domain-specific prefix, to improve retrieval relevance without altering stored chunk content. For COM-enriched chunks, the prefix SHALL include the element type, interface, and element name for optimal retrieval. The prefix MAY additionally include resolved link target summaries when link metadata is available.

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

#### Scenario: Augment with link context when link metadata is present

- **WHEN** a chunk has non-empty `links` or `backlinks` in `chunk_metadata`
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

#### Scenario: Graceful degradation when link target chunks are missing

- **WHEN** a link's `target_chunk_ids` references a chunk ID that no longer exists in the database
- **THEN** the augmentation SHALL include the text `"[deleted chunk]"` as the summary for that link
- **AND** SHALL NOT error or halt augmentation
