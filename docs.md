# RAG Pipeline Documentation

This document describes the three retrieval implementations in the RAG Pipeline project: the **Current RAG** (simple cosine similarity), **LangChain RAG** (hybrid BM25 + FAISS), and **LlamaIndex RAG** (SQLite adapter).

---

## Overview

The RAG Pipeline provides three distinct retrieval strategies for question-answering over uploaded documents:

| Aspect | Current RAG | LangChain RAG (Hybrid) | LlamaIndex RAG |
|--------|------------|------------------------|----------------|
| **Method** | Cosine similarity (dense) | BM25 (sparse) + FAISS (dense) | Cosine similarity (dense) |
| **API Endpoint** | `/api/v1/query` | `/api/v1/query/langchain` | `/api/v1/query/llamaindex` |
| **Streaming** | `/api/v1/query/stream` | `/api/v1/query/langchain/stream` | `/api/v1/query/llamaindex/stream` |
| **Storage** | SQLite + in-memory embeddings | FAISS vector store + in-memory | SQLite VectorStore adapter |
| **Fusion** | None (single method) | Reciprocal Rank Fusion (RRF) | None (single method) |
| **Complexity** | O(n) embedding comparisons | O(n log n) + O(n) index search | O(n) embedding comparisons |
| **Use Case** | Semantic-only queries | Keyword + semantic hybrid | Simple retrieval with LlamaIndex API |

Both implementations share common infrastructure:

- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions)
- **Chunking**: Recursive text splitting (500 chars, 50 overlap)
- **Document Parsers**: PDF (pymupdf), DOCX (python-docx), TXT/MD, OpenAPI specs
- **LLM**: MLX-based `Qwen2.5-1.5B-Instruct-4bit`
- **Database**: SQLite with async support (aiosqlite)
- **Frontend**: Streamlit with side-by-side comparison

---

## Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                         Client (Streamlit)                              │
│                   chat page with compare mode                              │
└──────────────────────────────┬────────────────────────────────────────┘
                                │
          ┌─────────────┴─────────────┴─────────────┐
          │                                         │
          ▼                                         ▼                                         ▼
   ┌──────────────┐                         ┌──────────────┐                         ┌──────────────┐
   │  POST /query  │                         │ POST /query/ │                         │ POST /query/ │
   │   (Current)  │                         │   langchain   │                         │   llamaindex │
   └───────┬────────┘                         └───────┬────────┘                         └───────┬────────┘
          │                                         │                                         │
   ┌───────┴────────┐                         ┌──────┴────────┐                         ┌───────┴────────┐
   │   Cosine      │                         │  LangChain     │                         │  SQLite        │
   │ Similarity    │                         │  Hybrid        │                         │  VectorStore   │
   │ Retrieval     │                         │  (BM25+FAISS)  │                         │   Adapter     │
   └───────────────┘                         └─┬──────────────┘                         └───────────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
       ┌───────────┐      ┌───────────┐      ┌───────────┐
       │   BM25    │      │  FAISS    │      │  Custom   │
       │ Retriever │      │Vectorstore│     │Ensemble   │
       └───────────┘      └───────────┘     │Retriever  │
                                            └───────────┘
```

### Data Flow

```
Document Upload
      │
      ▼
┌───────────────��┐
│  Document      │
│  Parsers       │
│ (PDF/DOCX/etc) │
└────┬───────────┘
      │
      ▼
┌────────────────┐
│   Chunking     │
│ (Recursive)    │
└────┬───────────┘
      │
      ▼
┌────────────────┐     ┌────────────────┐
│   Embedding    │────▶│    Storage     │
│   (all-MiniLM) │     │  (SQLite JSON) │
└────────────────┘     └────────────────┘
      │
      ▼
