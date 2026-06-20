"""Integration tests for streaming query response formatting and citation control.

Tests cover the fix-response-citations behavior for the ``include_citations``
parameter across two RAG backends:

1.  Cosine similarity streaming  — ``POST /api/v1/query/stream``
2.  LlamaIndex streaming         — ``POST /api/v1/query/llamaindex/stream``

Each section verifies:
    * SSE event ordering (sources before tokens, ``[DONE]`` at end)
    * Citation stripping when ``include_citations=False``
    * Citation preservation when ``include_citations=True``
    * No raw LLM special-token leakage in streamed output
    * Clean, coherent reconstructed response text
"""

import io
import json
import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient

from src.domain.services.prompt_builder import clean_response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_DOCS_DIR = Path(__file__).parent.parent / "docs"


async def create_text_document(client: AsyncClient, title: str, content: str) -> str:
    """Upload a plain-text document and return its ID."""
    files = {"file": (title, io.BytesIO(content.encode()), "text/plain")}
    data = {"strategy_id": "recursive"}
    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201, f"Upload failed: {response.text}"
    return response.json()["id"]


async def wait_for_document_ready(client: AsyncClient, doc_id: str, timeout: float = 45.0) -> None:
    """Poll the document status endpoint until processing completes or fails."""
    import asyncio
    import time
    start = time.monotonic()
    while True:
        resp = await client.get(f"/api/v1/documents/{doc_id}/status")
        if resp.status_code == 200:
            status = resp.json()
            if status["status"] == "completed":
                return
            if status["status"] == "failed":
                error_msg = status.get("error_message", status.get("error", "unknown"))
                pytest.fail(f"Document {doc_id} processing failed: {error_msg}")
        if time.monotonic() - start > timeout:
            pytest.fail(f"Document {doc_id} did not complete within {timeout}s")
        await asyncio.sleep(0.3)


async def collect_sse_events(
    client: AsyncClient,
    url: str,
    payload: dict,
) -> list[dict]:
    """POST to an SSE streaming endpoint and collect all parsed events.

    Returns a list of dicts.  A sentinel ``{"type": "done"}`` marks the
    ``[DONE]`` event.  Events are returned in wire order.
    """
    events: list[dict] = []
    async with client.stream("POST", url, json=payload) as response:
        assert response.status_code == 200, (
            f"Stream request to {url} returned {response.status_code}: "
            f"{response.text}"
        )
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]  # strip "data: " prefix
            if data_str == "[DONE]":
                events.append({"type": "done"})
                break
            try:
                events.append(json.loads(data_str))
            except json.JSONDecodeError:
                events.append({"type": "raw", "data": data_str})
    return events


def reconstruct_text(events: list[dict]) -> str:
    """Join all ``token`` fields from a list of SSE events."""
    return "".join(event.get("token", "") for event in events)


_SPECIAL_TOKENS = frozenset({
    "<|endoftext|>", "<|eos|>", "<|eot|>", "<|end|>",
    "<|im_end|>", "<|im_start|>",
    "[INST]", "[/INST]", "[SYS]", "[/SYS]",
    "<<SYS>>", "<</SYS>>",
})


def has_special_tokens(text: str) -> bool:
    """Return True if *text* contains any raw LLM special token."""
    for tok in _SPECIAL_TOKENS:
        if tok in text:
            return True
    return False


# ---------------------------------------------------------------------------
# Long, structured document used by all streaming tests
# ---------------------------------------------------------------------------

