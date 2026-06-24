# Frontend Loading Status (Delta)

## MODIFIED Requirements

### Requirement: Chat page SHALL poll model status on load

**FROM**: Polling stops after 60 attempts (~12s) or on first error. Includes a timeout bypass that forces `models_ready=True`.
**TO**: The Streamlit chat page SHALL poll `GET /health/models` every 200ms while any model is in `loading` or `queued` status. Polling SHALL continue indefinitely until all models are `ready` or `permanent_error`. No timeout bypass SHALL exist.

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

**FROM**: Simple progress bar list with 2 models (cross_encoder, llm). Error models show `st.error()` but user can still proceed.
**TO**: A gateway screen showing per-model status cards above the chat area. Each card SHALL display: model name, status icon, progress bar, and a status message. Inputs required for that model SHALL be disabled with tooltips until the model is ready.

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

**FROM**: All RAG checkboxes are enabled whenever polling times out. Upload button is always enabled.
**TO**: Each input that depends on a model SHALL be disabled (grayed out) with a tooltip explaining which model is not ready.

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
- **THEN** the document upload button SHALL be disabled (grayed out)
- **THEN** its tooltip SHALL read "Embedder is still initializing... Please wait"

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Frontend SHALL determine API doc query readiness from in-memory manager state

**Reason**: This requirement is about API doc index readiness, not model readiness. It was included in the original spec as a related concern but is unrelated to model warmup gating. It remains in the main spec as-is and is not part of this delta.
**Migration**: No change needed — this requirement is retained in the main spec and continues to govern API doc readiness independently.

### Requirement: Frontend SHALL timeout bypass

**FROM**: `if st.session_state.models_poll_count > 60: models_ready = True`
**Reason**: Replaced by infinite polling with no timeout bypass. Users must wait for actual model readiness.
**Migration**: Remove the poll count check and the forced `models_ready = True` bypass.
