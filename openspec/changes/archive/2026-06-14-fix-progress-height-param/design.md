## Context

The `render_stage_bar()` and `wait_for_processing()` functions in `client/pages/4_📁_Documents.py` pass an invalid `height=8` keyword argument to `st.progress()`. Streamlit's `st.progress()` API only accepts `value` (int/float) and `text` (optional string). The `height` parameter is not part of the public API and was introduced during the document processing progress feature implementation as an assumed but unsupported parameter.

When a document is in "processing" status, the document listing page calls `render_stage_bar()` for each processing document, which triggers the 4 invalid `st.progress()` calls. Similarly, after upload the `wait_for_processing()` polling loop triggers the other 3 invalid calls. Both paths raise `TypeError: ProgressMixin.progress() got an unexpected keyword argument 'height'`.

## Goals / Non-Goals

**Goals:**
- Fix the runtime TypeError on the documents page
- Restore document listing and upload functionality for documents in processing state

**Non-Goals:**
- Changing the visual height of progress bars (accepting default Streamlit height)
- Introducing CSS overrides or alternative styling for compact bars
- Any changes to backend, API, or other frontend files

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Fix method | Remove `height=8` from all 7 calls | Simplest possible fix, zero risk of side effects. No behavioral change besides accepting the default bar height. |
| CSS alternative considered | Rejected | We could use custom CSS to set progress bar height, but that would be a larger change with potential style conflicts. If compact bars are desired later, it can be done in a separate change. |

## Risks / Trade-offs

- **[Low] Visual change**: Progress bars will render at default Streamlit height (~25px) instead of the intended compact 8px. This is a cosmetic regression but does not affect functionality. The layout already uses `st.caption()` labels and `st.columns()` to keep the display compact.
- **[None] API stability**: Removing a keyword argument is backwards-compatible — all Streamlit versions that support `st.progress()` accept `value` and `text`.
