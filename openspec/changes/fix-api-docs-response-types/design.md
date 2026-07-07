## Context

The `ApiDocQueryResponse` model defines `relevant_functions: list[str]` and `relevant_types: list[str]` fields intended to surface structured metadata about which API identifiers the answer relates to. The frontend already renders these fields as expandable sections when non-empty (per `api-docs-frontend` spec), but they are always empty because the backend never populates them.

The codebase has two query paths:
1. **`_query_fallback`** (fallback path — used when DSPy is disabled or when DSPy generation fails): collects `seen_functions` from `function_name`/`name` metadata and `seen_types` from `type_name` metadata, but omits `interface_name` entirely.
2. **`_query_dspy`** (DSPy path): relies on the local LLM to output `relevant_functions` and `relevant_types` as structured output fields. Small models (Qwen2.5-1.5B, Phi-4-mini) frequently skip auxiliary fields in favor of the main answer text.

The chunk graph (built from DOCX API docs) contains many **interface** nodes (kind=`"interface"`), which have `interface_name` in metadata but neither `function_name` nor `type_name`. These nodes are the most common top-level entity in any API doc, so their omission leaves the response fields effectively empty.

## Goals / Non-Goals

**Goals:**
- Populate `relevant_functions` in `ApiDocQueryResponse` with function names from retrieved chunks
- Populate `relevant_types` in `ApiDocQueryResponse` with type names AND interface names from retrieved chunks
- Ensure the DSPy path also produces populated lists (not just the fallback path)
- All behavior changes are backward-compatible — existing consumers see richer data, not a different schema

**Non-Goals:**
- No changes to the `ApiDocQueryResponse` schema or any Pydantic model
- No new API endpoints or query parameters
- No changes to the frontend (it already handles non-empty lists)
- No changes to the chunking, extraction, or graph-building pipeline

## Decisions

### Decision 1: Add `interface_name` to `seen_types` in `_query_fallback`

**Chosen**: Add `interface_name` to the `seen_types` set when `interface_name` is non-empty and not already present.

- **Rationale**: Interface names are conceptually "types" — they define the type system of the API. Grouping them with `type_name` under `relevant_types` is semantically correct. The `interface_name` metadata is already present on every source and is already passed to `ApiDocSource.interface_name` — it simply was never aggregated.
- **Implementation**: One conditional block after line 483 in `manager.py`:
  ```python
  if interface_name and interface_name not in seen_types:
      seen_types.add(interface_name)
  ```
- **Alternatives considered**:
  - *Add to `seen_functions`*: Rejected — interfaces are not functions.
  - *Add a separate `relevant_interfaces` field*: Would require schema changes, frontend changes, and spec changes. Over-engineered for this fix. The `relevant_types` field is semantically broad enough.

### Decision 2: Post-hoc extraction fallback in `_query_dspy`

**Chosen**: After the DSPy predictor returns a result, if `relevant_functions` or `relevant_types` are empty, extract them from the resolved sources by scanning metadata — exactly the same logic as `_query_fallback`.

- **Rationale**: The DSPy path already resolves sources from `primary_chunk_id` via graph traversal. Those sources have the same metadata structure (`function_name`, `name`, `type_name`, `interface_name`) as in the fallback path. Performing extraction from sources is deterministic and reliable, unlike relying on the small LLM's structured output. This also ensures behavioral consistency between the two paths.
- **Implementation**: In the common DSPy code path (around line 640-641 of `manager.py`), after mapping `result["relevant_functions"]` and `result["relevant_types"]`, check if either is empty and apply fallback:
  ```python
  if not relevant_functions or not relevant_types:
      sources = [... from the pipeline result ...]
      for src in sources:
          ... # same per-source extraction as _query_fallback
  ```
- **Alternatives considered**:
  - *Improve the DSPy prompt*: Worth doing but insufficient alone — small LLMs fundamentally struggle with multi-field structured outputs.
  - *Replace with pure extraction, no DSPy*: Defeats the purpose of having the DSPy pipeline for answer quality.
  - *Use a larger model for structured output*: Not feasible — model is constrained by local hardware (MLX, ~500MB-2GB models).

### Decision 3: Deduplication via sets

Both `_query_fallback` and the post-hoc extraction use Python `set()` for deduplication before returning `sorted()`. This is simple and preserves the existing pattern in `_query_fallback`. No change needed.

## Risks / Trade-offs

- **[Duplicate entries]**: Both DSPy output and post-hoc extraction could produce the same values. Mitigation: the set-based deduplication handles this naturally. The DSPy path still runs first; if it returns partial results, the extraction fills in missing values without doubling.
- **[Performance]**: Post-hoc extraction iterates over sources an additional time. Mitigation: the source list is bounded by `top_k` (default 10, max 50) and the iteration is O(n) over a small array. Negligible cost.
- **[Semantic blurring]**: Adding `interface_name` to `relevant_types` might confuse consumers who expect "types" to mean only `type_name` (error codes, records, enums). Acceptable — interfaces define type structures in the API, and the field name "relevant_types" is intentionally broad in the schema.

## Open Questions

- Should `interface_name` that duplicates `type_name` be filtered out? Currently the set deduplication handles exact duplicates, but a method could appear in both an interface and have its own `function_name`. This is fine — the method name goes in `relevant_functions` and the interface name goes in `relevant_types`. They describe different concerns.
