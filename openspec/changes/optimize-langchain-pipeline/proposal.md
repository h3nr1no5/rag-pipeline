## Why

The LangChain RAG pipeline takes 5+ minutes per query due to an oversized cross-encoder model and excessive candidate processing. Combined with missing error handling for transport failures, users see a generic "Unable to process request" error rendered as a normal chat message — no feedback about the timeout or what went wrong.

## What Changes

- Replace `Alibaba-NLP/gte-reranker-modernbert-base` cross-encoder with `cross-encoder/ms-marco-MiniLM-L-6-v2` (~22M params vs ~395M) for 10-20x faster re-ranking
- Reduce the candidate pool fed to the cross-encoder from ~66 docs to ~30 docs by lowering `internal_top_k` from 20 to 10
- Add `"error"` key in all 4 frontend query functions' exception handlers so the Chat page can render errors via `st.error()` instead of as normal assistant messages
- Handle timeout responses gracefully: show a clear "query took too long" message instead of a generic error

## Capabilities

### New Capabilities
- `langchain-pipeline-optimization`: Faster cross-encoder model and reduced candidate pool for the LangChain RAG pipeline
- `query-error-handling`: Proper error key propagation in frontend query functions with user-friendly timeout/transport error messages

### Modified Capabilities
- *(none — no existing specs to modify)*

## Impact

- **Performance**: LangChain query time reduced from ~317s to ~20-30s (cross-encoder alone drops from 307s to ~10-15s)
- **Frontend**: Error messages now render via `st.error()` with a clear "chat bubble" failure state; timeout errors show a specific message suggesting retry
- **No timeout increase**: 180s frontend timeout stays — the pipeline must complete within it
- **Dependencies**: Cross-encoder model added to HuggingFace model cache; no new Python packages needed
- **Code**: Changes constrained to `src/domain/services/retrieval_langchain.py` (model name, `internal_top_k`), `client/utils/query.py` (error key in exception handlers), and `client/pages/3_💬_Chat.py` (render the new error state)