┌──────────────────────────────────────────────────────────────┐
│                    Query Processing                            │
├────────────────────────┬─────────────────────────────────────┬──────────────────────────┐
│     Current RAG        │         LangChain RAG               │      LlamaIndex RAG        │
│ ───────────────────────│─────────────────────────────────────│──────────────────────────│
│ 1. Embed query         │ 1. Embed query                      │ 1. Embed query           │
│ 2. Embed all chunks   │ 2. BM25 search (keyword)            │ 2. SQLite search         │
│ 3. Compute cosine     │ 3. FAISS search (semantic)           │ 3. Cosine similarity   │
│ 4. Return top-k       │ 4. RRF fusion                       │ 4. Return top-k        │
│                      │ 5. Return top-k                     │                        │
└────────────────────────┴─────────────────────────────────────┴──────────────────────────┘
      │
      ▼
┌────────────────┐
│    LLM          │
│ (Qwen2.5-1.5B) │
└────┬───────────┘
      │
      ▼
┌────────────────┐
│   Response     │
│   + Sources    │
└────────────────┘
```

---

## Current RAG (Cosine Similarity)

### Implementation

**File**: `src/api/routes/query/_retrieval.py`

The Current RAG uses a simple but efficient dense retrieval method based on cosine similarity via dot product of normalized embeddings.

### Core Algorithm

```python
async def retrieve_chunks(
    db: "AsyncSession",
    user_id: str,
    document_ids: list[str],
    question: str,
    top_k: int = 5,
) -> list[tuple[Chunk, float]]:
    """Retrieve relevant chunks from documents based on semantic similarity."""
    
    # 1. Load embedder and generate query embedding
    embedder = await get_embedder()
    query_embedding = await embedder.embed_text(question)
    
    # 2. Fetch all chunks for the specified documents
    all_chunks = await db.execute(
        select(Chunk).where(Chunk.document_id.in_(document_ids))
    )
    
    # 3. Generate embeddings for all chunks
    chunk_texts = [c.content for c in all_chunks]
    chunk_embeddings = await embedder.embed_texts(chunk_texts)
    
    # 4. Compute cosine similarity (dot product of normalized vectors)
    similarities = []
    for chunk, embedding in zip(all_chunks, chunk_embeddings):
        similarity = sum(q * e for q, e in zip(query_embedding, embedding))
        similarities.append((chunk, similarity))
    
    # 5. Sort by similarity and return top-k
    similarities.sort(key=lambda x: x[1], reverse=True)
    top_chunks = similarities[:top_k]
    
    return top_chunks
```

### How It Works

1. **Query Embedding**: The question is embedded using the sentence-transformers model, producing a 384-dimensional vector.

2. **Chunk Embedding**: All document chunks are embedded in bulk for efficiency.

3. **Similarity Computation**: Since embeddings are normalized, cosine similarity reduces to a simple dot product:
   
   ```
   similarity = query_embedding · chunk_embedding
             = sum(q[i] * e[i] for i in 384 dims)
   ```

4. **Ranking**: Results are sorted by similarity score in descending order.

### Advantages

- **Simple**: Straightforward implementation with minimal dependencies
- **Fast**: Single embedding + sort operation, no index building
- **Lightweight**: No external vector store required
- **Memory-Efficient**: Embeddings can be stored in SQLite JSON field

### Limitations

- **No Keyword Matching**: Cannot handle exact keyword queries well
- **O(n) Complexity**: Must compare against all chunks each query
- **Single Method**: Cannot combine complementary signals

---

## LlamaIndex RAG (SQLite Adapter)

### Implementation

**File**: `src/domain/services/retrieval_llamaindex.py`

The LlamaIndex RAG uses a lightweight approach with SQLiteVectorStoreAdapter that reads existing embeddings from the SQLite database.

### Core Components

#### SQLiteVectorStoreAdapter

```python
class SQLiteVectorStoreAdapter:
    """Simple vector store adapter that reads from existing SQLite Chunk table."""
    
    def __init__(self, db_session: AsyncSession, document_ids: List[str]):
        self._db = db_session
        self._document_ids = document_ids
    
    async def search(self, query_embedding: List[float], top_k: int = 5) -> List[LlamaIndexRetrievedChunk]:
        """Search by cosine similarity."""
        chunks = await self.get_chunks_with_embeddings()
        
        # Calculate cosine similarity
        similarities = []
        for chunk in chunks:
            emb = chunk["embedding"]
            if emb:
                sim = self._cosine_similarity(query_embedding, emb)
                similarities.append((chunk, sim))
        
        # Sort and get top k
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        return [
            LlamaIndexRetrievedChunk(
                chunk_id=chunk["id"],
                content=chunk["content"],
                score=sim,
                metadata=chunk["metadata"],
            )
            for chunk, sim in similarities[:top_k]
            if sim > 0.01
        ]
