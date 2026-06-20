## Why

`st.progress()` in Streamlit accepts only `value` and `text` parameters — it has no `height` parameter. The document processing progress feature introduced `height=8` on 7 `st.progress()` calls to make progress bars compact, but this causes a runtime `TypeError` on any page render that encounters a processing document. The error surfaces as "Error loading documents" in the document list, breaking the entire page.

## What Changes

- Remove the invalid `height=8` keyword argument from all 7 `st.progress()` calls in `client/pages/4_📁_Documents.py`:
  - 4 calls in `render_stage_bar()` function
  - 3 calls in `wait_for_processing()` function
- No new capabilities, no API changes, no spec-level requirement modifications.

## Capabilities

### New Capabilities

None. This is a bug fix with no new capabilities.

### Modified Capabilities

None. No spec-level behavior changes — this is a pure implementation fix.

## Impact

- **Code**: Only `client/pages/4_📁_Documents.py` is modified (7 lines, each removing `, height=8`)
- **UI**: Progress bars will use the default Streamlit height (slightly larger) instead of the intended compact 8px height
- **No API, database, dependency, or config changes**
