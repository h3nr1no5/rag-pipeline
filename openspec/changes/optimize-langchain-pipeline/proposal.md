## Why

The LangChain RAG pipeline takes 5+ minutes per query due to an oversized candidate pool feeding the cross-encoder re-ranker. Combined with missing error handling for transport failures, users see a generic "Unable to process request" error rendered as a normal chat message — no feedback about the timeout or what went wrong.

## What Changes

- Reduce the candidate pool fed to the cross-encoder from ~66 docs to ~30 docs by lowering `internal_top_k` from 20 to 10 (BM25 and FAISS `k` drop from 40 to 20 each)
- Add `"error"` key in all 4 frontend query functions' exception handlers so the Chat page can render errors via `st.error()` instead of as normal assistant messages
- Handle timeout responses gracefully: show a clear "query took too long" message instead of a generic error

## Capabilities

### New Capabilities
- `langchain-pipeline-optimization`: Reduced candidate pool for the LangChain RAG hybrid retrieval pipeline
- `query-error-handling`: Proper error key propagation in frontend query functions with user-friendly timeout/transport error messages

### Modified Capabilities
- *(none — no existing specs to modify)*

## Impact

- **Performance**: LangChain query time reduced from ~317s to ~150-170s (halving the candidate pool from 66 to ~30 docs reduces cross-encoder scoring from 3 batches to 1-2)
- **Frontend**: Error messages now render via `st.error()` with a clear "chat bubble" failure state; timeout errors show a specific message suggesting retry
- **No timeout increase**: 180s frontend timeout stays — the pipeline must complete within it
- **Dependencies**: No new Python packages needed
- **Code**: Changes constrained to `src/domain/services/retrieval_langchain.py` (`internal_top_k`, BM25/FAISS `k` values), `client/utils/query.py` (error key in exception handlers), `client/pages/3_💬_Chat.py` (render the new error state), and `src/api/routes/query/routes.py` (backend timeout)
