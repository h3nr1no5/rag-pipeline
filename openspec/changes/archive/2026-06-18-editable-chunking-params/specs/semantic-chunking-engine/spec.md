## MODIFIED Requirements

### Requirement: Assemble chunks with configurable size and overlap constraints

The system SHALL assemble final chunks from the bounded segments, enforcing configurable `chunk_size` (in tokens) and `chunk_overlap` between adjacent chunks, and merging of undersized adjacent segments. The `chunk_size` and `chunk_overlap` values SHALL come from the document's `ProcessingConfig` (or directly from the strategy when no config exists), replacing all previously hardcoded per-element-type defaults. The `min_chunk_size` SHALL be derived as 25% of `chunk_size`.

#### Scenario: Use strategy chunk_size as hard max for all chunk types
- **WHEN** processing a document via the semantic chunking engine
- **THEN** the system SHALL use `ProcessingConfig.chunk_size` as the maximum token count for all chunks, regardless of element type
- **AND** SHALL derive `min_chunk_size` as `max(50, chunk_size // 4)` tokens
- **AND** SHALL compute token count using the same tokenizer as the embedding model (e.g., `cl100k_base` for `text-embedding-3-large`)
- **AND** the `ELEMENT_TYPE_TOKEN_LIMITS` map (previously `{function: (400, 800), property: (150, 400), ...}`) SHALL be removed

#### Scenario: Use strategy chunk_overlap for overlap between chunks
- **WHEN** `ProcessingConfig.chunk_overlap` is set to a positive value
- **THEN** the system SHALL compute overlap ratio as `chunk_overlap / chunk_size`
- **AND** SHALL append the last `chunk_overlap` tokens of chunk N to the beginning of chunk N+1
- **AND** the overlap SHALL NOT cross a hard boundary (heading, function signature, enum block)
- **AND** for COM chunks, the overlap SHALL include the interface header or introduction context (1-2 sentences) when relevant

#### Scenario: Never split atomic COM constructs
- **WHEN** a bounded segment contains a complete COM construct (function signature + parameter descriptions + return value)
- **THEN** the system SHALL NOT split it, even if it exceeds `chunk_size`
- **WHEN** a bounded segment contains an entire `enum { ... }` block
- **THEN** the system SHALL NOT split it
- **WHEN** a bounded segment contains a complete record/struct definition
- **THEN** the system SHALL NOT split it
- **AND** the hard maximum for atomic constructs SHALL be 2x `chunk_size` — beyond that, log a warning and split at the outermost structural boundary

#### Scenario: Merge undersized adjacent chunks
- **WHEN** two adjacent bounded segments are each smaller than `min_chunk_size` (derived as `max(50, chunk_size // 4)` tokens)
- **THEN** the system SHALL merge them into a single chunk
- **AND** SHALL concatenate their content with a double newline separator

#### Scenario: Enforce maximum chunk size
- **WHEN** a bounded segment exceeds `chunk_size`
- **THEN** the system SHALL recursively split it at the next available structural boundary (subheading, paragraph break, line break)
- **AND** SHALL NOT split mid-sentence or mid-code-line

### Requirement: Accept chunk_size and chunk_overlap from processor

The async Python API and CLI SHALL accept `chunk_size` and `chunk_overlap` parameters from the caller (the processor or CLI invocation), instead of relying on hardcoded defaults.

#### Scenario: Async API accepts chunk_size and chunk_overlap
- **WHEN** `chunk_pdf(file_path, chunk_size=600, chunk_overlap=80)` is called from Python
- **THEN** the system SHALL pass these values to the `ChunkAssembler` as `max_tokens` and overlap configuration
- **AND** SHALL use the provided values instead of any internal defaults
- **AND** SHALL fall back to `chunk_size=800`, `chunk_overlap=80` if no values are provided (backward compatibility)

#### Scenario: CLI passes through --chunk-size and --chunk-overlap
- **WHEN** the CLI is invoked as `python -m src.pdf_semantic_chunking.cli input.pdf --chunk-size 600 --chunk-overlap 80`
- **THEN** the system SHALL use these values instead of defaults
- **AND** SHALL accept the existing `--min-chunk-size`, `--max-chunk-size`, and `--overlap` flags as aliases for backward compatibility (with `--chunk-size` and `--chunk-overlap` taking precedence)

## ADDED Requirements

### Requirement: Processing statistics include chunk_size source

The processing statistics SHALL report which `chunk_size` and `chunk_overlap` values were actually used during chunking, to aid debugging.

#### Scenario: Stats report effective parameters
- **WHEN** chunking completes
- **THEN** the `stats` dict SHALL include `effective_chunk_size` and `effective_chunk_overlap` keys showing the values used during processing

## REMOVED Requirements

### Requirement: Apply per-element-type token-based size defaults for COM chunks

**Reason**: Replaced by a single `chunk_size` value from the strategy/ProcessingConfig that applies uniformly to all chunk types. Per-element-type token limits (function 400-800, property 150-400, etc.) added complexity without providing meaningful user control.

**Migration**: Remove `ELEMENT_TYPE_TOKEN_LIMITS` dict from `ChunkAssembler`. All chunk types use `chunk_size` as the hard max. The `min_chunk_size` is derived as `max(50, chunk_size // 4)`.
