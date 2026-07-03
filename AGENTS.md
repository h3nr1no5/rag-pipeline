# AGENTS.md

## Quick Commands

```bash
uv sync                    # Install dependencies
uv run pytest -v -m "not slow"  # All tests (fast mode - excludes slow smoke test)
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
- **API-docs pipeline**: Configurable chunking strategies via YAML (`config/strategies.yaml`), seeded by `src/infrastructure/strategies/seeder.py`, supporting 4 entity types: interfaces, enums, error_codes, records

## API Endpoints

- **GET /api/v1/documents/strategies/types**: Returns available chunking strategy types with their configuration schemas (no authentication required)
- **All other routes**: Under `/api/v1` prefix with JWT authentication

## Key Quirks

- `rank-bm25` is listed with conflicting constraints (`>=0.7` and `==0.2.2`) in pyproject.toml — uv resolves to `0.2.2`
- `.env` is loaded redundantly in both `src/core/config.py` and `src/api/main.py`
- No `.pre-commit-config.yaml`, no CI workflows, no Docker configs in repo
- `.opencode/opencode.json` enables MCP Context7 and `opencode-mem` plugin
- `.opencode/agents.md` requires mandatory @security review for every code change
- `config` JSON column on ChunkingStrategy stores YAML-based chunking parameters and flows through the api-docs pipeline via `src/domain/services/processor.py`

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

## Profiling Commands

```bash
./scripts/run_profile.sh             # Full profile test run (all PROFILE lines)
./scripts/run_profile_fast.sh        # Quick profile run (PROFILE lines only)
```

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **rag-pipeline** (9693 symbols, 15325 relationships, 193 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/rag-pipeline/context` | Codebase overview, check index freshness |
| `gitnexus://repo/rag-pipeline/clusters` | All functional areas |
| `gitnexus://repo/rag-pipeline/processes` | All execution flows |
| `gitnexus://repo/rag-pipeline/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
