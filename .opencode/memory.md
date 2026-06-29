# Project Memory

## Project Overview
**RAG Pipeline** is a production-ready RAG pipeline with local LLM (MLX), 3 retrieval backends (cosine, LangChain hybrid, LlamaIndex), and Streamlit UI. It supports document ingestion (PDF, DOCX, TXT, MD, OpenAPI), semantic chunking, cross-encoder reranking, and response verification.

## Architecture
- **Backend**: FastAPI at `src.api.main:app` (routes in `src/api/routes/`)
- **Frontend**: Streamlit at `client/app.py`
- **Database**: SQLite in `data/db.sqlite`
- **Vector Store**: FAISS in `data/vectorstore/`
- **Authentication**: JWT with bcrypt, tokens expire in 30 min

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.109+, Python 3.11+ |
| Database | SQLite + SQLAlchemy 2.0+ |
| Vector Store | FAISS |
| Frontend | Streamlit |
| Auth | JWT with bcrypt |

## Quick Commands
```bash
uv sync              # Install dependencies
uv run pytest -v      # Run tests
uv run ruff check .   # Lint
uv run mypy src/      # Typecheck

# Run servers
uvicorn src.api.main:app --reload --port 8000
streamlit run client/app.py --server.port 8501
```

## Important Context
- Streamlit frontend on port 8501
- JWT tokens expire in 30 minutes
- Vector embeddings stored in FAISS index
- secret_key required in .env for JWT signing

**Last updated**: June 2026