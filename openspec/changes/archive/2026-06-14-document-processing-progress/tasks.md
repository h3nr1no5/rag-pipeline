## 1. Backend — `saved_chunks` Counter

- [x] 1.1 Add `saved_chunks: Mapped[int] = mapped_column(Integer, default=0)` to the `Document` model in `src/infrastructure/database/models.py`
- [x] 1.2 Update the save loop in `processor.py` (`process_document_async()`) to increment `document.saved_chunks` after each chunk batch (currently every 10 chunks + last chunk)
- [x] 1.3 Reset `saved_chunks = 0` in the reprocess and clear-embeddings handlers in `src/api/routes/documents.py`
- [x] 1.4 Generate and run the Alembic migration for the new column (or use `Base.metadata.create_all` if not using migrations)

## 2. Backend — `compute_stage_progress()` Function

- [x] 2.1 Implement `compute_stage_progress(processing_step, saved_chunks, chunk_count) -> dict` as a pure function in `src/domain/services/processor.py` (or a new `src/domain/services/progress.py` module)
- [x] 2.2 Handle edge cases: `None` step (pending doc returns all 0), `chunk_count=0` during saving (return 0, not division by zero), completed status (all 100)
- [x] 2.3 Write unit tests for the function covering all step transitions and edge cases

## 3. Backend — API Schema and Endpoint Updates

- [x] 3.1 Add `parsing_progress`, `chunking_progress`, `saving_progress`, `saved_chunks` fields to `DocumentResponse` in `src/api/schemas/document.py`
- [x] 3.2 In the `GET /documents/{id}/status` handler, call `compute_stage_progress()` and include the per-stage fields in the response
- [x] 3.3 In the `GET /documents/` list handler, call `compute_stage_progress()` for each document before returning the list
- [x] 3.4 Optionally keep or remove the old `progress_pct` field (deprecate if removing, to avoid breaking existing frontend code mid-transition)

## 4. Frontend — Document List Per-Stage Progress Bars

- [x] 4.1 Create a reusable `render_stage_bar()` helper function in the client code that renders a single compact progress bar for a stage (label, emoji, percentage, optional detail text)
- [x] 4.2 In `client/pages/4_📁_Documents.py`, update the processing-document row rendering to show three stacked stage bars instead of one combined bar
- [x] 4.3 Implement the stage bar layout: parsing bar (📄), chunking bar (✂️), embed+save bar (🧠) with compact `st.progress(..., height=8)`
- [x] 4.4 Show indeterminate state for parsing/chunking stages when they're active (0% but marked as "in progress")
- [x] 4.5 Show chunk detail text (e.g., "12/42 chunks") during the saving stage
- [x] 4.6 Ensure auto-polling (`st_autorefresh`) fires only when at least one document has status "processing"
- [x] 4.7 Handle the transition from processing → completed: show all bars at 100% briefly, then collapse to the standard completed badge

## 5. Frontend — Upload Flow Per-Stage Progress

- [x] 5.1 In the `wait_for_processing()` function in `Documents.py`, replace the single progress bar with three per-stage bars
- [x] 5.2 Update the polling loop to use the new per-stage fields from the status endpoint
- [x] 5.3 Show the same indeterminate/snapping behavior for parsing and chunking stages during upload

## 6. Frontend — Chat Page Processing Warning

- [x] 6.1 In `client/pages/3_💬_Chat.py`, update the document status check logic to fetch per-stage progress fields
- [x] 6.2 Update the warning banner to show a compact per-stage status line for each processing document (e.g., `📄✅ ✂️🔄 80% 🧠⏳`)
- [x] 6.3 Maintain the existing polling pattern (`time.sleep(2)` loop with `st.empty()`) but update the displayed content to reflect per-stage data

## 7. Testing

- [x] 7.1 Unit tests for `compute_stage_progress()` — all stage transitions, zero/chunk_count edge cases, None step
- [x] 7.2 Integration test for `GET /documents/{id}/status` — verify per-stage fields present and correct at each processing step
- [x] 7.3 Integration test for `GET /documents/` — verify per-stage fields present in list response
- [x] 7.4 Integration test for reprocess flow — verify `saved_chunks` resets to 0 and per-stage fields start at 0