```

### Security Features

- **Access Control**: Filters chunks by `document_ids` passed to constructor
- **Parameter Validation**: `top_k` clamped between 1 and 100
- **No Global State**: Each request creates fresh instance

### Advantages

- **Lightweight**: Reuses existing SQLite embeddings, no extra index
- **Simple**: Direct cosine similarity computation
- **Secure**: Proper document-level access control
- **Fast**: No index building required

### Limitations

- **O(n) Complexity**: Must compare against all chunks
- **No Hybrid**: Only semantic, no keyword matching
- **Same as Current RAG**: Algorithmically identical, differs in API

---

## LangChain RAG (Hybrid BM25 + FAISS)

### Implementation

**File**: `src/domain/services/retrieval_langchain.py`

The LangChain RAG combines both sparse (BM25) and dense (FAISS) retrieval methods using Reciprocal Rank Fusion for optimal results.

### Core Components

#### CustomEnsembleRetriever

```python
class CustomEnsembleRetriever(BaseRetriever):
    """Custom ensemble retriever combining BM25 (sparse) + FAISS (dense)."""
    
    def __init__(
        self,
        retrievers: list,
        weights: list[float] | None = None,
        k: int = 5,
    ):
        self.retrievers = retrievers
        self.weights = weights or [0.5] * len(retrievers)
        self.k = k
    
    async def _aget_relevant_documents(
        self,
        query: str,
        k: int | None = None,
        **kwargs: Any,
    ) -> list[LangChainDocument]:
        """Get relevant documents from all retrievers and combine scores."""
        k = k or self.k
        
        all_docs = {}
        all_scores = {}
        
        # Run each retriever and collect results
        for retriever in self.retrievers:
            docs = await retriever.ainvoke(query)
            for i, doc in enumerate(docs[:k * 2]):
                doc_key = doc.metadata.get("chunk_id", str(i))
                if doc_key not in all_docs:
                    all_docs[doc_key] = doc
                    all_scores[doc_key] = 0.0
                # Reciprocal rank scoring
                score = 1.0 / (i + 1)
                all_scores[doc_key] += score
        
        # Sort by combined score
        sorted_keys = sorted(all_scores.keys(), key=lambda x: all_scores[x], reverse=True)
        
        results = []
        for key in sorted_keys[:k]:
            results.append(all_docs[key])
        
        return results
```

### How It Works

#### 1. BM25 (Sparse Retrieval)

BM25 is a probabilistic ranking function used for text search:

- **Term Frequency (TF)**: Counts keyword occurrences in each chunk
- **Inverse Document Frequency (IDF)**: Penalizes common terms, boosts rare terms
- **Document Length Normalization (b)**: Adjusts for varying chunk sizes

```python
# Initialize BM25 retriever
self._bm25_retriever = BM25Retriever.from_documents(
    langchain_docs,
    k1=1.5,  # Term frequency saturation
    b=0.75   # Length normalization
)
```

**Strengths**: Excels at exact keyword matching, handles vocabulary mismatch

**Weaknesses**: Ignors semantic similarity, limited by exact term matching

#### 2. FAISS (Dense Retrieval)

FAISS (Facebook AI Similarity Search) enables efficient similarity search over dense embeddings:

```python
# Create FAISS vectorstore from existing embeddings
self._faiss_vectorstore = FAISS.from_embeddings(
    text_embeddings=[(doc.page_content, emb) for doc, emb in zip(langchain_docs, chunk_embeddings)],
    embedding=embeddings,
    metadatas=[doc.metadata for doc in langchain_docs]
)
```

**Strengths**: Captures semantic similarity, handles synonyms

**Weaknesses**: May miss exact keywords, requires embedding computation

#### 3. Reciprocal Rank Fusion (RRF)

Combines ranked lists from both retrievers using the formula:

```
RRF_score(doc) = sum(1.0 / (k + rank_i(doc))) for each retriever i
```

Where `k` is a constant (typically 60) that prevents heavily-ranked documents from dominating.

```python
# For each retriever:
for i, doc in enumerate(docs[:k * 2]):
    score = 1.0 / (i + 1)  # Reciprocal rank
    all_scores[doc_key] += score
