# Project: RAG Pipeline

> **v0.1.0** — RAG pipeline with local LLM (MLX), 3 retrieval backends, Streamlit UI
> **Last updated**: 2026-06-15
> **Purpose**: Canonical AI-facing project brief. Supersedes `context.md`.
> <!-- AI: Start here for project context. For ops commands → AGENTS.md, for RAG deep-dive → docs.md -->

## 1. Project Identity
- Name: rag-pipeline
- Version: 0.1.0 (from pyproject.toml)
- One-liner: RAG pipeline with local LLM, MLX acceleration, and Streamlit UI
- Python version constraint: >=3.11,<3.13 (from pyproject.toml)
- Package manager: uv

## 2. Architecture (Concise)
- High-level: FastAPI → Domain Services → SQLite/FAISS
- 3 RAG backends: Cosine similarity (default), LangChain hybrid (BM25+FAISS+RRF), LlamaIndex
- Auth: JWT/bcrypt, 30-min expiry, `get_current_user` dependency on all routes
- Entrypoint chain: `src/main.py` imports `app` from `src.api.main`, runs uvicorn
- Singleton lazy-loading: LLM (`src/domain/services/llm.py`), Embedder (`src/domain/services/embedding.py`) — loaded on first use
- Background doc processing via `asyncio.create_task` in `src/domain/services/processor.py` (no queue persistence — lost on restart)
- All API routes under `/api/v1` prefix, defined in `src/api/routes/`
- Query cache: 3-day global TTL (configurable via `CACHE_EXPIRY_DAYS`, set to 0 to disable)

## 3. Directory Map
```
rag-pipeline/
├── src/
│   ├── main.py                   # Entrypoint (uvicorn runner)
│   ├── api/                       # FastAPI routes & schemas
│   ├── core/                      # Config, security, exceptions
│   ├── domain/                    # Business logic, ports, services
│   ├── infrastructure/            # DB, parsers, LLM, embeddings
│   └── pdf_semantic_chunking/     # PDF semantic chunking subsystem
├── client/                        # Streamlit UI
├── tests/                         # Unit + integration tests (doc/pytest)
├── scripts/                       # run_all.sh, stop_all.sh
├── data/                          # Uploads, vectorstore/, SQLite DB
├── docs/                          # Supporting docs
├── openspec/                      # OpenSpec specs + change management
│   ├── specs/                     # Canonical accepted specs
│   └── changes/                   # Active + archived changes
├── .opencode/
│   ├── agents.md                  # Multi-agent definitions + security policy
│   ├── agents/                    # Agent configs (coordinator, subagents)
│   ├── skills/                    # OpenSpec skills
│   └── opencode.json              # MCP + plugin config
├── todos/                         # Cross-session task persistence
├── AGENTS.md                      # Dev commands & quirks (ops reference)
├── docs.md                        # Deep RAG technical documentation
├── README.md                      # Human-facing landing page
└── project.md                     # ← YOU ARE HERE
```

## 4. Tech Stack (Deduplicated Table)
| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend framework | FastAPI 0.109+ | Async, Pydantic v2 |
| Python | 3.11+ | Constraint: >=3.11,<3.13 |
| ORM | SQLAlchemy 2.0+ | Async via aiosqlite |
| Auth | JWT (python-jose) + bcrypt | 30-min token expiry |
| Default RAG | Cosine similarity | all-mpnet-base-v2 embeddings (768d) |
| LangChain RAG | BM25 + FAISS + RRF | Hybrid retrieval |
| LlamaIndex RAG | Cosine similarity | SQLiteVectorStoreAdapter |
| Embeddings | sentence-transformers | all-mpnet-base-v2 (768d) |
| LLM | MLX (Apple Silicon) | mlx-community/Qwen2.5-1.5B-Instruct-4bit |
| Vector store | FAISS | data/vectorstore/ |
| Frontend | Streamlit | Port 8501 |
| Document parsers | pymupdf, python-docx | PDF, DOCX, TXT, MD, OpenAPI |
| Chunking | Recursive text split | 500 chars, 50 overlap |
| Package manager | uv | uv sync to install |

## 5. Key Quirks (Gotchas)

1. **`rank-bm25` pinned to old version** — pyproject.toml pins `==0.2.2` while latest is >=0.7; `uv` respects the pin
2. **Redundant `.env` loading** — loaded in both `src/core/config.py` and `src/api/main.py`
3. **No CI/Docker/pre-commit** — no `.pre-commit-config.yaml`, no CI workflows, no Docker configs
4. **`@pytest.mark.integration` NOT registered** — tests organized by directory (`tests/unit/` vs `tests/integration/`)
5. **LLM model discrepancy** — AGENTS.md env table says `mlx-community/Qwen2.5-1.5B-Instruct-4bit`; .env.example defaults to `microsoft/Phi-4-mini-instruct-8bit`
6. **`memory.md` has stale content** — `.opencode/memory.md` says "financial sentiment analysis" — this is incorrect. Ignore it. `project.md` is the authoritative source.
7. **Plugin-managed files** — `opencode-mem` plugin manages `memory.md`; `opencode-plugin-openspec` manages the `openspec/` workflow.

