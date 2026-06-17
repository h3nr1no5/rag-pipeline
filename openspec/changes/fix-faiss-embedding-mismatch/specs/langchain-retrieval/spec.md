## ADDED Requirements

### Requirement: FAISS query embedding MUST use the project's SentenceTransformerEmbedder

The LangChain hybrid retriever SHALL use the project's `SentenceTransformerEmbedder` (via `get_embedder()` from `domain/services/embedding.py`) for FAISS query encoding, instead of creating a separate `HuggingFaceEmbeddings` instance. This ensures query embeddings match the stored embedding vector space.

#### Scenario: FAISS query returns same chunks as cosine path for identical query
- **WHEN** a query is executed through the LangChain hybrid retriever
- **THEN** the top-5 FAISS results SHALL contain the same chunks as the top-5 cosine similarity results for the same query and document set

#### Scenario: Embedding function is lazy-loaded singleton
- **WHEN** `LangChainRetriever` is initialized
- **THEN** the embedding function SHALL NOT create a new model instance but reuse the project's `get_embedder()` singleton

### Requirement: FAISS retrieval SHALL preserve actual similarity scores

The LangChain hybrid retriever SHALL use `similarity_search_with_relevance_scores()` (or equivalent) to retrieve actual FAISS similarity scores, instead of substituting rank-based `1/(rank+1)` scores. These scores SHALL be combined with BM25 scores in the hybrid ensemble.

#### Scenario: FAISS scores reflect semantic similarity
- **WHEN** FAISS retrieves documents for a query
- **THEN** each document SHALL have a score proportional to cosine similarity between the query embedding and the stored document embedding, not derived from rank position

#### Scenario: Combined BM25 + FAISS score uses meaningful FAISS scores
- **WHEN** the ensemble combines BM25 and FAISS results
- **THEN** the combined score SHALL use `0.5 * bm25_score + 0.5 * faiss_similarity_score` where `faiss_similarity_score` is the actual FAISS similarity (not `1/(rank+1)`)

### Requirement: Cross-encoder scores SHALL be normalized before threshold filtering

After cross-encoder reranking, scores SHALL be min-max normalized using `normalize_scores()` from `domain/services/embedding.py` before applying the `min_relevance_score` threshold. This ensures the threshold value of 0.15 is consistently meaningful regardless of cross-encoder score range.

#### Scenario: Filtered results preserved after normalization
- **WHEN** cross-encoder returns scores in range [-3, 5] for a set of chunks
- **THEN** after min-max normalization, at least one chunk SHALL have score >= 0.15 (assuming at least one chunk is relevant)
- **AND** the normalized scores SHALL be in [0, 1] range

### Requirement: LangChainRetriever.retrieve() SHALL produce results consistent with cosine path

The LangChain hybrid retriever's `retrieve()` method SHALL, for the same query and document set, return top chunks that overlap with the cosine path's results by at least 60% (intersection over union) when evaluated on real-world queries over the same corpus.

#### Scenario: Comparison test passes for known working query
- **WHEN** a test query "how to change the view mode in AxisVM" is executed on both the LangChain hybrid retriever and the cosine similarity retriever
- **THEN** at least 3 of the top 5 chunks SHALL be identical between both retrievers
- **AND** the top chunk SHALL contain the `EWindowState` enum reference
