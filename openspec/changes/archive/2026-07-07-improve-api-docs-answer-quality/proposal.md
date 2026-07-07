## Why

After fixing the parameter-description extraction bug, the api-docs query endpoint still produces answers that lack parameter-level detail. For example, "how to add cross section from catalog?" returns "use the AddFromCatalog function" without naming the parameters (`CrossSectionShape`, `CrossSectionName`) or describing how to use them. Two independent causes: (1) method chunk content includes param names/types in the signature but not param descriptions, and (2) the DSPy prompt doesn't instruct the LLM to include parameter details in answers.

## What Changes

### Change 1: Include parameter descriptions in method chunk content

`ChunkTextFormatter._format_method()` currently produces:
```
AddFromCatalog(CrossSectionShape: ECrossSectionShape, CrossSectionName: BSTR) -> long
```

After this change it will produce (when `include_descriptions=True`):
```
AddFromCatalog(CrossSectionShape: ECrossSectionShape, CrossSectionName: BSTR) -> long
  CrossSectionShape (ECrossSectionShape): Shape of the cross-section
  CrossSectionName (BSTR): Name of the cross-section
```

### Change 2: Sharpen the DSPy answer-generation prompt

The `APIResponseGenerator` signature's `answer` field description will be updated to explicitly request parameter-level detail — function signatures, parameter names, types, descriptions, and usage instructions.

### Change 3: Apply the same inline description enrichment to `_meta_method` fallback

The metadata-based fallback formatter (`_meta_method`) will also include parameter descriptions from the node metadata, ensuring the improvement works even when domain objects aren't available.

## Capabilities

### New Capabilities

- `method-chunk-formatting`: Method chunks SHALL include parameter names, types, and descriptions inline below the signature when `include_descriptions` is enabled.

### Modified Capabilities

- `api-docs-rag`: The answer-generation signature SHALL instruct the LLM to include parameter names, types, descriptions, and usage patterns in its answers.

## Impact

| Area | Impact |
|------|--------|
| `chunking/text_formatter.py` | `_format_method()` (line 203) and `_meta_method()` (line 289) modified to include param descriptions inline |
| `pipeline/signatures.py` | `APIResponseGenerator.answer` field description updated |
| `pipeline/module.py` | No change — context assembly and DSPy invocation unchanged |
| `api-docs-rag` spec | New requirement: answer includes parameter details |
| Chunk size | Method chunk content grows by ~1 line per parameter with description — minimal impact on embedding/retrieval |
