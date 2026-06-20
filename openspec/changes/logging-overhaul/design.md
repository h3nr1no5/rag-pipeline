## Context

The RAG pipeline runs in development mode with `LOG_LEVEL=DEBUG`. Logging uses stdlib `logging` throughout (181 logger.\* calls). The primary pain point is signal-to-noise ratio: per-query logs bury meaningful events (latency spikes, verification failures, errors) under repeated stage gates, a full prompt dump, and duplicate request tracking.

Previous attempts to fix this with global log-level changes fail because different modules need different verbosity at different times. During development, you want INFO for most modules but may need DEBUG for a specific module under investigation.

This design introduces a **runtime log level override system** using stdlib primitives only — no new dependencies.

## Goals / Non-Goals

**Goals:**
- Reduce per-query log volume by ~60% at default INFO level
- Enable per-module log level toggling at runtime without restart
- Eliminate duplicate/redundant log lines (middleware vs uvicorn, multiple retriever lines per query)
- Replace verbose DEBUG payloads (prompt dumps) with compact, identifiable fingerprints
- Consolidate multi-line initialization logs into single structured events
- Keep implementation in stdlib `logging` — no new dependencies

**Non-Goals:**
- Production log aggregation or shipping (Datadog, etc.)
- Log rotation or retention policies
- Structured JSON output format (future concern)
- Session-scoped log overrides via contextvars (overkill for current needs)
- Modifying `.env` or config files — overrides are runtime-only, in-memory

## Decisions

### Decision 1: Toggle endpoint (Path 2) + DevModeFilter (Path 1)

**Chosen**: Runtime API endpoint at `/api/v1/debug/logging` for per-module overrides, plus a static `DevModeFilter` for noise suppression.

**Alternatives considered:**
- *Env vars only*: Requires restart, slow iteration cycle. Rejected.
- *logging.Filter alone*: Good for static suppression but can't drill into specific modules without code changes.
- *Contextvars per-request*: Cleanest isolation but highest complexity. Unnecessary — the toggle is developer-scoped, not request-scoped.

**Rationale**: The two-layer approach separates concerns. The `DevModeFilter` handles known noise patterns (uvicorn access, redundant lines) unconditionally. The toggle endpoint provides the drill-in capability when a developer needs deeper visibility into a specific subsystem.

### Decision 2: In-memory override storage

**Chosen**: Simple `dict[str, int]` in a singleton `LogLevelManager` class. Resets on restart.

**Alternatives:**
- *Persist to DB/file*: Survives restarts but adds complexity and I/O. Restart clears overrides to a known state, which is arguably better for development.
- *SQLite*: Overkill for a temporary developer toggle.

**Rationale**: Dev tooling should be ephemeral. If you need DEBUG logging every session, set `LOG_LEVEL=DEBUG` in `.env`. The toggle is for surgical investigation.

### Decision 3: Stdlib `logging` only — no structlog/loguru

**Chosen**: `logging.Filter` subclass (`DevModeFilter`) + `LogLevelManager` helper. All stdlib.

**Alternatives:**
- *structlog*: Great for structured logging but adds a dependency and changes the logging interface across 181 call sites.
- *loguru*: Similar concern — library lock-in for a problem stdlib can solve.

**Rationale**: The fix is about *what* we log and *when*, not *how we format* it. Structured JSON output can be added later at the handler/formatter level without changing any of this work.

### Decision 4: Collapse retriever logging into a single structured event

**Chosen**: Replace 7 sequential `logger.info()` calls in `_retrieval.py` with a single call that bundles all context into one log message using a helper `log_structured()`.

**Format**: `log_structured("retrieval", "query", top_k=n, results=n, latency_ms=n, source=type)`

**Rationale**: These 7 lines are all describing the same operation from different angles. Bundling them preserves all information while eliminating 6 log line overhead per query. The structured helper makes parsing straightforward.

### Decision 5: Prompt hash + length instead of full dump

**Chosen**: At DEBUG level, log `prompt_hash=SHA256[:12], prompt_len=n_tokens` instead of the full prompt text.

