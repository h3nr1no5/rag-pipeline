# Frontend Loading Status

## Purpose

Provide real-time feedback to users during model warmup by polling the backend health endpoint and displaying per-model progress bars, ensuring the application remains responsive and transparent about its initialization state.

## Requirements

### Requirement: Chat page SHALL poll model status on load

The Streamlit chat page SHALL poll `GET /health/models` every 200ms while any model is in `loading` or `queued` status. Polling SHALL continue indefinitely until all models are `ready` or `permanent_error`. No timeout bypass SHALL exist.

#### Scenario: Polling starts on page load
- **WHEN** the chat page loads
- **THEN** the page SHALL begin polling `/health/models` at 200ms intervals
- **THEN** each poll response SHALL be checked for model status values

#### Scenario: Polling stops when all models ready
- **WHEN** all models report `status: "ready"`
- **THEN** polling SHALL stop
- **THEN** no further `/health/models` requests SHALL be made until the next page load

#### Scenario: Polling stops on permanent error
- **WHEN** a model reports `status: "permanent_error"`
- **THEN** polling SHALL stop immediately (no recovery possible)

#### Scenario: No timeout bypass
- **WHEN** models are still loading after any duration
- **THEN** polling SHALL continue
- **THEN** the page SHALL NOT force `models_ready = True` based on poll count
- **THEN** the chat input SHALL remain disabled

### Requirement: Frontend SHALL display per-model gateway cards

A gateway screen showing per-model status cards above the chat area. Each card SHALL display: model name, status icon, progress bar, and a status message. Inputs required for that model SHALL be disabled with tooltips until the model is ready.

#### Scenario: Gateway cards shown during loading
- **WHEN** at least one model has `status: "loading"` or `"queued"`
- **THEN** the page SHALL display a status section above the chat input
- **THEN** each model SHALL have its own card showing:
  - Model display name (e.g., "Language Model", "Embedder")
  - Status icon (spinner for loading, ✅ for ready, ⚠️ for error, ❌ for permanent_error)
  - Progress bar (0-100%)
  - Status message ("Downloading model...", "Loading into memory...", "Ready", "Error — retrying in 4s...")
- **THEN** the chat input SHALL be disabled/hidden
- **THEN** all RAG method checkboxes SHALL be disabled with tooltips

#### Scenario: No gateway when all models ready
- **WHEN** all models are `status: "ready"`
- **THEN** the status section SHALL be hidden
- **THEN** the chat input SHALL be fully interactive
- **THEN** all enabled RAG checkboxes SHALL be available

#### Scenario: Gateway cards show error and retry state
- **WHEN** a model has `status: "error"`
- **THEN** the card SHALL show a ⚠️ warning icon
- **THEN** the message SHALL indicate retry delay (e.g., "Error — retrying in 8s...")
- **THEN** the progress bar SHALL remain at its last value

#### Scenario: Gateway cards show permanent error
- **WHEN** a model has `status: "permanent_error"`
- **THEN** the card SHALL show a ❌ error icon
- **THEN** the message SHALL indicate permanent failure
- **THEN** the page SHALL display guidance text: "Please restart the server or contact support"
- **THEN** the upload button and relevant RAG checkboxes SHALL remain permanently disabled

#### Scenario: Layout does not shift on polling
- **WHEN** the gateway section appears or updates during polling
- **THEN** the section SHALL use `st.empty()` placeholders to avoid page layout shifts

### Requirement: Frontend SHALL disable inputs based on model readiness

Each input that depends on a model SHALL be disabled (grayed out) with a tooltip explaining which model is not ready. Previously all RAG checkboxes were enabled whenever polling timed out, and the upload button was always enabled.

#### Scenario: Cosine/LlamaIndex disabled when LLM not ready
- **WHEN** the `"llm"` model has status other than `"ready"`
- **THEN** the "🔵 Cosine Sim" and "🟢 LlamaIndex" checkboxes SHALL be disabled
- **THEN** their tooltip SHALL read "LLM is still initializing..."

#### Scenario: LangChain disabled when LLM or cross-encoder not ready
- **WHEN** the `"cross_encoder"` model has status other than `"ready"`
- **THEN** the "🟣 LangChain" checkbox SHALL be disabled
- **THEN** its tooltip SHALL read "Cross-encoder reranker is still initializing..."

#### Scenario: API Docs disabled when DSPy LM not ready
- **WHEN** the `"dspy_lm"` model has status other than `"ready"`
- **THEN** the "🔶 API Docs" checkbox SHALL be disabled
- **THEN** its tooltip SHALL read "DSPy LM is still initializing..."

