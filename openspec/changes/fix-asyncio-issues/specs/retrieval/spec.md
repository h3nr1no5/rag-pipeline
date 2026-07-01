# Retrieval — Delta Spec

## MODIFIED Requirements

### Requirement: CustomEnsembleRetriever SHALL raise error instead of silent empty return

The `CustomEnsembleRetriever._get_relevant_documents()` method SHALL raise a `RuntimeError` when called from a context with a running event loop, instead of silently returning an empty list.

**Rationale**: The synchronous `_get_relevant_documents()` method is only provided for LangChain's interface compatibility. The correct usage is the async `_aget_relevant_documents()` method. Returning `[]` silently hides bugs — callers receive empty results without any indication of misuse.

#### Scenario: Called from running event loop raises error
- **WHEN** `_get_relevant_documents()` is called
- **AND** `asyncio.get_event_loop().is_running()` returns `True`
- **THEN** the method SHALL raise `RuntimeError("CustomEnsembleRetriever must be used with async methods only")`
- **AND** SHALL NOT return an empty list

#### Scenario: Called from non-running event loop
- **WHEN** `_get_relevant_documents()` is called
- **AND** no event loop is running
- **THEN** the method SHALL fall back to `loop.run_until_complete(self._aget_relevant_documents(query, k))` (existing behavior, unchanged)

#### Scenario: Called without a running loop
- **WHEN** `_get_relevant_documents()` is called
- **AND** there is no current event loop (`RuntimeError` from `get_event_loop()`)
- **THEN** the method SHALL raise the original exception
- **AND** SHALL NOT silently return an empty list
