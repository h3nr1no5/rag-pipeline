## 1. Fix `st.progress()` calls in `client/pages/4_📁_Documents.py`

- [x] 1.1 Remove `, height=8)` from the 4 calls in `render_stage_bar()` (lines 99, 101, 103, 106)
- [x] 1.2 Remove `, height=8)` from the 3 inline calls in `wait_for_processing()` (lines 143, 148, 154)

## 2. Verify the fix

- [x] 2.1 Start the backend (`uvicorn src.api.main:app --reload --port 8000`) — verified OK
- [ ] 2.2 Start the frontend (`streamlit run client/app.py --server.port 8501`)
- [ ] 2.3 Upload a document and confirm the progress bars render without error
- [ ] 2.4 Navigate to the documents page with a processing/completed document and confirm no error appears
