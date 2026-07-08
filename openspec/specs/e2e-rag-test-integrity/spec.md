# E2E RAG Test Integrity

## Purpose

Ensure slow E2E tests verify that RAG pipeline answers contain meaningful content from uploaded documents, use a realistic LLM double that extracts source text from prompts, and properly signal auth failures in the frontend.

## Requirements

### Requirement: Slow E2E tests SHALL verify answers contain document content

The 4 `@pytest.mark.slow` E2E tests SHALL verify the RAG pipeline answer contains meaningful content from the uploaded document, not just that the answer is non-empty. The tests SHALL use a `RealisticTestLLM` double that extracts document source text from the prompt and incorporates it into the response, thereby verifying that retrieval → prompt assembly → LLM coupling is functional.

#### Scenario: Cosine pipeline answer references document content
- **WHEN** `test_pdf.pdf` is uploaded with `recursive` chunking strategy
- **AND** processing completes successfully
- **AND** a query is sent to `POST /api/v1/query` with question "how to add material?"
- **THEN** the response status SHALL be 200
- **AND** the response SHALL contain an `answer` field
- **AND** `result["answer"]` SHALL NOT equal the generic `TestLLM` canned response
- **AND** `result["answer"]` SHALL contain the word "material" (a key term from the document)

#### Scenario: LangChain pipeline answer references document content
- **WHEN** the same chunked document from the cosine test is used
- **AND** a query is sent to `POST /api/v1/query/langchain` with question "how to add material?"
- **THEN** the response status SHALL be 200
- **AND** the response SHALL contain an `answer` field
- **AND** `result["answer"]` SHALL NOT equal the generic `TestLLM` canned response
- **AND** `result["answer"]` SHALL contain the word "material"

#### Scenario: LlamaIndex pipeline answer references document content
- **WHEN** the same chunked document from the cosine test is used
- **AND** a query is sent to `POST /api/v1/query/llamaindex` with question "how to add material?"
- **THEN** the response status SHALL be 200
- **AND** the response SHALL contain an `answer` field
- **AND** `result["answer"]` SHALL NOT equal the generic `TestLLM` canned response
- **AND** `result["answer"]` SHALL contain the word "material"

#### Scenario: API Docs pipeline answer is not a fallback
- **WHEN** `test docx.docx` is uploaded with `api-docs` chunking strategy
- **AND** processing completes successfully
- **AND** a query is sent to `POST /api/v1/query` with question "how to add material?" and the API doc document ID
- **THEN** the response status SHALL be 200
- **AND** the response SHALL contain a non-empty `answer` field
- **AND** `result["answer"]` SHALL NOT equal `"I don't have enough information to answer this question."`

### Requirement: Slow E2E tests SHALL NOT use the session-scoped TestLLM

The `@pytest.mark.slow` E2E tests SHALL NOT be affected by the `seed_singletons` fixture in `tests/integration/conftest.py`. The test module SHALL reseed the LLM singleton with `RealisticTestLLM` at module level so that the E2E tests use a realistic LLM double that responds about document content.

#### Scenario: RealisticTestLLM replaces TestLLM for slow tests
- **WHEN** a `@pytest.mark.slow` E2E test in `test_rag_pipelines_e2e.py` starts
- **THEN** `get_llm()` SHALL return a `RealisticTestLLM` instance (not `TestLLM`)
- **AND** `RealisticTestLLM.generate()` SHALL parse the prompt for `[Source N]:` sections
- **AND** `RealisticTestLLM.generate()` SHALL return a response containing text from the first source when sources are present
- **AND** `RealisticTestLLM.generate()` SHALL return `"I don't have enough information to answer this question."` when no sources are found

### Requirement: Frontend SHALL visibly signal auth failure

The `client/utils/query.py` helper functions SHALL NOT silently return a fake answer when the user is not authenticated. When `st.session_state.get("token")` is falsy, the helper SHALL return a result dict with an `"error"` key set to `"not_authenticated"` that the Streamlit chat page can detect and display as an error message.

#### Scenario: No token in session state
- **WHEN** `query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()`, or `api_docs_query()` is called
- **AND** `st.session_state.get("token")` is falsy
- **THEN** the function SHALL return a dict with `"answer"` and `"error": "not_authenticated"`
- **AND** `client/pages/3_💬_Chat.py` SHALL check for `"error"` in the result and call `st.error()` if present