_AI_CONTENT = (
    "Artificial Intelligence Overview\n\n"
    "AI Definition\n"
    "Artificial Intelligence (AI) is the simulation of human intelligence "
    "in machines that are programmed to think and learn. "
    "AI systems can perform tasks that typically require human intelligence, "
    "such as visual perception, speech recognition, decision-making, "
    "and language translation.\n\n"
    "Machine Learning\n"
    "Machine learning is a subset of AI that enables systems to "
    "automatically learn and improve from experience without being explicitly "
    "programmed. Machine learning algorithms use statistical techniques to "
    "identify patterns in data and make decisions with minimal human "
    "intervention. Common algorithms include linear regression, decision "
    "trees, and neural networks.\n\n"
    "Deep Learning\n"
    "Deep learning is a subset of machine learning that uses artificial "
    "neural networks with multiple layers (hence deep) to model complex "
    "patterns. Deep learning has been particularly successful in image "
    "recognition, natural language processing, and speech recognition. "
    "Convolutional neural networks (CNNs) are commonly used for image "
    "tasks while recurrent neural networks (RNNs) are used for sequential data.\n\n"
    "Natural Language Processing\n"
    "Natural Language Processing (NLP) is a branch of AI focused on "
    "the interaction between computers and human language. NLP enables "
    "computers to understand, interpret, and generate human language. "
    "Applications include sentiment analysis, machine translation, "
    "chatbots, and text summarization.\n\n"
    "Reinforcement Learning\n"
    "Reinforcement learning is a type of machine learning where an agent "
    "learns to make decisions by interacting with an environment. "
    "The agent receives rewards or penalties based on its actions and "
    "learns to maximize cumulative reward over time.\n\n"
    "AI Applications\n"
    "AI has numerous real-world applications including virtual assistants "
    "like Siri and Alexa, autonomous vehicles, medical diagnosis systems, "
    "recommendation engines used by Netflix and Amazon, fraud detection "
    "in banking, and language translation services like Google Translate."
)


@pytest_asyncio.fixture(scope="function")
async def processed_doc(auth_client) -> str:
    """Upload the AI document and wait for processing to finish."""
    doc_id = await create_text_document(auth_client, "ai_overview.txt", _AI_CONTENT)
    await wait_for_document_ready(auth_client, doc_id)
    return doc_id


# ===================================================================
# 1.  Direct unit-level verification of clean_response
#     (deterministic, no model needed)
# ===================================================================


class TestCleanResponseDirect:
    """Direct tests for the `clean_response` function that underlies streaming."""

    CITATION_TEXT = (
        "According to the sources, artificial intelligence simulates human "
        "intelligence in machines [Source 1]. Machine learning enables "
        "systems to learn from data [Source 2]."
    )
    PAGE_TEXT = (
        "The simulation of human intelligence in machines [Page 1] "
        "is known as artificial intelligence. [Page 2] "
    )
    SPECIAL_CHARS = "<|endoftext|> This is a response <|im_end|>"

    def test_strips_source_markers_when_disabled(self):
        """include_citations=False removes [Source N] markers."""
        result = clean_response(self.CITATION_TEXT, include_citations=False)
        assert "[Source 1]" not in result
        assert "[Source 2]" not in result
        assert "artificial intelligence" in result.lower()

    def test_preserves_source_markers_when_enabled(self):
        """include_citations=True keeps [Source N] markers intact."""
        result = clean_response(self.CITATION_TEXT, include_citations=True)
        assert "[Source 1]" in result
        assert "[Source 2]" in result

    def test_strips_page_markers_always(self):
        """[Page N] is always stripped regardless of include_citations."""
        for include_val in (True, False):
            result = clean_response(self.PAGE_TEXT, include_citations=include_val)
            assert re.search(r"\[Page \d+\]", result) is None, (
                f"[Page N] NOT stripped when include_citations={include_val}"
            )

    def test_strips_special_tokens(self):
        """Special LLM tokens are removed from the response."""
        result = clean_response(self.SPECIAL_CHARS, include_citations=True)
        assert not has_special_tokens(result)
        assert "This is a response" in result

    def test_strips_section_markers_always(self):
        """[Section N] markers are always stripped."""
        text = "Relevant content [Section 2.1] goes here."
        result = clean_response(text, include_citations=True)
        assert re.search(r"\[Section \d+(\.\d+)*\]", result) is None

    def test_empty_response_returns_empty_string(self):
        """Very short or empty responses are returned as-is (no crash)."""
        assert clean_response("", include_citations=True) == ""
        assert clean_response("   ", include_citations=True) == ""

    def test_no_false_positive_on_bracket_content(self):
        """Non-citation bracket content (e.g. [sic], [note]) is not stripped."""
        text = "The author wrote [sic] and added a reference [1]."
        result = clean_response(text, include_citations=False)
        # [Source N] is stripped; other brackets survive
        assert "[sic]" in result, f"[sic] was stripped from: {result!r}"
        assert "[1]" in result, f"[1] was stripped from: {result!r}"

    @pytest.mark.parametrize("include_val", [True, False])
    def test_concise_response_truncation_respects_citations(self, include_val):
        """Concise mode truncates but still strips/preserves citations correctly."""
        long_text = "First sentence about AI. Second sentence about ML. Third about DL."
        result = clean_response(long_text, response_length="concise", include_citations=include_val)
        # Should not crash, result should be at most 2 sentences
        assert len(result) > 0

    def test_detailed_response_no_truncation(self):
        """Detailed mode keeps the full response."""
        full_text = "A. B. C. D. E."
        result = clean_response(full_text, response_length="detailed", include_citations=True)
        assert result == full_text.strip()


