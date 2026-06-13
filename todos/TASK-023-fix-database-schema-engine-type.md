---
id: TASK-023
status: completed
priority: high
created: 2026-06-13
completed_at: 2026-06-13
---

Fix database schema: add missing `engine_type` column to ChunkingStrategy model

- [x] Add `engine_type` column to `ChunkingStrategy` DB model (`VARCHAR`, default `"recursive"`, nullable) with Alembic migration
- [x] Update system seed in `src/api/main.py` — set `engine_type="semantic"` for "API Documentation" strategy
- [x] Modify `src/domain/services/processor.py` — add routing logic: when `strategy.engine_type == "semantic"`, call semantic chunker
