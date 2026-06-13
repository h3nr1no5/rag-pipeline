# Link Extraction

## Purpose

Extract hyperlinks from PDF and DOCX documents during parsing, converting page-based links (page refs, named destinations, URIs) into structured link metadata attached to source pages. Provides the raw link data needed for downstream resolution, augmentation, and traversal.

## ADDED Requirements

### Requirement: Extract PDF hyperlinks from page annotations

The PDF parser SHALL extract all hyperlinks from each page using PyMuPDF's `page.get_links()` method, capturing internal page references, named destinations, and external URIs.

#### Scenario: Extract internal page references

- **WHEN** a PDF page contains a link with `kind == fitz.LINK_GOTO` pointing to a target page number
- **THEN** the parser SHALL record a `LinkInfo` entry with `type: "internal"`, `source_page: <page_num>`, `target_page: <target_page>`, and `uri: null`
- **AND** SHALL record the link's bounding rectangle (`bbox`) if available

#### Scenario: Extract external URIs

- **WHEN** a PDF page contains a link with `kind == fitz.LINK_URI`
- **THEN** the parser SHALL record a `LinkInfo` entry with `type: "external"`, `uri: <the URL>`, `source_page: <page_num>`, and `target_page: null`

#### Scenario: Extract named destinations

- **WHEN** a PDF page contains a link with `kind == fitz.LINK_GOTO` and a named destination (string name instead of page number)
- **THEN** the parser SHALL resolve the named destination via `doc.resolve_link()` to obtain the target page number
- **AND** SHALL record a `LinkInfo` entry with `type: "internal"`, the resolved `target_page: <page_num>`, and `named_dest: "<name>"`

#### Scenario: Skip unsupported link types

- **WHEN** a PDF page contains a link with `kind == fitz.LINK_LAUNCH` or `kind == fitz.LINK_FILE` or other non-standard link type
- **THEN** the parser SHALL skip the link with a debug-level log message
- **AND** SHALL NOT error or halt extraction

### Requirement: Extract DOCX external hyperlinks

The DOCX parser SHALL extract external hyperlinks from paragraph-level `hyperlink` elements in the OpenXML document.

#### Scenario: Extract hyperlinks from DOCX paragraphs

- **WHEN** a DOCX paragraph contains one or more `hyperlink` child elements (as `run.hyperlink` in python-docx)
- **THEN** the parser SHALL record a `LinkInfo` entry per hyperlink with `type: "external"`, `uri: <resolved URL>`, and `source_page: null`
- **AND** SHALL resolve relative URIs using the document's relationship parts (`doc.part.rels`)

#### Scenario: Handle DOCX documents with no hyperlinks

- **WHEN** a DOCX document has no hyperlinks in any paragraph
- **THEN** the parser SHALL return an empty list from `extract_links()`

#### Scenario: Gracefully skip malformed DOCX hyperlinks

- **WHEN** a DOCX hyperlink element lacks a valid relationship ID or the relationship target is unreadable
- **THEN** the parser SHALL skip that hyperlink with a warning-level log message
- **AND** SHALL continue extracting other hyperlinks from the same paragraph

### Requirement: Provide `LinkInfo` data structure for extracted links

The extraction system SHALL use a standard `LinkInfo` data structure (dataclass or TypedDict) for all extracted links, enabling downstream consumers to process links uniformly regardless of source format.

#### Scenario: LinkInfo contains standard fields

- **WHEN** any parser extracts a link
- **THEN** the resulting `LinkInfo` SHALL contain these fields:

| Field | Type | Description |
|-------|------|-------------|
| `type` | `Literal["internal", "external"]` | Whether the link points to another page in the same document or to an external URI |
| `source_page` | `int \| None` | 1-indexed page number where the link appears (None for DOCX) |
| `target_page` | `int \| None` | 1-indexed target page for internal links (None for external) |
| `uri` | `str \| None` | External URI for external links (None for internal) |
| `named_dest` | `str \| None` | PDF named destination name (None for external or direct page refs) |
| `bbox` | `tuple[float, float, float, float] \| None` | Link's bounding box in PDF point coordinates (None for DOCX) |
| `anchor_text` | `str \| None` | Extracted text content of the link region, when available (None if not extracted) |

### Requirement: Add `extract_links()` method to `DocumentParser` interface

The abstract `DocumentParser` base class SHALL define an optional `extract_links()` method returning `list[LinkInfo]`. Implementations that don't support link extraction SHALL return an empty list.

#### Scenario: extract_links() is additive and non-breaking

- **WHEN** a `DocumentParser` implementation does not override `extract_links()`
- **THEN** the base class SHALL provide a default implementation returning `[]`
- **AND** existing callers of `parse()` SHALL continue to work without modification
- **AND** `PDFParser` and `DocxParser` SHALL both override `extract_links()` with format-specific implementations

#### Scenario: TextParser and OpenAPIParser return empty link list

- **WHEN** `extract_links()` is called on a `TextParser` or `OpenAPIParser` instance
- **THEN** it SHALL return an empty list
- **AND** SHALL NOT attempt any file I/O or parsing
