## 1. Core Parser Fix

- [ ] 1.1 Update `RawParagraph.heading_level` default from `0` to `-1`
- [ ] 1.2 Add bare `"Heading"` detection: `elif not rest: return 0` in `get_heading_level()`
- [ ] 1.3 Update non-heading return value: change `return 0` to `return -1` at the end of `get_heading_level()`

## 2. Dependent Code Updates

- [ ] 2.1 Update converter filter: change `if para.heading_level > 0` to `if para.heading_level >= 0` in `converter.py`
- [ ] 2.2 Update PDF fallback default: change `heading_level=0` to `heading_level=-1` in `pdf_fallback.py`

## 3. Test Updates

- [ ] 3.1 Update heading filter in unit test: change `if p.heading_level > 0` to `if p.heading_level >= 0` in `test_api_docs_extraction.py`
- [ ] 3.2 Update PDF fallback assertion: change `assert para.heading_level == 0` to `assert para.heading_level == -1` in `test_api_docs_pdf_fallback.py`

## 4. Verification

- [ ] 4.1 Run extraction tests: `uv run pytest tests/ -k "extract" -v`
