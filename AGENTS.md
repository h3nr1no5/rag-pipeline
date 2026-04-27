# AGENTS.md

## Quick Commands

```bash
uv sync              # Install dependencies
uv run pytest -v      # Run tests
pytest tests/integration/<test_file>.py -v  # Run specific integration test
uv run ruff check .   # Lint
uv run mypy src/      # Typecheck

# Run servers
uvicorn src.api.main:app --reload --port 8000
streamlit run client/app.py --server.port 8501

# Or use scripts
./scripts/run_all.sh     # Start both backend + frontend
./scripts/stop_all.sh    # Stop all services
```

## Required Setup

1. `cp .env.example .env` - Create environment file
2. `uv sync` - Install dependencies (requires Python 3.11+)
3. LLM models download on first run (set `HF_HUB_OFFLINE=1` to skip)

## Important Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `HF_HUB_OFFLINE` | `0` | Set to `1` to skip model downloads |
| `PORT` | `8000` | Backend port |
| `HOST` | `127.0.0.1` | Host to bind servers to (127.0.0.1 for localhost only, 0.0.0.0 for all interfaces) |
| `STREAMLIT_SERVER_PORT` | `8501` | Frontend port |
| `secret_key` | **(required)** | JWT signing key |

## Architecture

- **Backend**: FastAPI at `src.api.main:app` (routes in `src/api/routes/`)
- **Frontend**: Streamlit at `client/app.py`
- **Database**: SQLite in `data/db.sqlite`
- **Vector Store**: FAISS in `data/vectorstore/`
- **Authentication**: JWT with bcrypt, tokens expire in 30 min

## Testing Notes

- Tests are async (`asyncio_mode = "auto"` in pyproject.toml)
- Integration tests may need running backend on port 8000
- Some tests use `@pytest.mark.integration` skip if backend unavailable

## App Startup

The backend loads `.env` in two places:
1. `src/core/config.py` - loads into `os.environ`
2. `src/api/main.py` - loads into `os.environ` again (redundant but works)