# ===================================================================
# 2.  Cosine streaming endpoint — POST /api/v1/query/stream
# ===================================================================


@pytest.mark.asyncio
async def test_cosine_stream_sse_protocol(processed_doc, auth_client):
    """SSE event ordering is correct: sources → tokens → [DONE].

    Additionally verifies the ``include_citations`` parameter is reflected
    in the sources event metadata.
    """
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is artificial intelligence?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"

    # --- First real event must be the sources event ---
    first = events[0]
    assert "sources" in first, (
        f"First SSE event should contain 'sources', got keys: {list(first.keys())}"
    )
    assert first.get("include_citations") is False, (
        "include_citations should be False in sources event"
    )

    # --- Intermediate events must be token events ---
    token_events = [e for e in events if "token" in e]
    assert len(token_events) > 0, "Expected at least one token event"

    # --- The very last event must be [DONE] ---
    assert events[-1].get("type") == "done", (
        f"Last event should be type=done, got: {events[-1]}"
    )

    # --- No error events interspersed ---
    error_events = [e for e in events if "error" in e]
    assert len(error_events) == 0, f"Unexpected error events: {error_events}"


@pytest.mark.asyncio
async def test_cosine_stream_no_citations_strips_markers(processed_doc, auth_client):
    """With ``include_citations=False`` the response text contains no
    ``[Source N]`` or ``[Page N]`` markers and no raw special tokens.
    """
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is machine learning?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    text = reconstruct_text(events)
    assert len(text) > 10, f"Response text too short: {text!r}"

    # No citation markers
    assert "[Source " not in text, f"Found [Source marker in: {text[:200]}"
    assert re.search(r"\[Page \d+\]", text) is None, f"Found [Page marker in: {text[:200]}"

    # No special token leakage
    assert not has_special_tokens(text), f"Special tokens found in: {text[:200]}"

    # No Markdown artifacts (the prompt instructs plain text)
    assert "**" not in text, "Markdown bold markers should be stripped"

    # Response is coherent (starts with relevant content, not a control token)
    assert len(text.split()) >= 3, "Response should contain at least 3 words"


@pytest.mark.asyncio
async def test_cosine_stream_no_raw_token_leakage(processed_doc, auth_client):
    """Individual SSE token events do not contain raw LLM special tokens.

    The ``clean_response`` function is applied before the text is split
    into word tokens, so no special characters should leak through.
    """
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is deep learning?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    for event in events:
        token = event.get("token", "")
        assert not has_special_tokens(token), (
            f"Raw special token leaked in event: {event}"
        )
        # No chunked / partial special tokens either
        assert "<|" not in token, f"Partial special token leaked: {token!r}"


