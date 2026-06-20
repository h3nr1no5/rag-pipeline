## ADDED Requirements

### Requirement: Per-stage progress model

The system SHALL track document processing progress independently for each pipeline stage. The three stages and their lifecycle SHALL be:

| Stage | API field | Progress behavior | Max |
|-------|-----------|-------------------|-----|
| Parsing | `parsing_progress` | 0 during parsing, jumps to 100 when parsing completes | 100 |
| Chunking | `chunking_progress` | 0 during chunking, jumps to 100 when chunking completes | 100 |
| Saving | `saving_progress` | 0 before saving starts, increments per chunk during saving, reaches 100 on completion | 100 |

Each stage SHALL transition through three states: `waiting` → `in_progress` → `completed` (or `failed` for the active stage).

#### Scenario: All stages waiting at document creation

- **WHEN** a document is first uploaded and has status `pending`
- **THEN** `parsing_progress` SHALL be 0, `chunking_progress` SHALL be 0, `saving_progress` SHALL be 0

#### Scenario: Only parsing stage advances during parsing

- **WHEN** the processor enters the `parsing` step
- **THEN** `parsing_progress` SHALL be 0 (before actually parsing)
- **AND** `chunking_progress` SHALL remain at 0
- **AND** `saving_progress` SHALL remain at 0
- **AND** when parsing completes, `parsing_progress` SHALL become 100

#### Scenario: Only chunking stage advances during chunking

- **WHEN** the processor enters the `chunking` step
- **THEN** `parsing_progress` SHALL be 100 (parsing completed)
- **AND** `chunking_progress` SHALL be 0 (before actually chunking)
- **AND** `saving_progress` SHALL remain at 0
- **AND** when chunking completes, `chunking_progress` SHALL become 100

#### Scenario: Saving stage increments per chunk

- **WHEN** the processor enters the `saving` step with a known total chunk count of N
- **THEN** `parsing_progress` SHALL be 100, `chunking_progress` SHALL be 100, `saving_progress` SHALL be 0
- **AND** after saving chunk i of N, `saving_progress` SHALL equal `int(100 * (i+1) / N)`

#### Scenario: Failed stage resets

- **WHEN** processing fails during the `saving` step
- **THEN** the active stage (`saving_progress`) SHALL be 0
- **AND** previously completed stages SHALL retain their `100` values (parsing, chunking remain at 100)

#### Scenario: All stages complete

- **WHEN** a document's status is `completed`
- **THEN** `parsing_progress` SHALL be 100, `chunking_progress` SHALL be 100, `saving_progress` SHALL be 100

### Requirement: API exposes per-stage progress

The system SHALL expose per-stage progress fields (`parsing_progress`, `chunking_progress`, `saving_progress`) in the document status and document list API responses.

#### Scenario: Document status endpoint returns per-stage progress

- **WHEN** a client calls `GET /api/v1/documents/{id}/status`
- **THEN** the response body SHALL include `parsing_progress`, `chunking_progress`, and `saving_progress` fields (each 0–100)
- **AND** the response SHALL include a `stage_detail` field with the current stage's sub-message (e.g., `"Saving chunk 12/42"`)

#### Scenario: Document list endpoint returns per-stage progress

- **WHEN** a client calls `GET /api/v1/documents/`
- **THEN** each document object in the response SHALL include `parsing_progress`, `chunking_progress`, and `saving_progress` fields

### Requirement: Document list per-stage progress bars

The document list page SHALL display three independent progress bars for documents whose status is `processing`. Each processing row SHALL show:
- A compact triple-bar layout: one bar per stage, labeled with stage name and emoji
- The active stage's bar SHALL be animated or highlighted
- Completed stage bars SHALL show a checkmark or green fill
- Waiting stage bars SHALL show an empty/gray bar

#### Scenario: Per-stage bars shown for processing documents

- **WHEN** the document list loads and a document has status `processing`
- **THEN** the row SHALL display three sequential progress bars labeled:
  - `📄 Parsing` with `parsing_progress` value
  - `✂️ Chunking` with `chunking_progress` value
  - `🧠 Embed + Save` with `saving_progress` value
- **AND** the active stage (the one currently `in_progress`) SHALL be visually emphasized

#### Scenario: Saving stage shows chunk detail

- **WHEN** a document is in the `saving` step with `saving_progress` at 30% and chunk detail "12/42"
- **THEN** the saving bar SHALL display the text `12/42 chunks` alongside the bar

#### Scenario: Auto-polling during processing

- **WHEN** at least one document in the list has status `processing`
- **THEN** the page SHALL auto-refresh every 3 seconds to update per-stage progress bars
- **AND** when no documents have status `processing`, auto-refresh SHALL stop

#### Scenario: Completed document shows all-done state

- **WHEN** a document's status transitions from `processing` to `completed`
- **THEN** all three progress bars SHALL be shown at 100% with green styling
- **AND** after a brief transition, the bars SHALL collapse back to the standard "✅ Completed" badge

### Requirement: Upload flow uses per-stage progress bars

The post-upload progress display SHALL show per-stage progress bars instead of a single combined bar.

#### Scenario: Upload progress shows per-stage bars

- **WHEN** a user uploads a document and the processing begins
- **THEN** the progress display SHALL show three sequential bars (parsing, chunking, embed+save) that update independently
- **AND** the display SHALL show the current stage detail during saving (e.g., "Saving chunk 12/42")

#### Scenario: Upload flow shows parsing as indeterminate

- **WHEN** a document is being parsed
- **THEN** the parsing bar SHALL show an animated/indeterminate state (since parsing has no sub-steps to measure)
- **AND** the parsing bar SHALL snap to 100% when parsing completes

### Requirement: Chat page processing warning with per-stage detail

The Chat page SHALL display a non-blocking warning banner when selected documents are still processing. The banner SHALL show per-stage progress for each processing document.

#### Scenario: Warning shown with per-stage progress

- **WHEN** a user selects documents and at least one has status `processing`
- **THEN** a warning banner SHALL appear above the chat area
- **AND** the banner SHALL list each processing document with a compact per-stage progress summary (e.g., `Parsing ✅ Chunking 🔄 60% Saving ⏳`)
- **AND** the chat input SHALL remain usable

#### Scenario: Warning updates as stages complete

- **WHEN** a document transitions from chunking to saving
- **THEN** the warning banner SHALL update to show chunking at 100% and saving as the active stage
- **AND** when all selected documents are completed, the banner SHALL be removed entirely