**Rationale**: The full prompt dump is ~1,800 bytes — the single largest log entry per query. A truncated hash uniquely identifies the prompt for reproduction/debugging while reducing the entry by ~95%. If full prompt text is needed, add a `--dump-prompts` flag or log it to a separate file.

### Decision 6: Remove middleware "started" line, demote "completed" to DEBUG

**Chosen**: Delete `logger.info("Request started: ...")` from `MonitoringMiddleware`. Demote `logger.info("Request completed: ...")` to `logger.debug`.

**Rationale**: Uvicorn's access log already logs every request at INFO with method, path, status code, and latency. The middleware lines duplicate this with no unique value. Keeping "completed" at DEBUG preserves observability for debugging without adding per-request noise at INFO.

### Decision 7: Include chain_langchain.py in init log consolidation

**Chosen**: Apply the same consolidation pattern to `chain_langchain.py` — merge "Initializing QA chain" + "QA chain initialized in Xs" into a single structured event.

**Rationale**: Consistency. The LangChain QA chain initialization follows the same multi-line pattern as the retriever.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  LOGGING ARCHITECTURE                    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────────────────────────────┐            │
│  │       Toggle Endpoint (auth-gated)       │            │
│  │  GET  /api/v1/debug/logging → levels     │            │
│  │  PUT  /api/v1/debug/logging ← {mod:lvl} │            │
│  └──────────────────┬───────────────────────┘            │
│                     │                                    │
│                     ▼                                    │
│  ┌──────────────────────────────────────────┐            │
│  │         LogLevelManager (singleton)      │            │
│  │  _overrides: dict[str, int]              │            │
│  │  get_level(logger_name) → int | None     │            │
│  │  set_level(logger_name, level)           │            │
│  │  reset()                                 │            │
│  └──────┬─────────────────────────┬─────────┘            │
│         │                         │                      │
│         ▼                         ▼                      │
│  ┌──────────────┐    ┌──────────────────────┐            │
│  │ DevModeFilter │    │  Module-level filter │            │
│  │ (uvicorn)     │    │  (consults manager)  │            │
│  └──────────────┘    └──────────────────────┘            │
│                                                          │
│  ┌──────────────────────────────────────────┐            │
│  │     log_structured() helper function     │            │
│  │  log_structured("retrieval", "query",    │            │
│  │    top_k=5, results=3, latency_ms=42)    │            │
│  └──────────────────────────────────────────┘            │
│                                                          │
│  ┌──────────── module changes ──────────────────────┐   │
│  │  _retrieval.py:      9 lines → 1 log_structured() │   │
│  │  llm.py:             prompt dump → hash+len       │   │
│  │  middleware:          remove "started", D "completed"│  │
│  │  embedding.py:        INFO→DEBUG, consolidate     │   │
│  │  processor.py:        deduplicate branches        │   │
│  │  retriever init:      N lines → 1 structured      │   │
│  │  chain_langchain.py:  2 lines → 1 structured      │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Toggle endpoint is auth-gated but still an API surface** | Route is under `/api/v1/debug/` prefix. In production, block at the reverse proxy level. Document as dev-only. |
| **In-memory overrides reset on restart** | Documented behavior. If persistent overrides are needed, they belong in `.env`. |
| **Collapsing retriever lines loses information if the log format isn't parseable** | `log_structured()` uses `key=value` pairs in the message string. Machine-parseable without structured JSON. |
| **Removing prompt dump makes it harder to debug prompt issues** | Prompt hash identifies the exact prompt. If full dump is needed, developer can add a temporary `logger.debug(prompt)` or set `LLM_DEBUG_DUMP=1`. |
| **Middleware change breaks monitoring dashboards that parse "started" lines** | No such dashboards exist (dev environment). The uvicorn access log provides equivalent information. |

## Open Questions

- Should the toggle endpoint support regex patterns for module names (e.g., `retrieval.*` → DEBUG)?
- Should `DevModeFilter` be configurable via the toggle endpoint, or is static enough?
