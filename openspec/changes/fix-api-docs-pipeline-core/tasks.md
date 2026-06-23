## 1. Fix double format_graph in ApiEmbeddingIndex

- [ ] 1.1 Thread domain objects (interfaces, enums, error_codes) through `manager.ingest_docx()` → `retriever.ingest_graph()` → `embedding_index.add_graph()`
- [ ] 1.2 Update `HybridRetriever.ingest_graph()` signature to accept optional `interfaces`, `enums`, `error_codes` parameters
- [ ] 1.3 Update `ApiEmbeddingIndex.add_graph()` signature to accept optional domain objects and pass them to `text_formatter.format_graph(graph, interfaces, enums, error_codes)`
- [ ] 1.4 Verify PDF path (`ingest_pdf()`) passes `None` domain objects and gets the correct metadata-only fallback behavior
- [ ] 1.5 Verify `load_from_db()` path is not affected (uses stored content directly, does not call format_graph)

## 2. Fix LinkTraverser shared mutable state race

- [ ] 2.1 Move `_interface_name_to_id` from `self` attribute to a local variable inside `LinkTraverser.traverse()`
- [ ] 2.2 Verify that `traverse()` rebuilds the mapping on every call and does not leak state between concurrent invocations

## 3. Add cross-encoder reranking to HybridRetriever

- [ ] 3.1 Import `CrossEncoderReRanker` from `src.domain.services.retrieval_langchain` and expose `get_instance()`
- [ ] 3.2 Add `rerank_k` parameter to `HybridRetriever.__init__()` and `retrieve()` (default 20)
- [ ] 3.3 In `retrieve()`, insert reranking step after RRF fusion and before link traversal: take top `rerank_k` candidates, compute cross-encoder scores, re-sort, apply `min_relevance_score` filter
- [ ] 3.4 Normalize cross-encoder scores to [0, 1] via min-max and assign as each chunk's `score` (preserve original RRF score internally for debugging)
- [ ] 3.5 Add `rerank_k` parameter to `ApiDocQueryRequest` schema for user configurability
- [ ] 3.6 Thread `rerank_k` from route handler through `manager.query()` to `retriever.retrieve()`

## 4. Add response verification to manager._generate_answer()

- [ ] 4.1 Import `ResponseVerifier` from `src.domain.services.verification` and get shared instance
- [ ] 4.2 After `llm.generate()` in `_generate_answer()`, call `verifier.verify(answer, source_texts, threshold=settings.verification_similarity_threshold)`
- [ ] 4.3 If verification result `verified_text` is empty, return the fallback message: "I don't have enough information to answer this question."
- [ ] 4.4 If verification returns verified text, return it with any `unsupported_sentences` in response metadata
- [ ] 4.5 Respect `settings.verification_enabled` — skip verification when disabled

## 5. Fix error masking in query endpoint

- [ ] 5.1 Stop catching all `Exception` in `manager._generate_answer()` — only catch and log `ImportError` for missing LLM module
- [ ] 5.2 Let runtime exceptions (LLM failure, embedding failure, etc.) propagate naturally
- [ ] 5.3 Verify the existing `except Exception` in `routes.py` line 193 catches the propagated exception and returns HTTP 500 with an appropriate error message
- [ ] 5.4 Update error response body to include correlation details (e.g., request ID or document_id) for debugging

## 6. Write tests

- [ ] 6.1 Add unit test for `ApiEmbeddingIndex.add_graph()` — verify that content is NOT overwritten when domain objects are provided
- [ ] 6.2 Add unit test for `LinkTraverser.traverse()` — verify no state leaks between sequential calls with different documents
- [ ] 6.3 Add integration test for `/api/v1/query/api-docs` — verify answer generation returns non-empty response for a known DOCX document
- [ ] 6.4 Add integration test for API docs query with verification enabled — verify fallback message when LLM response has low relevance
- [ ] 6.5 Add integration test for API docs cross-encoder reranking — verify that reranked results preserve only chunks above the relevance threshold
