## Context

The system has two built-in chunking strategies: "Default" (id: `default`, recursive engine) and "Semantic Chunking" (id: `semantic`, semantic engine). These are seeded on startup and stored in the `chunking_strategies` DB table. Currently:

- Strategies are **create-only** — no PATCH/PUT endpoint exists, so parameters are immutable after creation.
- The semantic chunking engine (`pdf_semantic_chunking/`) **ignores** the strategy's `chunk_size` and `chunk_overlap` fields. It uses hardcoded defaults (`min_tokens=200`, `max_tokens=800`, `overlap_ratio=0.10`) and per-element-type token limits in `ChunkAssembler.ELEMENT_TYPE_TOKEN_LIMITS`.
- The recursive chunking path **does use** strategy params (`chunk_size`, `chunk_overlap`, `separators`) — creating an inconsistency where the semantic path is less configurable than the recursive path.
- The `POST /documents` endpoint accepts a `strategy_id` but no parameter overrides. Users cannot tune parameters per-document.
- The frontend shows a read-only strategy dropdown with caption-only param display. No editing.
- Chat parameters (`data/chat_params.json`) already follow a "sticky defaults" pattern — load from JSON file, display in UI, allow editing, save on button click. Chunking parameters have no equivalent.

The `semantic-chunking-hyperlinks-toggle` change recently added `use_hyperlinks` as a strategy-level toggle, but that only addressed one parameter — the broader editability gap remains.

## Goals / Non-Goals

**Goals:**
- Rename `"default"` strategy to `"recursive"` (id and name), rename `"Semantic Chunking"` to `"Semantic"` (name only).
- Add `PATCH /strategies/{id}` endpoint so strategies are editable after creation.
- Introduce `ProcessingConfig` entity and DB table — a full copy of the effective processing parameters used per document.
- Modify `POST /documents` to accept optional override params (`chunk_size`, `chunk_overlap`, `separators`, `use_hyperlinks`) that merge with strategy defaults and are stored in `ProcessingConfig`.
- Wire `chunk_size` and `chunk_overlap` from `ProcessingConfig` through the processor into the semantic chunking engine, replacing hardcoded `ChunkAssembler` defaults.
- Replace per-element-type token limits (`ELEMENT_TYPE_TOKEN_LIMITS`) with strategy `chunk_size` as the sole hard maximum for all chunk types.
- Modify `POST /documents/{id}/reprocess` to accept new params and reprocess with current effective configuration.
- Add sticky defaults to the frontend: `data/chunking_params.json` file, editable params in upload sidebar, "Save as Defaults" button.

**Non-Goals:**
- Not changing the recursive chunking path behavior (it already uses strategy params correctly).
- Not adding per-document param overrides to the `Document` entity itself — `ProcessingConfig` is a separate table.
- Not removing the CLI `--min-chunk-size`/`--max-chunk-size`/`--overlap` flags (they remain as overrides when the CLI is used standalone).
- Not adding multi-user isolation for sticky defaults (follows same shared-file pattern as `chat_params.json`).
- Not removing the `embedding_model` or `engine_type` fields from strategy (they remain but are not user-editable through PATCH).

## Decisions

### Decision 1: ProcessingConfig as a full copy, not reference + overrides

Chosen over a diff/override model. The `ProcessingConfig` table stores the complete set of effective parameters as a snapshot at processing time.

**Why**: Processor reads a single row with no merge logic. No risk of strategy changes retroactively affecting processed documents. Simpler to reason about, test, and debug.

**Alternative considered**: Reference to strategy + overrides column (JSON diff). Rejected because it adds a merge step at processing time and makes it harder to audit exactly what parameters were used for a given document.

### Decision 2: Per-element-type limits replaced by strategy chunk_size

The semantic engine's `ELEMENT_TYPE_TOKEN_LIMITS` dict (function 400-800, property 150-400, etc.) is removed. Strategy `chunk_size` becomes the sole hard maximum for all chunk types.

**Why**: The user explicitly chose this. It simplifies the semantic engine. Users who want tighter limits for certain types can lower `chunk_size`. The per-element-type limits added complexity without providing meaningful control — they were essentially hardcoded heuristics that users couldn't tune.

**Alternative considered**: Keep per-element-type limits but scale them proportionally to strategy `chunk_size`. Rejected as over-engineering; the user wants a single knob.

### Decision 3: PATCH /strategies/{id} for mutability (not PUT)

Chosen over a full-replacement PUT endpoint. PATCH accepts partial updates — only the fields sent are modified.

**Why**: Partial updates are safer and more ergonomic. A PUT that requires all fields creates a risk of accidentally resetting unspecified fields to defaults. PATCH maps naturally to the frontend's "edit individual sliders" UX.

### Decision 4: Sticky defaults shared file (same pattern as chat_params)

Chosen over a user-preferences DB table. The file `data/chunking_params.json` stores last-used values per strategy type, loaded on page start.

**Why**: Follows the established pattern. The chat_params.json approach works well and is already understood. No backend changes needed for the sticky defaults feature. Users don't need per-user isolation at this stage.

**Alternative considered**: Backed user preferences via `PUT /user/preferences` endpoint on the API. Rejected as premature — the file-based approach is simpler and sufficient for the current scale.

### Decision 5: ProcessingConfig is created at upload time, linked to document

The `POST /documents` endpoint creates a `ProcessingConfig` record with the effective params and stores its ID on the `Document` record. The processor reads from `ProcessingConfig`.

**Why**: Decouples processing configuration from strategy entity. A document's processing config is immutable after creation — it's a historical record of what was used. Future reprocessing creates a new `ProcessingConfig`.

### Decision 6: Reprocessing creates a new ProcessingConfig

When reprocessing, the user can specify new override params. A new `ProcessingConfig` record is created, linked to the document. The old one is retained (or optionally cleaned up).

**Why**: Keeps a clean audit trail of what params were used for each processing run. The document's `current_processing_config_id` always points to the latest.

## Risks / Trade-offs

- **[Migration risk]** Existing documents using `"default"` strategy ID must be migrated to `"recursive"`. Mitigation: migration runs at startup, targets only rows with `chunking_strategy_id="default"`, and logs warnings on failure.
- **[Breaking change]** API consumers sending `strategy_id: "default"` will fail after migration. Mitigation: the migration creates the `"recursive"` row and migrates documents; the old `"default"` row is removed. API error messages will guide consumers to use `"recursive"`.
- **[Per-element-type removal]** Existing chunks were produced with the old per-element-type limits. Only newly processed documents will use the new single `chunk_size` behavior. Existing chunks retain their original embeddings. Mitigation: acceptable — this is a forward-looking change.
- **[File-based sticky defaults]** Shared file means all users on the same machine share the same defaults. Mitigation: same limitation as `chat_params.json` — acceptable for current usage patterns.
- **[ProcessingConfig growth]** Every document processing and reprocessing creates a new `ProcessingConfig` row. For very high document volumes, this table could grow. Mitigation: the table is small (one row per processing event) and can be pruned if needed.
