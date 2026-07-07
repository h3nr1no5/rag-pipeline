## Context

Parameter hallucination in the API docs RAG pipeline has three remaining causes after the extraction fix (54eb9a7) and DSPy prompt enhancement (516a265, 12c8af0):

1. **Advisory assertions**: `_generate_with_assertions()` runs `validate_citations()` and `check_question_references()` but returns the CoT output regardless of results. Assertions at `module.py:449-467` are logged but never acted on.

2. **Blind fallback prompt**: `_generate_answer()` at `manager.py:762-774` uses a generic prompt ("Use EXACT values from context. Do not invent names.") that never explicitly requests parameter-level detail. The method chunk content now includes param descriptions (from 12c8af0), so the data *is* in context — the prompt just doesn't instruct the LLM to use it.

3. **BM25 keyword blind spot**: `ApiBm25Index._build_keyword_text()` at `bm25_index.py:143-147` builds method-level keyword text from `interface_name`, `function_name`, `name`, `return_type`, and top-level `description` — but not the per-parameter names and descriptions stored in the `parameters` metadata list. BM25 can't match queries about parameter semantics; only the embedding index can, creating a retrieval gap when embedding similarity is noisy.

4. **No parameter-level answer validation**: The `ResponseVerifier` at `verification.py` performs sentence-level semantic similarity verification using a cross-encoder, but does not verify that parameter names and descriptions cited in the answer actually match the source documentation. An LLM can describe a parameter with fabricated details and no check catches it.

## Goals / Non-Goals

**Goals:**

- Make assertion failures actionable — retry or provide a structured fallback when citations are invalid
- Update the fallback prompt to request parameter names, types, and descriptions
- Index per-parameter descriptions in BM25 keyword text for method nodes
- Add answer-level validation that parameter claims (name + description) match source chunks
- Do not degrade response latency for the happy path (assertions pass)

**Non-Goals:**

- No changes to the DSPy `APIResponseGenerator` signature (already enhanced in 516a265)
- No changes to the chunk graph builder or text formatter (already done in 12c8af0)
- No changes to the cross-encoder reranker or embedding index
- No changes to MAX_CONTEXT_CHUNKS (the 10-chunk limit is deliberate for latency)
- No cross-document context boundary enforcement (addressed by existing doc_id filtering)

## Decisions

### Decision 1: Assertion retry — three-strike strategy

**Approach**: Replace the advisory-only assertion pattern at `module.py:449-467` with a three-strike strategy:

1. **Strike 1 (CoT)**: Run `response_generator` (ChainOfThought) as today. Validate assertions.
2. **Strike 2 (Predict)**: If assertions fail, run `fallback_generator` (plain Predict) — already exists. Validate again.
3. **Strike 3 (structured fallback)**: If Predict also fails assertions, return a structured answer listing the available functions and types from context, instead of returning hallucinated content.

**Rationale**: The plain Predict fallback already exists in `_generate_fallback()`. The current code reaches it only when CoT *crashes* (exception), but not when assertions *fail*. The three-strike approach adds minimal code: a fallthrough path from CoT to Predict on assertion failure, and a structured fallback for the final strike.

**Alternative considered**: Re-run generation with a strengthened prompt on each retry. Rejected because it adds complexity and latency. The Predict fallback already exists and is designed for this purpose.

### Decision 2: Fallback prompt — append parameter detail instruction

**Approach**: Add one sentence to the prompt at `manager.py:770`: "For each function you mention, include its parameter names, types, and descriptions from the context."

**Rationale**: Minimal change (single line), zero architectural impact. The context already contains param descriptions (from 12c8af0) — this just tells the LLM to use them.

### Decision 3: BM25 method keyword text — flatten parameters metadata

**Approach**: In `ApiBm25Index._build_keyword_text()` at `bm25_index.py:143-147`, after the existing parts for the `"method"` kind, iterate the `m.get("parameters", [])` list and append each parameter's `name` and `description` to `parts`.

**Current output** (method chunk): `"IFacadeReflectiveCatalog AddFromCatalog AddFromCatalog long Description text..."`
**After change**: `"IFacadeReflectiveCatalog AddFromCatalog AddFromCatalog long CrossSectionName CrossSectionShape Name of cross-section Shape of the cross-section Description text..."`

**Rationale**: Simple additive change. The `parameters` metadata is already present in method chunk nodes (set by `ChunkGraphBuilder._add_method_node()`). No schema changes needed.

**Risk**: Marginal keyword-text size increase. Method chunks average 3-8 parameters, each adding ~2-10 tokens. Minimal impact on BM25 scoring speed.

### Decision 4: Answer-level parameter validation — new verifier function

**Approach**: Add a `validate_parameter_claims()` function that:

1. Extracts parameter mentions from the generated answer using regex patterns like:
   - `ParamName (TypeAnnotation): Description text`
   - `ParamName — Description text`
   - Patterns from the context (`CrossSectionName (ECrossSectionShape): ...`)

2. Extracts known parameter names and descriptions from the retrieved source chunks (from metadata `parameters` list).

3. Flags any parameter name mentioned in the answer that does not exist in any source chunk's parameter list.

4. Flags any parameter description in the answer that is a fabricated value (not matching the source description for that parameter name).

**Integration**: This operates alongside the existing `ResponseVerifier`. For the DSPy path, it runs after `_generate_with_assertions()` in `module.py`. For the fallback path, it runs after `_generate_answer()` in `manager.py`. Results are included in the response metadata (not removing text — just flagging).

**Why not extend ResponseVerifier?**: `ResponseVerifier` uses cross-encoder semantic similarity for sentence-level scoring. Parameter validation requires exact-match and substring matching against structured metadata, not embedding comparison. A separate function is cleaner.

**Alternative considered**: Use the cross-encoder to score parameter claims specifically. Rejected because parameter validation needs exact-name matching — a cross-encoder would say "CrossSectionName" and "CrossSectionShape" are semantically similar when they're entirely different parameters.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| [Assertion retry] Structured fallback answer may be less helpful than a hallucinated one | The current advisory pattern already returns hallucinated output. A structured "I found these functions: ..." is safer and more honest. This affects only the assertion-failure path (rare when retrieval quality is good). |
| [BM25] Parameter description text could introduce noise for queries not about parameters | Parameter descriptions are descriptive text that naturally matches relevant queries. The risk of false positives is low and acceptable. |
| [Parameter validation] Regex patterns may miss parameter claims in free-form LLM answers | Pattern evolution: start with common patterns, add more as edge cases are discovered. Validation is advisory-only (flag, don't block). |
| [Retry latency] Retry on assertion failure doubles generation time for failure cases | Assertion failure is rare (~5-10% of queries based on observed metrics). The 3-strike cap prevents infinite retries. Latency increase is bounded to 2x for the failure path. |
| [Design] No changes to MAX_CONTEXT_CHUNKS | The 10-chunk limit is a deliberate tradeoff for latency. The inline param descriptions in method chunks (12c8af0) mitigate the risk of missing parameter-level chunks. If retrieval tuning later changes this, it's a separate change. |
