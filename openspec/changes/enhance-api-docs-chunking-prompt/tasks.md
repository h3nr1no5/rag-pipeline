## 1. Metadata Completeness (Area 3)

- [ ] 1.1 Add `interface_name` to `enum_value` chunk metadata in `builder.py` `_add_enum()` — source from `enum_def.parent_interface`
- [ ] 1.2 Add `interface_name` to `record_field` chunk metadata in `builder.py` `_add_record()` — source from `record.parent_interface`

## 2. Paragraph Chunks (Area 1)

- [ ] 2.1 Modify `converter.py` to capture non-first paragraphs under interface headings — scan all paragraphs after `_build_interface_descriptions()` and associate each with the nearest preceding interface heading
- [ ] 2.2 Add `paragraphs: list[str]` field to `APIInterface` domain model in `models.py` (or use existing storage mechanism)
- [ ] 2.3 Add `paragraph` chunk kind to `builder.py` `_add_interface()` — create one level-1 child node per paragraph, skip the first paragraph (already used as interface description)
- [ ] 2.4 Add paragraph formatting to `text_formatter.py` — support `kind="paragraph"` with raw paragraph text as content
- [ ] 2.5 Verify paragraph chunks are indexed in both BM25 and embedding indexes (no special changes needed — they flow through automatically)

## 3. Unknown Table Handling (Area 2)

- [ ] 3.1 Modify `converter.py` `_build_table_contexts()` — replace the `else: logger.debug(...)` silent skip with generic table entry creation (heading stack, rows, header row)
- [ ] 3.2 Add `generic_table` chunk kind to `builder.py` — created as level-1 child of nearest interface from heading context
- [ ] 3.3 Add generic table formatting to `text_formatter.py` — render as markdown-like pipe table for `kind="generic_table"`
- [ ] 3.4 Upgrade unknown table logging from `DEBUG` to `INFO` with heading context, dimensions, and first-row cell previews

## 4. Enum Cross-Reference Traversal (Area 4)

- [ ] 4.1 Extend `LinkTraverser` regex from `\bI[A-Z][a-zA-Z0-9_]*\b` to include `\bE[A-Z][a-zA-Z0-9_]*\b`
- [ ] 4.2 Add enum name-to-ID resolution in `LinkTraverser` — analogous to `_interface_name_to_id`, create `_enum_name_to_id` mapping populated during `traverse()`
- [ ] 4.3 Ensure max_depth limit applies to enum-originated traversal (same as interface traversal)

## 5. Prompt Improvements (Areas 5 & 6)

- [ ] 5.1 Add exact enum value instruction to `_generate_answer()` prompt template in `manager.py`: "Use EXACT enum values from context. Do not invent or approximate enum member names."
- [ ] 5.2 Add citation marker instruction: "Cite each source as [Source N] where N is the index of the relevant chunk." Include chunk index markers in context snippets
- [ ] 5.3 Add grounding and anti-repetition guardrails: "Only use information from the provided context. If the context does not contain the answer, say so." / "Do not repeat the same information multiple times." / "Structure your answer with clear sections if multiple concepts are discussed."
- [ ] 5.4 Verify prompt changes integrate with existing DSPy assertion and verification setup (no regressions from `fix-api-docs-answer-quality`)

## 6. Testing

- [ ] 6.1 Unit tests for paragraph chunk creation — converter associates paragraphs with correct interface, builder creates correctly parented paragraph nodes
- [ ] 6.2 Unit tests for unknown table handling — converter creates generic table entries, builder creates generic_table chunks
- [ ] 6.3 Unit tests for enum_value and record_field metadata completeness — interface_name present after builder runs
- [ ] 6.4 Unit tests for LinkTraverser enum cross-references — E-prefix names followed, I-prefix still works, unmatched names ignored, depth limit respected
- [ ] 6.5 Manual/integration test: query "how to add cross section from catalog" returns correct `AddFromCatalog` with `ENationalDesignCode::ndcEuroCode` and exact enum values in the answer