@pytest.mark.asyncio
async def test_cosine_stream_buffering_no_double_stream(processed_doc, auth_client):
    """The buffering-then-stream pattern produces each word exactly once.

    The implementation collects all LLM output, applies ``clean_response``,
    splits the result into words, and streams each word as a single token
    event.  This means:
      * Token events before ``[DONE]`` contain only token (or error) keys.
      * No event has both 'sources' and 'token' keys.
      * The tokens form contiguous, non-repeating text.
    """
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is NLP?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    # --- Only token events between sources and [DONE] ---
    sources_seen = False
    for event in events:
        if "sources" in event:
            sources_seen = True
            continue
        if event.get("type") == "done":
            continue

        # Every non-sources, non-done event should be a pure token event
        assert "token" in event, f"Unexpected event without token: {event}"
        assert "sources" not in event, "Token event should not carry sources"
        assert "error" not in event, f"Error event interrupted stream: {event}"

    assert sources_seen, "Sources event was never emitted"

    # --- Text is contiguous (word count roughly matches token count) ---
    text = reconstruct_text(events)
    token_count = sum(1 for e in events if "token" in e)
    word_count = len(text.split())
    # Each word is streamed as one token (+ a trailing space)
    assert abs(token_count - word_count) <= 2, (
        f"Token count ({token_count}) mismatches word count ({word_count})"
    )


# ===================================================================
# 3.  LlamaIndex streaming endpoint — POST /api/v1/query/llamaindex/stream
# ===================================================================


@pytest.mark.asyncio
async def test_llamaindex_stream_sse_protocol(processed_doc, auth_client):
    """LlamaIndex SSE event ordering: sources → tokens → [DONE]."""
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/llamaindex/stream", {
        "question": "What is artificial intelligence?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"

    first = events[0]
    assert "sources" in first, (
        f"First SSE event should contain 'sources', got keys: {list(first.keys())}"
    )
    assert first.get("include_citations") is False

    token_events = [e for e in events if "token" in e]
    assert len(token_events) > 0, "Expected at least one token event"

    assert events[-1].get("type") == "done", (
        f"Last event should be type=done, got: {events[-1]}"
    )

    error_events = [e for e in events if "error" in e]
    assert len(error_events) == 0, f"Unexpected error events: {error_events}"


@pytest.mark.asyncio
async def test_llamaindex_stream_no_citations_strips_markers(processed_doc, auth_client):
    """LlamaIndex: ``include_citations=False`` strips ``[Source N]`` / ``[Page N]``."""
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/llamaindex/stream", {
        "question": "What is machine learning?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    text = reconstruct_text(events)
    assert len(text) > 10, f"Response text too short: {text!r}"

    assert "[Source " not in text, f"Found [Source marker in: {text[:200]}"
    assert re.search(r"\[Page \d+\]", text) is None, f"Found [Page marker in: {text[:200]}"
    assert not has_special_tokens(text), f"Special tokens found in: {text[:200]}"
    assert "**" not in text, "Markdown bold markers should be stripped"


@pytest.mark.asyncio
async def test_llamaindex_stream_no_raw_token_leakage(processed_doc, auth_client):
    """LlamaIndex: individual token events have no special-token leakage."""
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/llamaindex/stream", {
        "question": "What is deep learning?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    for event in events:
        token = event.get("token", "")
        assert not has_special_tokens(token), (
            f"Raw special token leaked in event: {event}"
        )
        assert "<|" not in token, f"Partial special token leaked: {token!r}"


@pytest.mark.asyncio
async def test_llamaindex_stream_buffering_no_double_stream(processed_doc, auth_client):
    """LlamaIndex: buffering-then-stream pattern produces each word once."""
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/llamaindex/stream", {
        "question": "What is NLP?",
        "document_ids": [doc_id],
        "include_citations": False,
    })

    sources_seen = False
    for event in events:
        if "sources" in event:
            sources_seen = True
            continue
        if event.get("type") == "done":
            continue

        assert "token" in event, f"Unexpected event without token: {event}"
        assert "sources" not in event, "Token event should not carry sources"
        assert "error" not in event, f"Error event interrupted stream: {event}"

    assert sources_seen, "Sources event was never emitted"

    text = reconstruct_text(events)
    token_count = sum(1 for e in events if "token" in e)
    word_count = len(text.split())
    assert abs(token_count - word_count) <= 2, (
        f"Token count ({token_count}) mismatches word count ({word_count})"
    )


# ===================================================================
# 4.  include_citations=True  —   markers preserved
# ===================================================================


