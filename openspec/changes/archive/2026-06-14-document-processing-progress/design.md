## Context

The document processing pipeline (`src/domain/services/processor.py`) has three sequential stages: parsing, chunking, and saving (which includes per-chunk embedding + DB write). Currently progress is tracked as a single `processed_chars / total_chars` percentage that becomes meaningless after parsing finishes (100% instantly).

The existing Document model has these progress-related fields:

| Field | Purpose | Limitation |
|-------|---------|------------|
| `processing_step` | Current step name | Single string, no per-stage granularity |
| `processed_chars` | Chars processed | Set to `total_chars` after parsing, never changes after that |
| `total_chars` | Total chars | Only known after parsing |
| `chunk_count` | Total chunks | Only known after chunking |
| `processing_message` | Human-readable status | Text field, not machine-queryable |

**The core problem:** The pipeline has three distinctly paced stages (parsing is instant, chunking is fast, saving/embedding is slow), but progress is reported as a single number that doesn't reflect this. Users can't tell which stage is active or how far along it is.

## Goals / Non-Goals

**Goals:**
- Expose per-stage progress (`parsing_progress`, `chunking_progress`, `saving_progress`) in the API
- Show three independent progress bars in the document list, one per stage, each updating independently
- Show per-stage bars in the upload flow post-processing page
- Show per-stage progress summary in the Chat page processing warning
- Add a `saved_chunks` counter to the Document model so saving progress can be computed per-chunk

**Non-Goals:**
- Server-Sent Events or WebSocket-based real-time push (polling is sufficient)
- Breaking embedding out of the saving loop into its own stage (embedding is per-chunk, inline with saving)
- Per-operand progress within parsing (no "byte X of Y" — parsing is nearly instant and indeterminate display is fine)
- Per-operand progress within chunking (no "chunk X of Y" — chunk count unknown until chunking completes; indeterminate display is fine)

## Decisions

### Decision 1: Compute per-stage progress from existing fields + new `saved_chunks` counter

Per-stage progress is computed by a pure function that maps `(processing_step, saved_chunks, chunk_count)` to a dict of three `{0..100}` values.

```python
# Domain logic — NOT stored in DB, computed on read
def compute_stage_progress(
    processing_step: str | None,
    saved_chunks: int,
    chunk_count: int,
) -> dict[str, int]:
    """
    Returns {"parsing": 0..100, "chunking": 0..100, "saving": 0..100}
    
    Logic:
    - parsing: 100 if step is past parsing (chunking/saving/completed), else 0
    - chunking: 100 if step is past chunking (saving/completed), else 0
    - saving: computed from saved_chunks/chunk_count if step is "saving",
              100 if completed, 0 otherwise
    """
    p = {"parsing": 0, "chunking": 0, "saving": 0}
    
    if processing_step in ("chunking", "saving", "completed"):
        p["parsing"] = 100
    if processing_step in ("saving", "completed"):
        p["chunking"] = 100
    if processing_step == "saving" and chunk_count > 0:
        p["saving"] = min(100, int(100 * saved_chunks / chunk_count))
    elif processing_step == "completed":
        p["saving"] = 100
    
    return p
```

**Why computed-on-read vs stored:**
- All the source data already exists in the Document model (step, chunk_count) or is cheap to add (saved_chunks counter)
- No DB migration for progress columns needed (just one new column: `saved_chunks`)
- The computation is deterministic — there's no value in caching it
- Avoids the risk of progress columns getting out of sync with the actual step

**Why `saved_chunks` is needed:** Neither `chunk_count` nor `processing_step` alone tells us how many chunks have been saved so far. Currently "Saving chunk 12/42" is embedded in a text message — we need a numeric counter.

### Decision 2: Add `saved_chunks` column to Document model

A single new column on the `Document` model:

```python
saved_chunks: Mapped[int] = mapped_column(Integer, default=0)
```

Updated in the processor's save loop after each chunk batch:

```python
# In the save loop (currently every 10 chunks):
document.saved_chunks = i + 1  # or the actual count
await session.commit()
```

**Why a DB column vs. in-memory only:** Processing is async and the task could crash between chunk saves. A DB-persisted counter means the frontend can always see accurate progress, even after a restart.

### Decision 3: Three independent bars, not one weighted bar

The fundamental shift: instead of a single 0→100 bar that weights stages, show three stacked bars that each track their own stage:

```
Before:  [████████░░░░░░░░░░░░]  30% (phase-weighted, ambiguous)
After:
         📄 Parsing     [████████████████] 100% ✅
         ✂️ Chunking    [████████████░░░░]  80% 🔄
         🧠 Embed+Save  [░░░░░░░░░░░░░░░░]   0% ⏳
```