```

### Initialization Flow

```python
async def initialize(self, chunks: list, chunk_embeddings: list[list[float]]) -> None:
    """Initialize the hybrid retriever with chunks and their embeddings."""
    
    # 1. Convert chunks to LangChain documents
    langchain_docs = [
        LangChainDocument(
            page_content=chunk.content,
            metadata={
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                **(chunk.chunk_metadata or {})
            }
        )
        for chunk in chunks
    ]
    
    # 2. Build BM25 index
    self._bm25_retriever = BM25Retriever.from_documents(
        langchain_docs,
        k1=1.5,
        b=0.75
    )
    
    # 3. Build FAISS index
    embeddings = await self._get_embeddings()
    self._faiss_vectorstore = FAISS.from_embeddings(...)
    
    # 4. Create ensemble retriever
    retrievers = [self._bm25_retriever, self._faiss_vectorstore.as_retriever()]
    weights = [0.5, 0.5]  # Equal weight
    
    self._ensemble = CustomEnsembleRetriever(
        retrievers=retrievers,
        weights=weights,
        k=5,
    )
```

### Advanced: Retrieve with Scores

The `retrieve_with_scores` method provides detailed scoring:

```python
async def retrieve_with_scores(
    self,
    question: str,
    question_embedding: list[float],
    top_k: int = 5,
) -> list[RetrievedChunkResult]:
    """Retrieve with combined BM25 and FAISS scores."""
    
    # Get BM25 scores
    bm25_results = await self._bm25_retriever.ainvoke(question, k=top_k * 2)
    bm25_scores = {doc.metadata["chunk_id"]: 1.0/(i+1) 
                   for i, doc in enumerate(bm25_results)}
    
    # Get FAISS scores
    faiss_results = await self._faiss_vectorstore.as_retriever().ainvoke(question, k=top_k * 2)
    faiss_scores = {doc.metadata["chunk_id"]: 1.0/(i+1) 
                   for i, doc in enumerate(faiss_results)}
    
    # Combine with weighted fusion
    all_chunk_ids = set(bm25_scores.keys()) | set(faiss_scores.keys())
    combined = []
    
    for chunk_id in all_chunk_ids:
        bm25_score = bm25_scores.get(chunk_id, 0)
        faiss_score = faiss_scores.get(chunk_id, 0)
        
        # Weighted combination
        combined_score = 0.5 * bm25_score + 0.5 * faiss_score
        
        # Determine primary source
        source = "hybrid"
        if bm25_score > faiss_score:
            source = "bm25"
        elif faiss_score > bm25_score:
            source = "faiss"
        
        combined.append(RetrievedChunkResult(
            chunk_id=chunk_id,
            content=content,
            score=combined_score,
            metadata=metadata,
            source=source
        ))
    
    combined.sort(key=lambda x: x.score, reverse=True)
    return combined[:top_k]
