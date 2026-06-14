## Why

Users have no visibility into what stage of document processing is happening. The current progress bar uses `processed_chars / total_chars`, which jumps 0→100% as soon as parsing finishes — meaning the bar is stuck at 100% during the entire chunking and embedding phase where the real work happens. A user watching their document upload sees an empty bar, then a full bar, then nothing for potentially minutes. They don't know if the system is still working, what step it's on, or how much longer it will take.

## What Changes

- **Per-stage independent progress bars** — instead of one combined phase-weighted bar, show three independent bars: one for each pipeline stage (parsing, chunking, embedding/saving). Each bar tracks its own stage independently: completed stages show 100%, the active stage shows real sub-progress, and future stages show "waiting."
- **Parsing stage gets file-based progress** — show indeterminate progress during parsing (since sub-step granularity isn't available), moving to 100% when parsing completes
- **Chunking stage gets indeterminate progress** — show a spinner/progress animation during chunking (total chunks aren't known until after chunking completes), then 100%
- **Embedding+saving stage gets per-chunk progress** — each chunk's embedding computation and DB write are tracked together, showing `i/N` chunks processed
- **API returns per-stage progress** — instead of a single `progress_pct`, expose per-stage progress so the frontend can render independent bars
- **Accordion/expandable detail view** — the per-stage bars can be compact or expanded with chunk-level detail

## Capabilities

### New Capabilities
- `document-progress-indicator`: Per-stage progress tracking on the backend (processor + API) and per-stage progress bar display on the frontend (document list auto-polling, stage bars with detail, chat-page processing warning)

### Modified Capabilities
None. No existing spec-level requirements are changing.

## Impact

- **`src/domain/services/processor.py`** — Replace single `progress_pct` with per-stage progress tracking. Add stage-level progress computation in `update_document_progress()`. Store stage progress data on the Document model (new columns or computed).
- **`src/api/routes/documents.py`** — Return per-stage progress data from status and list endpoints
- **`src/api/schemas/document.py`** — Add per-stage progress fields to `DocumentResponse` (e.g., `stage_progress: dict` or separate fields like `parsing_progress`, `chunking_progress`, `saving_progress`)
- **`client/pages/4_📁_Documents.py`** — Replace single progress bar with per-stage bars. Add auto-polling. Show stage labels with emojis.
- **`client/pages/3_💬_Chat.py`** — Update processing warning to show per-stage progress for selected docs
- **`src/infrastructure/database/models.py`** — Optionally add per-stage progress columns to `Document` model (or compute from existing data)
