## Context

The api-docs query pipeline assembles context by joining `ChunkNode.content` strings with `\n\n` separators (module.py `_format_chunks`), then passes the result to a DSPy `ChainOfThought` module. The method chunk content (text_formatter.py `_format_method`) includes the function signature — with parameter names and types — but does NOT include parameter descriptions. Those descriptions live only in separate parameter-level chunks, which are lower-ranked and structurally disconnected from their parent method in the plain-text context.

The DSPy prompt template (`APIResponseGenerator` signature, signatures.py) instructs the LLM to produce "a comprehensive, step-by-step answer" but does not explicitly request parameter-level detail. With a small 1.5B model, the LLM needs more explicit guidance to include parameter names, types, descriptions, and usage patterns in its answers.

## Goals / Non-Goals

**Goals:**
- Method chunk content includes parameter names, types, and descriptions inline below the signature
- Metadata-based method fallback (`_meta_method`) also includes parameter descriptions
- The DSPy answer-generation prompt explicitly requests parameter-level detail
- A "how do I call this function?" type question produces answers that name the parameters and describe their purpose

**Non-Goals:**
- No changes to the chunk graph structure or retrieval pipeline
- No changes to how parameter chunks are formatted (they remain as separate nodes)
- No changes to the fallback (non-DSPy) prompt — it already works well enough
- No changes to existing API contracts or response schemas

## Decisions

### Decision 1: Inline param descriptions in method chunk content

**Chosen**: Modify `_format_method` to append parameter descriptions below the signature when `include_descriptions` is enabled.

Format:
```
FunctionName(param1: type1, param2: type2) -> ReturnType: Description
  param1 (type1): Description of param1
  param2 (type2): Description of param2
```

This ensures every method chunk is self-contained — the LLM sees parameter details even when child parameter chunks are not retrieved or are low-ranked. No structural changes to the chunk graph are needed.

**Alternatives considered:**
- **Keep separate parameter chunks and improve context assembly**: Adding parent expansion with structural labels (`--- Parameters for FunctionName ---`) would be more complex and still depend on parameter chunks being retrieved.
- **Inline params in the signature line**: e.g., `FuncName(param1: type1 - desc, param2: type2 - desc)` — makes signatures too long and hard to read.
- **No change (rely on existing parameter chunks)**: Doesn't work because parameter chunks are not reliably included in top-K retrieval results.

### Decision 2: Apply the same to `_meta_method` fallback

The metadata-based fallback at line 289 uses `param_count` from metadata. We'll also store param name/type/description arrays in metadata so the fallback can produce the same inline format. This ensures the improvement works when domain objects aren't available (e.g., during index rebuild from DB cache).

### Decision 3: Sharpen the DSPy prompt

Replace:
```
"A comprehensive, step-by-step answer that reasons through the API documentation."
```

With:
```
"A comprehensive answer that includes the exact function signatures, parameter names, types, descriptions, and how to use the API. Include step-by-step instructions when applicable. Only use information from the context — do not invent API details."
```

The key additions are: explicit mention of "parameter names, types, descriptions" and a grounding constraint. Small models benefit from explicit output guidance.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Longer method chunks reduce retrieval precision (more tokens = more noise in embedding) | Parameter descriptions add ~50-100 chars per described param. For typical functions with 2-5 params, this is 100-500 extra chars — modest compared to embedding dimension (768). |
| `_meta_method` metadata doesn't currently store per-param descriptions | The builder (builder.py) already stores `description`, `type_annotation` per parameter node. We need to store these in the metadata dict key for method nodes too. |
| DSPy prompt change affects ALL answers, not just parameter-related questions | The "parameter names, types, descriptions" instruction is additive — it only adds detail when parameters are present. It won't degrade answers for non-parameter questions. |