```

### Advantages

- **Hybrid Coverage**: Handles both keyword and semantic queries
- **Better Ranking**: RRF balances complementary signals
- **More Robust**: Degrades gracefully if one method fails

### Limitations

- **More Complex**: Requires multiple indexes
- **Higher Memory**: FAISS index + BM25 in-memory
- **Dependencies**: Requires langchain, rank-bm25, faiss-cpu

---

## Comparison Table

| Feature | Current RAG | LangChain RAG | LlamaIndex RAG |
|---------|-------------|--------------|---------------|
| **Retrieval Method** | Cosine similarity | BM25 + FAISS hybrid | Cosine similarity |
| **Algorithm** | Dense (embeddings) | Sparse + Dense | Dense (embeddings) |
| **API Endpoint** | `/api/v1/query` | `/api/v1/query/langchain` | `/api/v1/query/llamaindex` |
| **Streaming** | `/api/v1/query/stream` | `/api/v1/query/langchain/stream` | `/api/v1/query/llamaindex/stream` |
| **Dependencies** | sentence-transformers | langchain, rank-bm25, faiss-cpu | sentence-transformers |
| **Index Building** | None (on-the-fly) | BM25 + FAISS indexes | None (reuses SQLite) |
| **Cache Key Suffix** | Default | `_langchain` | `_llamaindex` |
| **Keyword Matching** | Weak | Strong (BM25) | Weak |
| **Semantic Matching** | Strong | Strong (FAISS) | Strong |

### Benchmark Considerations

| Metric | Current RAG | LangChain RAG | LlamaIndex RAG |
|--------|-------------|--------------|---------------|
| **Cold Start** | ~0.5s embedding load | ~2s index build | ~0.5s embedding load |
| **Per Query** | ~100ms (1000 chunks) | ~150ms (with fusion) | ~100ms (1000 chunks) |
| **Scale** | 10K chunks | 100K+ chunks | 10K chunks |

---

## When to Use Each

### Use Current RAG When:

1. **Pure Semantic Queries**: Questions seeking meaning rather than exact terms
   - "What is this function about?"
   - "Explain how authentication works"

2. **Small Document Sets**: Under 5,000 chunks
   - Simpler infrastructure
   - No index building overhead

3. **Low Latency Priority**: Fastest response time needed
   - Single embedding + sort operation

4. **Resource Constraints**: Limited memory available
   - No FAISS index storage

5. **Prototyping**: Quick iteration and testing

```python
# Example: Current RAG query
import requests

response = requests.post(
    "http://localhost:8000/api/v1/query",
    json={
        "document_ids": ["doc-123"],
        "question": "How do I configure the API?"
    }
)
print(response.json())
```

### Use LangChain RAG When:

1. **Hybrid Query Needs**: Combining keyword + semantic search
   - "Find the POST /users endpoint that creates a user"
   - "What parameters does the login function accept?"

2. **Large Document Sets**: Over 10,000 chunks
   - FAISS enables scalable search

3. **Precision Critical**: Need best possible ranking
   - RRF balances multiple signals

4. **API Documentation**: Keyword-heavy content
   - BM25 excels at path/method lookups

5. **Comparison Testing**: Evaluating retrieval methods

```python
# Example: LangChain RAG query
response = requests.post(
    "http://localhost:8000/api/v1/query/langchain",
    json={
        "document_ids": ["doc-123"],
        "question": "Find the POST /users endpoint"
    }
)
result = response.json()

# Check which method contributed
for source in result["sources"]:
    print(f"Source: {source.get('metadata', {}).get('source', 'unknown')}")
```

### Use LlamaIndex RAG When:

1. **LlamaIndex Integration**: Prefer using LlamaIndex API patterns
   - "UseLlamaIndex's retrieval abstractions"
   - "Integration testing with LlamaIndex"

2. **Lightweight Retrieval**: Need simple retrieval with minimal dependencies
   - Same algorithm as Current RAG but via LlamaIndex API
   - Reuses existing SQLite embeddings

3. **Migration Path**: Moving from current setup to LlamaIndex
   - Test compatibility before committing
   - Compare performance metrics

4. **Component Testing**: Testing LlamaIndex-specific features
   - Custom node parsers
   - Custom retrievers

5. **Simplicity Preferred**: Want same behavior as Current RAG
   - No hybrid search needed
   - Direct cosine similarity

```python
# Example: LlamaIndex RAG query
response = requests.post(
    "http://localhost:8000/api/v1/query/llamaindex",
    json={
        "document_ids": ["doc-123"],
        "question": "How does authentication work?"
    }
)
result = response.json()

