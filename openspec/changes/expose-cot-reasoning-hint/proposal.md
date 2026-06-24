## Why

The DSPy-powered API docs RAG pipeline uses `dspy.ChainOfThought` for answer generation, which produces a reasoning trace (rationale) internally. This trace is currently discarded — only the final `answer` field reaches the user. Observing the model's reasoning would help users understand how answers are derived, building trust and enabling debugging.

## What Changes

- **Response schema** — `ApiDocQueryResponse` gains an optional `reasoning_hint` field containing the raw ChainOfThought rationale from the `APIResponseGenerator` DSPy predictor
- **Pipeline output** — `APIDocRAG.forward()` captures `response.rationale` and pipes it through the response chain
- **Frontend display** — The chat UI shows a new "💭 Reasoning" expandable section below the answer when `reasoning_hint` is non-empty (same pattern as Sources/Functions/Types)
- **Fallback path** — `reasoning_hint` is empty string when the non-DSPy fallback is used (no rationale available)
- **No changes** to `MLXDspyLM._build_chat_completion()` — `reasoning_content` remains `None` (it is a DSPy-internal stub, not consumed by the pipeline)

## Capabilities

### New Capabilities

- `api-docs-reasoning-hint`: Expose the DSPy ChainOfThought rationale as a `reasoning_hint` field in the API docs query response, and display it as an expandable section in the chat UI

### Modified Capabilities

- `api-docs-rag`: The API docs response schema gains a new `reasoning_hint` field; the pipeline must capture and propagate the rationale from the DSPy predictor output
- `api-docs-frontend`: The chat page response display must render the reasoning hint in an expandable section below the answer

## Impact

- **Backend**: `module.py`, `manager.py`, `schemas.py` — minor additions to capture and pipe through the rationale
- **Frontend**: `Chat.py` — new expandable section following the existing Sources/Functions/Types pattern
- **API contract**: `ApiDocQueryResponse` gains `reasoning_hint: str` (non-breaking addition)
- **No new dependencies**, no config changes, no database schema changes
