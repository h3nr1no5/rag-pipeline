## 1. Fix test_assembler.py

- [x] 1.1 Add `ElementType` to import from `extraction.model` and `ComElementType` to import from `enrichment.model`
- [x] 1.2 Narrow `_make_el` parameter: change `el_type: str` → `el_type: ElementType` (line 18) and remove `# type: ignore[arg-type]` (line 23)
- [x] 1.3 Narrow `_make_com_el` parameter: change `com_type: str | None` → `com_type: ComElementType | None` (line 31)
- [x] 1.4 Remove stale `# type: ignore[arg-type]` on `type="PARAGRAPH"` in `_make_com_el` (line 42)
- [x] 1.5 Remove stale `# type: ignore[arg-type]` on `type="PAGE"` in `_hierarchy` (line 58)
- [x] 1.6 Remove stale `# type: ignore[arg-type]` on `type="PAGE"` in `test_root_with_empty_page_and_no_children` (line 110)

## 2. Fix test_boundaries.py

- [x] 2.1 Add `ElementType` to import from `extraction.model` and `ComElementType` to import from `enrichment.model`
- [x] 2.2 Narrow `_make_el` parameter: change `el_type: str` → `el_type: ElementType` (line 23) and remove `# type: ignore[arg-type]` (line 29)
- [x] 2.3 Narrow `_make_com_el` parameter: change `com_type: str | None` → `com_type: ComElementType | None` (line 37)
- [x] 2.4 Remove stale `# type: ignore[arg-type]` on `type="PARAGRAPH"` in `_make_com_el` (line 43)
- [x] 2.5 Remove stale `# type: ignore[arg-type]` on `type="PAGE"` in `_flat` (line 52)
- [x] 2.6 Remove stale `# type: ignore[arg-type]` on `type="HEADING"` in `test_heading_with_no_font_size_key` (line 160)
- [x] 2.7 Remove stale `# type: ignore[arg-type]` on `type="PAGE"` in `TestBoundaryDetector._hierarchy_from_els` (line 528)

## 3. Verify

- [x] 3.1 Run `mypy` on both files — expect zero errors
- [x] 3.2 Run `pytest tests/pdf_semantic_chunking/test_chunking/test_assembler.py tests/pdf_semantic_chunking/test_detection/test_boundaries.py -v` — all tests pass
- [x] 3.3 Confirm total `# type: ignore` count dropped from 18 to 9 (or 8, excluding `test_patterns.py`)