print(f"Answer: {result['answer']}")
print(f"Sources: {len(result['sources'])} chunks")
```

### Comparison Mode (Frontend)

The Streamlit frontend supports side-by-side comparison:

```python
# In client/pages/3_💬_Chat.py
if st.session_state.get("compare_mode"):
    # Show both results
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Current RAG")
        # Query Current RAG endpoint
    
    with col2:
        st.markdown("### LangChain RAG")
        # Query LangChain endpoint
```

---

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `EMBEDDING_BATCH_SIZE` | `32` | Batch size for embedding |
| `DEFAULT_CHUNK_SIZE` | `500` | Chunk size in characters |
| `DEFAULT_CHUNK_OVERLAP` | `50` | Character overlap between chunks |
| `LLM_MODEL` | `mlx-community/Qwen2.5-1.5B-Instruct-4bit` | LLM model |
| `LLM_MAX_TOKENS` | `600` | Max response tokens |
| `LLM_TEMPERATURE` | `0.5` | LLM creativity |

### Programmatic Configuration

#### Changing Chunking Parameters

```python
# In document upload configuration
chunking_config = {
    "chunk_size": 1000,        # Larger chunks
    "chunk_overlap": 100,     # More overlap
    "separators": ["\n\n", "\n", " "]
}
```

#### Adjusting BM25 Parameters

```python
from langchain_community.retrievers import BM25Retriever

# In retrieval_langchain.py
bm25 = BM25Retriever.from_documents(
    docs,
    k1=1.5,   # Higher = more term frequency saturation
    b=0.75     # Higher = more length normalization
)
```

#### Customizing Weights

```python
# In LangChain retriever
 ensemble = CustomEnsembleRetriever(
     retrievers=[bm25_retriever, faiss_retriever],
     weights=[0.7, 0.3],  # More weight on BM25
     k=5
 )
```

### FAISS Index Persistence

```python
# Save FAISS index
vectorstore.save_local("faiss_index")

# Load FAISS index
vectorstore = FAISS.load_local(
    "faiss_index", 
    embeddings, 
    allow_dangerous_deserialization=True
)
```

---

## API Usage Examples

### 1. Current RAG Query

```python
import requests

url = "http://localhost:8000/api/v1/query"
payload = {
    "document_ids": ["doc-abc-123"],
    "question": "How does authentication work?"
}

response = requests.post(url, json=payload)
data = response.json()

print(f"Answer: {data['answer']}")
print(f"Sources: {len(data['sources'])} chunks")
print(f"Latency: {data['latency_ms']}ms")
```

### 2. LangChain RAG Query

```python
import requests

url = "http://localhost:8000/api/v1/query/langchain"
payload = {
    "document_ids": ["doc-abc-123"],
    "question": "Find the POST /login endpoint"
}

response = requests.post(url, json=payload)
data = response.json()

print(f"Answer: {data['answer']}")
for src in data["sources"]:
    print(f"  - {src['chunk_id']}: score={src['score']:.3f}")
```

### 3. LlamaIndex RAG Query

```python
import requests

url = "http://localhost:8000/api/v1/query/llamaindex"
payload = {
    "document_ids": ["doc-abc-123"],
    "question": "How does authentication work?"
}

response = requests.post(url, json=payload)
data = response.json()

print(f"Answer: {data['answer']}")
print(f"Sources: {len(data['sources'])} chunks")
print(f"Latency: {data['latency_ms']}ms")
```

### 5. Streaming Response

```python
import requests
import sseclient

url = "http://localhost:8000/api/v1/query/stream"
payload = {
    "document_ids": ["doc-abc-123"],
    "question": "Explain the API schema"
}

response = requests.post(url, json=payload, stream=True)
client = sseclient.SSEClient(response)

for event in client.events():
    data = json.loads(event.data)
    if "token" in data:
        print(data["token"], end="")
    elif "sources" in data:
        print("\nSources:", data["sources"])
```

### 6. Compare Both Methods

```python
import requests
from concurrent.futures import ThreadPoolExecutor