#### Scenario: Upload button disabled when embedder not ready
- **WHEN** the `"embedder"` model has status other than `"ready"`
- **THEN** the document upload button in both Chat page sidebar and Documents page sidebar SHALL be disabled (grayed out)
- **THEN** its tooltip SHALL read "Embedder is still initializing... Please wait"

### Requirement: Frontend SHALL determine API doc query readiness from in-memory manager state

The chat page SHALL check the API Doc pipeline manager's in-memory index state (via `GET /query/api-docs/documents/{id}/status`) rather than the document's DB `status` field to determine whether an API doc is ready for querying. This accounts for the gap between DB persistence and in-memory index loading at startup.

#### Scenario: API doc shown as ready when manager has indexed it
- **WHEN** a user selects an API doc document
- **THEN** the frontend SHALL call `GET /api/v1/query/api-docs/documents/{id}/status`
- **WHEN** the response shows `indexed: true`
- **THEN** the document SHALL be shown as ready for querying
- **AND** the "🔶 API Docs" checkbox SHALL be enabled

#### Scenario: API doc shown as unavailable when manager has not indexed it
- **WHEN** the response shows `indexed: false`
- **THEN** the document SHALL show a loading indicator or "warming up" state
- **AND** the "🔶 API Docs" checkbox SHALL be disabled with a tooltip explaining the model is still warming up


### Requirement: Frontend SHALL display model status banner on Documents page

The Documents page SHALL show a model status section using a shared component imported from `client/components/model_status.py`. The banner SHALL display all 4 model statuses with per-model cards, and SHALL disable the file uploader and upload button when the embedder is not ready.

#### Scenario: Model status banner displayed on Documents page load
- **WHEN** the Documents page loads
- **THEN** the page SHALL call `/health/models` to fetch model status
- **THEN** the page SHALL display a status banner showing all 4 model cards
- **THEN** each model card SHALL show its name, status icon, progress bar, and message

#### Scenario: Documents page disables upload during embedder loading
- **WHEN** the `"embedder"` model has status other than `"ready"`
- **THEN** the `st.file_uploader` widget SHALL be disabled
- **THEN** the `st.button("Upload")` SHALL be disabled
- **THEN** a tooltip SHALL explain: "Embedder model is loading — please wait"

#### Scenario: Documents page shows success banner when all models ready
- **WHEN** all 4 models have `status: "ready"`
- **THEN** the status banner SHALL collapse to a compact "✅ AI models ready" success message
- **THEN** the file uploader and upload button SHALL be fully interactive

#### Scenario: Documents page handles permanent_error state
- **WHEN** a model reports `status: "permanent_error"`
- **THEN** the banner SHALL display a ❌ icon for that model
- **THEN** the upload button SHALL remain permanently disabled
- **THEN** guidance text SHALL read: "Please restart the server or contact support"

#### Scenario: Documents page replaces inline health check with shared component
- **WHEN** the Documents page renders
- **THEN** the existing inline `/health/models` polling code (lines 21-57 of `4_📁_Documents.py`) SHALL be replaced by the shared `model_status_banner()` component
- **THEN** the component SHALL handle polling, status display, and upload gating

### Requirement: Frontend SHALL handle 503 for document upload

When the `POST /documents` endpoint returns HTTP 503 (embedder not ready), the Documents page SHALL display a clear error message instead of a generic failure.

#### Scenario: Upload returns 503
- **WHEN** a user clicks "Upload" while embedder is not ready
- **AND** the backend returns HTTP 503
- **THEN** the page SHALL display: "Model 'embedder' is not ready — please wait and try again"
- **THEN** the file uploader SHALL retain the selected file

### Requirement: Frontend SHALL update query spinner/error handling for 503

When a query returns HTTP 503 (model not ready), the frontend SHALL display an appropriate error message instead of showing a spinner indefinitely.

#### Scenario: Query returns 503 while model loading
- **WHEN** a user submits a query
- **AND** the backend returns HTTP 503
- **THEN** the spinner SHALL stop
- **THEN** the error message SHALL indicate the model is still loading
- **THEN** the user SHALL be prompted to wait and retry

#### Scenario: Query returns 503 due to error/permanent_error
- **WHEN** a user submits a query
- **AND** the backend returns HTTP 503 with error detail
- **THEN** the spinner SHALL stop
- **THEN** the error message SHALL display the backend's error detail
