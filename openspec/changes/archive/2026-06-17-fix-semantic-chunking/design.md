## Context

The semantic chunking pipeline (`src/pdf_semantic_chunking/`) was designed for COM API documentation (e.g., AxisVM PDFs with `[ComImport]`, `interface I*`, C# signatures). It uses a `PdfminerParser` → `COMEnricher` → `BoundaryDetector` → `ChunkAssembler` pipeline. When applied to non-COM PDFs (general technical reports, whitepapers):

- `COMEnricher` finds nothing → all elements get `com_confidence=0.0`
- `BoundaryDetector` relies on COM patterns + heading font size >14pt → typically finds 0-2 boundaries
- `ChunkAssembler` with 0 boundaries → all elements in 1-2 segments → 1-2 chunks

Additionally, the `ChunkingStrategy` parameters (`chunk_size`, `chunk_overlap`, `separators`) are ignored by the semantic pipeline. Line 189 of `processor.py` calls `semantic_chunk_pdf(file_path)` with no kwargs, while the pipeline internally uses hardcoded defaults (200-800 tokens, 10% overlap).

The existing spec at `openspec/specs/semantic-chunking-engine/spec.md` already defines "Graceful degradation on poorly structured input" (Requirement 6, lines 179–191) with scenarios for paragraph-boundary fallback and size-based splitting, but these are not implemented in code. The `HeadingBoundaryDetector` only recognizes `HEADING`-typed elements with font_size >14 or >18 pt, plus markdown `#` prefixes — missing all-caps lines, numbered sections, and short structural lines common in non-COM documents.

## Goals / Non-Goals

**Goals:**
- Make the semantic pipeline produce multiple chunks from non-COM PDFs when appropriate
- Make `ChunkingStrategy.chunk_size` and `chunk_overlap` actually control the semantic pipeline's output
- Improve heading detection to cover more heading patterns (all-caps, numbered, short structural lines)
- Maintain zero regression for COM-enriched documents (existing boundary detection must continue working as-is)

**Non-Goals:**
- Not building a general-purpose "semantic understanding" chunker — the fallback is purely size-based
- Not changing the COM enrichment pipeline or its boundary priority rules
- Not adding new API endpoints or CLI flags
- Not changing the recursive chunking path (non-semantic `engine_type`)

## Decisions

### Decision 1: Pass strategy params via kwargs (Fix A)

**Approach:** Modify `processor.py` line 189 to pass `min_chunk_size`, `max_chunk_size`, and `overlap` derived from the strategy's `chunk_size` and `chunk_overlap`:

```python
semantic_result = await semantic_chunk_pdf(
    file_path,
    min_chunk_size=max(50, chunk_size // 4),
    max_chunk_size=chunk_size // 2,
    overlap=int(chunk_overlap / chunk_size * 100) if chunk_size > 0 else 10,
)
```

The pipeline already supports these kwargs in `cli.py` → `build_pipeline(kwargs)` → `ChunkAssembler(min_tokens=..., max_tokens=..., overlap_ratio=...)`.

**Rationale:** The `api.py` and `cli.py` already accept `**kwargs` and pass them down. The gap is only in the caller. Mapping `chunk_size` (character-based, from `ChunkingStrategy`) to the semantic pipeline's `max_tokens` (word-based) requires a heuristic. Using `chunk_size // 2` approximates tokens from characters (roughly 1 word = 5 chars on average, then halved for safety since the semantic pipeline already has `min_tokens`/`max_tokens` per element type). The per-element-type limits (e.g., "mixed": 200-600) act as a floor via `max(min_t, self.min_tokens)`, so passing smaller values won't produce tiny chunks for COM-classified elements.

**The real value of Fix A is for non-COM documents:** when `element_type="mixed"` and no COM enrichment, the per-type limits are (200, 600). The passed `max_chunk_size=250` (for default strategy `chunk_size=500`) gives `max_t = max(600, 250) = 600`. So Fix A alone has limited direct effect on COM docs — but it sets up the parameter plumbing for future tuning.

### Decision 2: Token-count fallback in ChunkAssembler (Fix B)

**Approach:** After boundary-based segment creation in `assemble()` (line 64), check: if `len(segments) <= 2` and the flat element count `> 3`, create new segments using a token-count paragraph split that targets `max_tokens` per segment:

```python
if len(segments) <= 2 and len(flat) > 3:
    segments = self._fallback_paragraph_split(flat)
```

The `_fallback_paragraph_split` method iterates elements, grouping them until exceeding `max_tokens`, then starting a new segment. It's simple, predictable, and guaranteed to produce multiple chunks from non-COM documents.

**Rationale:** The existing `_split_oversized()` method only handles chunks that exceed 2× `max_tokens` — it never triggers when content is already in 1-2 segments under the limit. A new stage-level fallback (before per-chunk processing) is needed. Alternatives considered:

- **Heuristic boundary injection** — inserting artificial boundaries at every Nth element. Rejected because it's fragile across different PDF extraction qualities.
- **Paragraph-markup-based split** — using blank-line paragraph detection. Our elements from pdfminer are already small paragraphs; a token-count split is equivalent and simpler.
- **Increasing the COM confidence threshold lower** — wouldn't help because COMEnricher doesn't run on non-COM content; there are no low-confidence COM elements to salvage.

This fallback is intentionally conservative: it only triggers when boundary detection produces ≤2 segments from >3 elements. For COM documents with working boundary detection (producing 10+ segments), the fallback never activates.

**Caveat:** `_fallback_paragraph_split` processes the flat element list after `_strip_root()`. It doesn't use the document tree hierarchy. For deeply nested docs where hierarchy matters, the semantic boundary detection should already be working, so this shouldn't be an issue.

### Decision 3: Improve heading detection patterns (Fix C)

**Approach:** Extend `HeadingBoundaryDetector.detect()` with three new heuristics:

1. **All-caps short lines** (5 < len < 100, fully uppercase, no trailing period): Common in technical docs for section titles. Priority 75.0.
2. **Numbered section headers** matching `^[A-Z0-9][\.\)]\s+` (e.g., "1. ", "A) ") or Roman numerals `^[IVXLCDM]+\.\s+` (e.g., "II. "). Priority 85.0.
3. **Short lines without terminal punctuation** (10 < len < 80, no `.` `:` `!` `?` at end): Catches structural headings that aren't uppercase or numbered. Priority 60.0 (lower to avoid false positives in body text).

**Rationale:** The existing detector only uses `el.type == "HEADING"` (from pdfminer font classification) and checks font_size >14/18. Many PDFs don't use distinct heading fonts — they use bold at 12pt for headings. The new rules are purely content-based and independent of pdfminer's element type classification. Priority values are set higher for numbered headers (more likely true positives) and lower for "short line" (more likely ambiguous).

**Risk:** The short-line rule (priority 60) may produce false positives on short body text lines. The priority system in `BoundaryDetector.detect()` de-duplicates by index and prefers higher-priority markers, so a false-positive short-line marker at index 60 would be discarded if a COM signature marker (priority 100) exists at the same index. For non-COM docs with no other markers, some false splits are acceptable since the fallback (Fix B) would otherwise split by pure token count — heading-based splits are more meaningful even if imperfect.

### Decision 4: No spec file changes needed

The existing `semantic-chunking-engine/spec.md` already defines the graceful degradation requirements (lines 179–191). The implementation is simply catching up to the spec. No new spec capabilities are being introduced. The modified requirements are implementation only — the spec requirements for fallback behavior remain unchanged.

Nonetheless, a delta spec should be created in the change's `specs/` directory to document what changed from an implementation perspective, making it clear that these scenarios are now operational.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Fix B activates for COM docs with very few boundaries** (e.g., a short COM doc with only 1-2 functions) | Low — real COM docs have hundreds of functions → many boundaries | Fallback produces token-based instead of semantic chunks | Trigger threshold is `≤2 segments AND >3 elements`. COM docs with 3+ segments are unaffected. Test with real COM PDF. |
| **Fix C all-caps rule fires on abbreviated body text** | Medium — e.g., "API" or "HTTP" on its own line in body text | Extra chunk boundaries in middle of prose | Priority 75 is below heading priority 80-90, so real headings win. For non-COM docs, extra boundaries are better than none. |
| **Fix A mapping of chunk_size to token limits is too crude** | Low | Strategy params don't translate well | The per-element-type limits floor the values, preventing truly broken behavior. Improvement over "params have no effect at all." |
| **Regression in existing tests for COM docs** | Very low — Fixes B and C only activate when boundaries are sparse/absent | Failing integration tests | Run existing tests before/after. The fallback explicitly checks segment count and won't trigger for COM docs with many segments. |
| **Fix C short-line rule captures too many elements** | Low | Chunks become too small | Priority 60 is the lowest. If too aggressive, can be tuned down or removed. |

## Migration Plan

No migration needed. Changes are isolated to the semantic chunking pipeline. Existing documents in the database are unaffected (chunks are created at upload time, not retroactively).

**Rollback:** Revert the 3 file changes. No data migration needed.

## Open Questions

*(none)*