## 6. Required Environment Variables
| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `SECRET_KEY` | **Yes** | — | JWT signing key. Generate with: openssl rand -hex 32 |
| `HF_HUB_OFFLINE` | No | `0` | Set to `1` to skip model downloads |
| `HOST` | No | `127.0.0.1` | `0.0.0.0` for external access |
| `PORT` | No | `8000` | Backend port |
| `STREAMLIT_SERVER_PORT` | No | `8501` | Frontend port |
| `LLM_MODEL` | No | `mlx-community/Qwen2.5-1.5B-Instruct-4bit` | MLX-optimized, ~500MB |
| `EMBEDDING_MODEL` | No | `sentence-transformers/all-mpnet-base-v2` | 768-dim embeddings |
| `HF_TOKEN` | No | `<placeholder>` | Required for gated Hugging Face models |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | JWT expiry |
| `RERANKER_MODEL` | No | `cross-encoder/ms-marco-MiniLM-L6-v2` | Cross-encoder for re-ranking; enable via `RERANKER_ENABLED` |
| `VERIFICATION_ENABLED` | No | `true` | Enables sentence-level response verification against source chunks. Disable only if you understand the risk of unverified outputs. |
| `CACHE_EXPIRY_DAYS` | No | `3` | Query cache TTL (0=disabled) |

→ **Full list with defaults**: see `.env.example`

## 7. Testing Conventions
- Async mode (`asyncio_mode = "auto"`), all test files use `@pytest.mark.asyncio`
- Each test gets unique SQLite file via `setup_test_db` (autouse conftest fixture)
- Integration tests use `ASGITransport(app=app)` — no running server needed
- Tests organized by directory: `tests/unit/` vs `tests/integration/` (NOT by marker)
- Fixture PDFs/docs in `tests/docs/`
- Commands: `uv run pytest -v`, `uv run ruff check .`, `uv run mypy src/`

## 8. Agent Conventions
- **1 coordinator + 13 specialized sub-agents** defined in `.opencode/agents.md` — all free models (OpenCode Zen)
- **@coordinator** (big-pickle) orchestrates → delegates to specialized sub-agents
- **Mandatory @security review** for every code change — non-negotiable
- **OpenSpec workflow**: propose → design → spec → implement → archive (skills in `.opencode/skills/`)
- **MCP servers enabled**: OpenContext, Context7, GitHub, Azure-MCP, server-pdf (config: `.opencode/opencode.json`)
- **Plugins**: `opencode-mem` (memory), `opencode-plugin-openspec` (specs), `@tarquinen/opencode-dcp` (context)
- **Skills**: openspec-* (propose, apply, archive, explore), python-testing-patterns
- **`todos/` directory**: cross-session task persistence; synced via `@subagents/todo`

## 9. Undocumented Features Map
| Feature | File(s) | What it does |
|---------|---------|-------------|
| Cross-encoder Reranker | `src/domain/services/retrieval_langchain.py`, `src/core/config.py` | Re-ranks retrieval results via cross-encoder; gated by `RERANKER_ENABLED` |
| Response Verification | `src/domain/services/verification.py` (267 lines) | Sentence-level verification against source chunks; configurable similarity threshold |
| Prompt Builder | `src/domain/services/prompt_builder.py` (213 lines) | Dedup, anti-repetition, citation formatting, length control; shared by all 3 RAG pipelines |
| PDF Semantic Chunking | `src/pdf_semantic_chunking/` | Full subsystem: detection → extraction → enrichment → semantic chunking → validation; CLI + API endpoints |
| OpenAPI Ingestion | `src/infrastructure/parsers/` | Parses OpenAPI specs into searchable document content |
| Query Cache | Config: `CACHE_EXPIRY_DAYS` | 3-day global cache keyed by query hash + document ID + strategy |

## 10. Doc Reference Map
| Topic | File |
|-------|------|
| Quick start, features, API endpoint table | `README.md` |
| Agent commands, setup, linting, env var table | `AGENTS.md` |
| Deep RAG technical details (3 backends) | `docs.md` (949 lines) |
| Full env var defaults | `.env.example` |
| OpenSpec specs + change management | `openspec/` directory |
| Multi-agent system definitions + security policy | `.opencode/agents.md` |
| MCP server + plugin configuration | `.opencode/opencode.json` |
| Session archive | `SESSION_EXPORT.md` |
| **← CANONICAL PROJECT BRIEF** | **`project.md`** |
