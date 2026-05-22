# RAG Pipeline

A production-ready RAG (Retrieval-Augmented Generation) pipeline with local LLM, MLX acceleration, and Streamlit UI.

## Features

- 🔐 **User Authentication** - JWT-based auth with bcrypt password hashing
- 📄 **Multi-format Documents** - PDF, DOCX, TXT, Markdown, and OpenAPI specs
- 💬 **Streaming Chat** - Real-time AI responses via Server-Sent Events
- 📦 **Query Caching** - 3-day global cache for identical queries
- 🎯 **API-Aware** - Understands OpenAPI endpoints and schemas
- 🏠 **Local LLM** - Runs on Apple Silicon with MLX acceleration
- 🔍 **Hybrid Retrieval** - Semantic search with structured API data

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, Pydantic
- **Frontend**: Streamlit
- **LLM**: MLX (Apple Silicon GPU optimized)
- **Embeddings**: Sentence Transformers (all-MiniLM-L6-v2)
- **Vector Store**: FAISS
- **Database**: SQLite

## Quick Start

### 1. Install Dependencies

```bash
cd rag-pipeline
uv sync
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
source .venv/bin/activate
```

### 3. Start the Backend

```bash
uvicorn src.api.main:app --reload --port 8000
```

### 4. Start the Streamlit UI

```bash
streamlit run client/app.py --server.port 8501
```

### 5. Open Browser

- API Docs: http://localhost:8000/docs
- Streamlit App: http://localhost:8501

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/signup` | POST | Create user account |
| `/auth/login` | POST | Get JWT token |
| `/documents` | POST | Upload document |
| `/documents` | GET | List documents |
| `/documents/{id}` | DELETE | Delete document |
| `/query` | POST | Query documents |
| `/query/stream` | POST | Stream query response |
| `/query/langchain` | POST | Query with LangChain retrieval |
| `/query/langchain/stream` | POST | Stream with LangChain retrieval |
| `/query/llamaindex` | POST | Query with LlamaIndex retrieval |
| `/query/llamaindex/stream` | POST | Stream with LlamaIndex retrieval |
| `/query/history` | GET | Query history |
| `/strategies` | GET | Chunking strategies |

## Project Structure

```
rag-pipeline/
├── src/
│   ├── api/           # FastAPI routes and schemas
│   ├── core/          # Config, security, exceptions
│   ├── domain/        # Business logic and ports
│   └── infrastructure/# Database, parsers, LLM, embeddings
├── client/            # Streamlit UI
├── tests/             # Unit and integration tests
└── data/              # Uploads, vector store, SQLite DB
```

## Testing



```bash
pytest -v

uv run pytest tests/ -v
```

## stop server


$ pkill -f "uvicorn.*src.api.main" 2>/dev/null; sleep 1; curl -s http://localhost:8000/ 2>&1 || echo "Server stopped"

## force kill



## License

MIT
