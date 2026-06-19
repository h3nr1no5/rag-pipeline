# Citation Toggle — Frontend

## Purpose

The Streamlit chat sidebar exposes a "Show Citations" checkbox that controls the `include_citations` parameter sent to the RAG backend API, and persists this setting across sessions via `chat_params.json`. This gives users control over whether `[Source N]` citations appear inline in responses.

## Requirements

### Requirement: User can toggle citations from the chat sidebar

The Streamlit chat UI SHALL expose a checkbox in the sidebar Parameters section that controls the `include_citations` setting sent to the backend API.

#### Scenario: Checkbox displayed in Parameters section

- **WHEN** a user opens the chat page
- **THEN** the sidebar SHALL display a checkbox labeled "Show Citations" under the Parameters section
- **AND** the checkbox SHALL be checked by default

#### Scenario: Toggle affects API requests

- **WHEN** a user unchecks the "Show Citations" checkbox
- **AND** submits a query
- **THEN** the request to the backend SHALL include `"include_citations": false`
- **AND** the response SHALL NOT contain `[Source N]` citations inline

#### Scenario: Toggle affects all three RAG backends

- **WHEN** a user submits a query with citations unchecked
- **THEN** all three enabled RAG backends (cosine, LangChain, LlamaIndex) SHALL receive `include_citations=false`
- **AND** all responses SHALL omit `[Source N]` citations

### Requirement: Citation toggle is persisted between sessions

The `include_citations` value SHALL be saved to `chat_params.json` when the user clicks "Save Parameters", and restored on page load.

#### Scenario: Setting saved on save

- **WHEN** a user changes the "Show Citations" checkbox
- **AND** clicks "Save Parameters"
- **THEN** the `chat_params.json` file SHALL contain `"include_citations": <value>`

#### Scenario: Setting restored on load

- **WHEN** a user returns to the chat page
- **THEN** the "Show Citations" checkbox SHALL reflect the saved value from `chat_params.json`
- **AND** default to `true` if no saved value exists
