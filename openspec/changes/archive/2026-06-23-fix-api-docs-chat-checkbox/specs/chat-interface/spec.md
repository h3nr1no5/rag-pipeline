## ADDED Requirements

### Requirement: RAG backend selection respects document engine type

The Chat page SHALL show the API Docs RAG backend checkbox when the user selects a document with `engine_type == "api-docs"`. When all selected documents are of type api-docs, the three main RAG backends (Cosine Similarity, LangChain, LlamaIndex) SHALL be disabled with a tooltip explaining they are not available for API documentation documents. When a mix of api-docs and regular documents is selected, all four backends SHALL remain enabled.

#### Scenario: API Docs checkbox appears for api-docs document
- **WHEN** the user selects a document processed with the api-docs engine type
- **THEN** the "🔶 API Docs" checkbox appears in the sidebar

#### Scenario: Main RAGs disabled for api-docs-only selection
- **WHEN** all selected documents have `engine_type == "api-docs"`
- **THEN** the Cosine Sim, LangChain, and LlamaIndex checkboxes are disabled with a tooltip explaining their unavailability

#### Scenario: All backends enabled for mixed selection
- **WHEN** the user selects both an api-docs document and a regular document
- **THEN** all four RAG backend checkboxes (Cosine, LangChain, LlamaIndex, API Docs) are enabled

#### Scenario: Main RAGs not sent to backend when disabled
- **WHEN** all selected documents are api-docs type and a query is submitted
- **THEN** no query request is sent to the `/api/v1/query`, `/api/v1/query/langchain`, or `/api/v1/query/llamaindex` endpoints (only `/api/v1/query/api-docs` is called)
