# Context

A production-ready RAG pipeline with local LLM, MLX acceleration, and Streamlit UI.

## Project Overview

- **Type**: RAG (Retrieval-Augmented Generation) Pipeline
- **Backend**: FastAPI, SQLAlchemy, Pydantic
- **Frontend**: Streamlit
- **LLM**: MLX (Apple Silicon optimized)
- **Embeddings**: Sentence Transformers (all-MiniLM-L6-v2)
- **Vector Store**: FAISS
- **Database**: SQLite

## Key Features

- User Authentication - JWT-based auth with bcrypt password hashing
- Multi-format Documents - PDF, DOCX, TXT, Markdown, and OpenAPI specs
- Streaming Chat - Real-time AI responses via Server-Sent Events
- Query Caching - 3-day global cache for identical queries
- API-Aware - Understands OpenAPI endpoints and schemas
- Local LLM - Runs on Apple Silicon with MLX acceleration
- Hybrid Retrieval - Semantic search with structured API data

## Project Structure

```
rag-pipeline/
├── src/
│   ├── api/           # FastAPI routes and schemas
│   ├── core/          # Config, security, exceptions
│   ├── domain/        # Business logic and ports
│   └── infrastructure/ # Database, parsers, LLM, embeddings
├── client/            # Streamlit UI
├── tests/             # Unit and integration tests
└── data/              # Uploads, vector store, SQLite DB
```

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

## Important Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `HF_HUB_OFFLINE` | `0` | Set to `1` to skip model downloads |
| `PORT` | `8000` | Backend port |
| `STREAMLIT_SERVER_PORT` | `8501` | Frontend port |
| `secret_key` | **(required)** | JWT signing key |

## Architecture

- **Backend**: FastAPI at `src.api.main:app` (routes in `src/api/routes/`)
- **Frontend**: Streamlit at `client/app.py`
- **Database**: SQLite in `data/db.sqlite`
- **Vector Store**: FAISS in `data/vectorstore/`
- **Authentication**: JWT with bcrypt, tokens expire in 30 min