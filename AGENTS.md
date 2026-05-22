# AGENTS.md

## Quick Commands

```bash
uv sync                    # Install dependencies
uv run pytest -v           # All tests
uv run pytest tests/unit/  # Unit tests only
uv run pytest tests/integration/<file>.py -v  # Specific integration test
uv run ruff check .        # Lint (pyproject.toml: py311, line-length=100)
uv run mypy src/           # Typecheck (no config in pyproject.toml)
uvicorn src.api.main:app --reload --port 8000           # Backend
streamlit run client/app.py --server.port 8501          # Frontend
./scripts/run_all.sh       # Both backend + frontend
./scripts/stop_all.sh      # Stop all services
```

## Required Setup

1. `cp .env.example .env` - Create environment file
2. `uv sync` (Python 3.11+)
3. First run downloads the LLM model (~500MB). Set `HF_HUB_OFFLINE=1` to skip.

## Architecture

- **Backend**: FastAPI, all routes under `/api/v1` prefix
- **Frontend**: Streamlit at `client/app.py`
- **3 RAG backends**: cosine similarity (default), LangChain (BM25+FAISS hybrid), LlamaIndex — query routes in `src/api/routes/query/routes.py`
- **LLM & Embedder**: singletons, lazy-loaded on first use (`domain/services/llm.py`, `embedding.py`)
- **Document processing**: async background via `asyncio.create_task` in `domain/services/processor.py`
- **Auth**: JWT/bcrypt, 30-min expiry, route-level `get_current_user` dependency
- **DB**: SQLite via SQLAlchemy + aiosqlite, FAISS vector store in `data/vectorstore/`
- **Entrypoint**: `src/main.py` imports `app` from `src.api.main` and runs uvicorn

## Key Quirks

- `rank-bm25` is listed with conflicting constraints (`>=0.7` and `==0.2.2`) in pyproject.toml — uv resolves to `0.2.2`
- `.env` is loaded redundantly in both `src/core/config.py` and `src/api/main.py`
- No `.pre-commit-config.yaml`, no CI workflows, no Docker configs in repo
- `.opencode/opencode.json` enables MCP Context7 and `opencode-mem` plugin
- `.opencode/agents.md` requires mandatory @security review for every code change

## Testing Notes

- Async tests (`asyncio_mode = "auto"`), all test files use `@pytest.mark.asyncio`
- Each test gets its own unique SQLite file via `setup_test_db` (autouse conftest fixture)
- Integration tests use `ASGITransport(app=app)` for in-process HTTP — no running server needed
- `@pytest.mark.integration` is NOT registered — tests are organized by directory (`unit/` vs `integration/`)
- Fixture docs for PDF/upload tests in `tests/docs/`

## Important Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `HF_HUB_OFFLINE` | `0` | Set to `1` to skip model downloads |
| `SECRET_KEY` | **(required)** | JWT signing key |
| `HOST` | `127.0.0.1` | `0.0.0.0` for external access |
| `PORT` | `8000` | Backend port |
| `STREAMLIT_SERVER_PORT` | `8501` | Frontend port |
| `LLM_MODEL` | `mlx-community/Qwen2.5-1.5B-Instruct-4bit` | MLX-optimized, ~500MB |
| `EMBEDDING_MODEL` | `sentence-transformers/all-mpnet-base-v2` | |
| `HF_TOKEN` | `<placeholder>` | Set for gated models |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT expiry |