**Why three bars:**
- **Transparency**: Users see exactly which stage is active and how each is progressing
- **Honesty**: Parsing (100%) and chunking (100%) stay at 100% once done — no ambiguity
- **Debugging**: If saving is stuck at 30% for a long time, the user knows embedding is the bottleneck
- **No math**: No need to argue about weight allocations (is parsing really 10%? is saving really 70%?)

**Why vertical stacking vs. horizontal row:**
- Stage labels need readable space
- Progress bar widths are meaningful
- Streamlit renders vertical layouts more naturally
- Can be made compact with small bar heights (`st.progress(..., height=8)`)

### Decision 4: Parsing and chunking show indeterminate progress, then snap to 100%

Since neither parsing nor chunking has sub-operations with known counts:
- **Parsing**: The progress bar stays at 0% (indeterminate animation via `st.progress(..., text="Parsing...")`) until parsing completes, then snaps to 100%
- **Chunking**: Same pattern — stays at 0% (indeterminate) during chunking, then snaps to 100%

**Alternative considered:** Estimate parsing progress from file size (bytes read / file_size). Rejected because the parser reads the entire file at once — there's no streaming byte counter available. Adding one would be disproportionate complexity for a stage that completes in <1s for most documents.

### Decision 5: Auto-polling via `streamlit-autorefresh` with per-stage rendering

Same pattern as the original design: `st_autorefresh(interval=3000)` when processing documents exist. The difference is that the rendering loop now shows three bars per processing document instead of one.

```python
# Pseudocode for document list rendering
if any(d.status == "processing" for d in documents):
    st_autorefresh(interval=3000, key="doclist")

for doc in documents:
    with st.container():
        st.write(f"**{doc.title}**")
        if doc.status == "processing":
            # Three compact bars
            col1, col2, col3 = st.columns(3)
            with col1: _render_stage_bar("📄 Parse", doc.parsing_progress, completed_emoji="✅")
            with col2: _render_stage_bar("✂️ Chunk", doc.chunking_progress, completed_emoji="✅")
            with col3: _render_stage_bar("🧠 Save", doc.saving_progress, 
                                        detail=f"{doc.saved_chunks}/{doc.chunk_count}" if doc.saving_progress > 0 else None)
        else:
            st.write(f"Status: {doc.status}")
```

### Decision 6: API returns per-stage progress in both status and list endpoints

Both `GET /documents/{id}/status` and `GET /documents/` return the per-stage progress fields. The computation happens in the API layer (or a shared service function).

**Response schema addition:**
```python
class DocumentResponse(BaseModel):
    # ... existing fields ...
    parsing_progress: int = 0      # 0-100
    chunking_progress: int = 0     # 0-100
    saving_progress: int = 0       # 0-100
    saved_chunks: int = 0
```

**Why not a single nested dict (`stage_progress: dict`)?** Flat fields are easier for frontends to consume, more type-safe, and Swagger/OpenAPI generates better docs for them.

### Decision 7: Chat page warning shows per-stage status compactly

The Chat page warning uses a compact single-line format per document:

```
⚠️ Documents still processing:
📄 annual_report.pdf    📄✅  ✂️🔄 80%  🧠⏳
📄 q3_results.pdf       📄✅  ✂️✅     🧠🔄 60% (12/42)
```

**Why compact vs. full bars:** The Chat page is not a document management page — the warning is informational. Full bars would take too much vertical space. A compact stage-summary line is sufficient.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| `saved_chunks` counter could get out of sync if processor crashes mid-batch | The counter is updated in the same DB transaction as the chunk save. If the processor crashes, the current batch of 10 chunks is lost but the counter stays consistent with what's actually in the DB. On reprocessing, the counter is reset to 0. |
| Three bars per document takes more vertical space in the document list | Use compact bar height (`height=8` in st.progress). Completed stages collapse out of the bar display after a brief transition. Only processing docs get the multi-bar treatment. |
| Auto-polling every 3s creates flickering during other interactions | The polling is scoped to the document list page only. Streamlit's full rerun is fast for this page (~100ms). If the user is in the middle of an action (e.g., delete confirmation), the rerun preserves state. |
| Indeterminate parsing/chunking bars don't differentiate "working" from "stuck" | The `stage_detail` message provides context (e.g., "Parsing 2.3MB PDF..."). If a stage takes >10s without progress, the message reflects actual wall-clock time. |
| Frontend complexity — maintaining three bars per document is more code | The rendering is a helper function `_render_stage_bar()` called three times per row. The auto-polling logic is unchanged from the original design. |