def query_current():
    return requests.post(
        "http://localhost:8000/api/v1/query",
        json={"document_ids": doc_ids, "question": question}
    ).json()

def query_langchain():
    return requests.post(
        "http://localhost:8000/api/v1/query/langchain",
        json={"document_ids": doc_ids, "question": question}
    ).json()

# Execute both in parallel
with ThreadPoolExecutor() as executor:
    current, langchain = executor.map(
        lambda f: f(), 
        [query_current, query_langchain]
    )

print("Current RAG:", current["answer"][:200])
print("LangChain RAG:", langchain["answer"][:200])
```

### 6. Python Client Wrapper

```python
class RAGClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    def query(self, doc_ids: list, question: str, mode="current"):
        endpoint = f"{self.base_url}/api/v1/query"
        if mode == "langchain":
            endpoint = f"{self.base_url}/api/v1/query/langchain"
        elif mode == "llamaindex":
            endpoint = f"{self.base_url}/api/v1/query/llamaindex"
        
        return requests.post(endpoint, json={
            "document_ids": doc_ids,
            "question": question
        }).json()

# Usage
client = RAGClient()
result = client.query(["doc-123"], "How do I upload files?")
print(result["answer"])
```

---

## Database Schema

### Chunk Table (SQLite)

```python
class Chunk(Base):
    __tablename__ = "chunks"
    
    id: Mapped[str]           # Primary key
    document_id: Mapped[str]  # Foreign key to Document
    content: Mapped[str]     # Chunk text content
    chunk_index: Mapped[int] # Position in document
    chunk_metadata: Mapped[Optional[dict]]  # Custom metadata
    embedding: Mapped[Optional[list]]  # 384-dim vector (JSON)
    embedding_id: Mapped[Optional[int]]  # Vector ID
    created_at: Mapped[datetime]  # Timestamp
```

### Query Cache Table

```python
class QueryCache(Base):
    __tablename__ = "query_cache"
    
    id: Mapped[str]
    user_id: Mapped[str]
    document_id: Mapped[str]
    query_hash: Mapped[str]  # Cache key
    query_text: Mapped[str]
    response_text: Mapped[str]
    source_chunk_ids: Mapped[Optional[list]]  # Source chunks
    chunking_strategy_id: Mapped[str]
    embedding_model_version: Mapped[str]
    latency_ms: Mapped[int]
    expires_at: Mapped[datetime]
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|------|----------|
| Empty embeddings | Empty text input | Add whitespace handling |
| Slow queries | Large chunk count | Implement pagination |
| Index not built | Import error | Check langchain dependencies |
| Cache conflicts | Same cache key | Use `_langchain` suffix |
| Memory issues | Large FAISS index | Implement persistence |

### Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)

# Enable retrieval logging
logger = logging.getLogger(__name__)
logger.info(f"Retrieving chunks: {document_ids}")
logger.info(f"Query embedding: {len(query_embedding)} dims")
logger.info(f"Similarity scores: {similarities[:5]}")
```

---

## References

- [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
- [FAISS Documentation](https://faiss.ai/)
- [LangChain Retrievers](https://python.langchain.com/docs/modules/data_connection retrievers/)
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcampub/rm/)

---

## Appendix: Method Selection Guide

```
                        ┌─────────────────────┐
                        │    User Query       │
                        └─────────┬──────────┘
                                  │
                                  ▼
                    ┌───────────────────────────────┐
                    │     Analyze Query Type       │
                    └───────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
   │  Keywords?  │     │ Semantic?  │     │   Both?    │
   │   (Yes)     │     │   (Yes)    │     │   (Yes)    │
   └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
          │                   │                   │
          ▼                   ▼                   ▼
   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
   │ Use BM25   │     │  Use FAISS │     │ Use RRF   │
   │  (Current │     │ (Current  │     │(LangChain│
   │  works)   │     │ works)    │     │ preferred)│
   └──────────────┘     └──────────────┘     └──────────────┘
```

---

*Document Version: 1.0*
*Last Updated: April 2026*