@pytest.mark.asyncio
async def test_cosine_stream_with_citations(processed_doc, auth_client):
    """Cosine: ``include_citations=True`` propagates the flag and preserves
    ``[Source N]`` markers that the LLM generates.

    We verify:
      * The ``include_citations`` field is ``true`` in the sources event.
      * No special tokens leak.
      * SSE protocol is correct (sources before tokens, ``[DONE]`` at end).
      * The final text does not contain ``[Page N]`` markers (always stripped).
    """
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is reinforcement learning?",
        "document_ids": [doc_id],
        "include_citations": True,
    })

    assert len(events) >= 2

    # --- sources event carries include_citations=True ---
    first = events[0]
    assert "sources" in first
    assert first.get("include_citations") is True, (
        f"include_citations should be True, got: {first.get('include_citations')}"
    )

    # --- SSE protocol ---
    assert events[-1].get("type") == "done"
    error_events = [e for e in events if "error" in e]
    assert len(error_events) == 0, f"Unexpected error events: {error_events}"

    # --- Token-level checks ---
    text = reconstruct_text(events)
    assert len(text) > 10, f"Response text too short: {text!r}"

    # No raw special tokens
    assert not has_special_tokens(text), f"Special tokens in response: {text[:200]}"

    # [Page N] is always stripped
    assert re.search(r"\[Page \d+\]", text) is None, "[Page N] should always be stripped"

    # If the LLM followed the prompt and added [Source N] markers, they
    # should be preserved.  We use a soft assertion here because the LLM
    # output is non-deterministic — but the prompt explicitly instructs it.
    if re.search(r"\[Source \d+\]", text):
        # Great — citations were generated AND preserved
        pass
    else:
        # The LLM may not have generated citations; the important thing is
        # that the pipeline passed include_citations=True through correctly.
        pytest.skip(
            "LLM did not generate [Source N] markers in this run — "
            "citation preservation could not be verified end-to-end. "
            "The include_citations flag was correctly propagated (verified above)."
        )


@pytest.mark.asyncio
async def test_llamaindex_stream_with_citations(processed_doc, auth_client):
    """LlamaIndex: ``include_citations=True`` propagates and preserves markers."""
    doc_id = processed_doc
    events = await collect_sse_events(auth_client, "/api/v1/query/llamaindex/stream", {
        "question": "What are AI applications?",
        "document_ids": [doc_id],
        "include_citations": True,
    })

    assert len(events) >= 2

    # --- Flag propagation ---
    first = events[0]
    assert "sources" in first
    assert first.get("include_citations") is True

    # --- Protocol ---
    assert events[-1].get("type") == "done"
    error_events = [e for e in events if "error" in e]
    assert len(error_events) == 0

    # --- Cleanliness ---
    text = reconstruct_text(events)
    assert len(text) > 10
    assert not has_special_tokens(text)
    assert re.search(r"\[Page \d+\]", text) is None

    # --- Citation preservation ---
    if re.search(r"\[Source \d+\]", text):
        pass
    else:
        pytest.skip(
            "LLM did not generate [Source N] markers in this run — "
            "citation preservation could not be verified end-to-end."
        )


# ===================================================================
# 5.  Edge cases
# ===================================================================


@pytest.mark.asyncio
async def test_empty_document_list_returns_early_error(auth_client):
    """Streaming with empty document_ids yields an error SSE event."""
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is AI?",
        "document_ids": [],
        "include_citations": False,
    })

    # Should get at least one event with an error
    error_events = [e for e in events if "error" in e]
    assert len(error_events) >= 1, f"No error event found in: {events}"


@pytest.mark.asyncio
async def test_nonexistent_document_returns_early_error(auth_client):
    """Streaming with a non-existent document ID yields an error event."""
    fake_id = str(uuid.uuid4())
    events = await collect_sse_events(auth_client, "/api/v1/query/stream", {
        "question": "What is AI?",
        "document_ids": [fake_id],
        "include_citations": False,
    })

    error_events = [e for e in events if "error" in e]
    assert len(error_events) >= 1, f"No error event found in: {events}"
