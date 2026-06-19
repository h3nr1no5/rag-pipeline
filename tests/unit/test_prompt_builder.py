"""
Unit tests for prompt builder functions in src.domain.services.prompt_builder.

build_prompt tests:
- [Page N] stripping from context (task 6.1)
- Conditional citation instruction block
- Conditional [Source N] labels on context chunks
- Combined scenarios across all three behaviors
- Both tuple (Chunk, float) and object (RetrievedChunkResult) formats
- Edge cases (empty chunks, prompt_sources limits, response_length variants)

clean_response tests:
- [Page N] markers always stripped (unconditional)
- [Source N] markers conditionally stripped based on include_citations
- Edge cases (empty string, no markers, mixed markers, HTML, long text)
- Response length parameter behavior
- Token / chat-template / Markdown cleaning
- Line deduplication and repetition removal
"""

# ============================================================================
# build_prompt tests — originally from pre-existing test file
# ============================================================================

from dataclasses import dataclass

from src.domain.services.prompt_builder import build_prompt
from src.domain.services.prompt_builder import clean_response


# ---------------------------------------------------------------------------
# Mock objects — matching patterns from tests/unit/test_dedup.py
# ---------------------------------------------------------------------------

@dataclass
class RetrievedChunkResult:
    """Mock object simulating RetrievedChunkResult from LangChain/LlamaIndex."""
    chunk_id: str
    content: str
    score: float
    metadata: dict


class MockChunk:
    """Mock Chunk object for tuple format (Chunk, score)."""
    def __init__(self, chunk_id: str, content: str):
        self.id = chunk_id
        self.content = content


# ===================================================================
# 1. [Page N] stripping from context
# ===================================================================

class TestBuildPromptPageStripping:
    """Verify that [Page N] markers are stripped from chunk content."""

    def test_strips_page_marker_without_colon(self):
        """[Page 3] (no colon) should be stripped from context."""
        chunks = [(MockChunk("c1", "[Page 3] Pure water has a pH of 7."), 0.9)]
        prompt = build_prompt("What is the pH of water?", chunks, include_citations=False)
        assert "[Page" not in prompt
        assert "Pure water has a pH of 7." in prompt

    def test_strips_page_marker_with_colon(self):
        """[Page 10]: (with colon) should be stripped."""
        chunks = [(MockChunk("c1", "[Page 10]: Pure water has a pH of 7."), 0.9)]
        prompt = build_prompt("What is the pH of water?", chunks, include_citations=False)
        assert "[Page" not in prompt
        assert "Pure water has a pH of 7." in prompt

    def test_chunks_without_page_marker_unchanged(self):
        """Chunks without [Page N] markers retain their original content."""
        content = "Python is a high-level programming language."
        chunks = [(MockChunk("c1", content), 0.9)]
        prompt = build_prompt("What is Python?", chunks, include_citations=False)
        assert content in prompt

    def test_multiple_chunks_with_varying_page_markers(self):
        """Multiple chunks each with [Page N] markers — all stripped."""
        chunks = [
            (MockChunk("c1", "[Page 1] Python supports multiple paradigms."), 0.9),
            (MockChunk("c2", "[Page 2]: Python has dynamic typing."), 0.8),
            (MockChunk("c3", "[Page 10] Python is interpreted."), 0.7),
        ]
        prompt = build_prompt("Tell me about Python", chunks, include_citations=False)
        assert "Python supports multiple paradigms." in prompt
        assert "Python has dynamic typing." in prompt
        assert "Python is interpreted." in prompt
        assert "[Page" not in prompt

    def test_stripping_before_source_labels_with_citations(self):
        """[Page N] is stripped BEFORE [Source N] label is added."""
        chunks = [(MockChunk("c1", "[Page 5] Important info here."), 0.9)]
        prompt = build_prompt("Any info?", chunks, include_citations=True)
        # Must not produce "[Source 1]: [Page 5] Important info here."
        assert "[Source 1]: [Page 5]" not in prompt
        # Must produce "[Source 1]: Important info here." (page stripped, source added)
        assert "[Source 1]: Important info here." in prompt

    def test_page_marker_in_middle_of_content(self):
        """[Page N] embedded mid-content is stripped correctly."""
        chunks = [(MockChunk("c1", "The Earth [Page 3] is the third planet."), 0.9)]
        prompt = build_prompt("Which planet?", chunks, include_citations=False)
        assert "[Page" not in prompt
        assert "The Earth" in prompt
        assert "is the third planet." in prompt

    def test_page_marker_with_large_number(self):
        """[Page 9999] is stripped just like any other page number."""
        chunks = [(MockChunk("c1", "[Page 9999] Appendix reference here."), 0.9)]
        prompt = build_prompt("Any appendix?", chunks, include_citations=False)
        assert "[Page" not in prompt
        assert "Appendix reference here." in prompt

    def test_page_marker_trailing_only(self):
        """Marker at end of content is stripped cleanly."""
        chunks = [(MockChunk("c1", "End of section. [Page 42]"), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=False)
        assert "[Page" not in prompt
        assert "End of section." in prompt

    def test_page_marker_with_only_colon_no_space(self):
        """[Page N]: immediately followed by text (no space) should strip colon too."""
        chunks = [(MockChunk("c1", "[Page 7]:Important info."), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=False)
        assert "[Page" not in prompt
        assert "Important info." in prompt


# ===================================================================
# 2. Conditional citation instruction block
# ===================================================================

class TestBuildPromptCitationInstruction:
    """Verify the citation instruction block is conditionally included."""

    def test_include_citations_contains_instruction(self):
        """include_citations=True -> citation instruction block present."""
        chunks = [(MockChunk("c1", "Some content."), 0.9)]
        prompt = build_prompt("Test question", chunks, include_citations=True)
        assert "source citation" in prompt.lower()
        assert "CRITICAL" in prompt
        assert "[Source" in prompt

    def test_no_citations_omits_instruction(self):
        """include_citations=False -> citation instruction block absent."""
        chunks = [(MockChunk("c1", "Some content."), 0.9)]
        prompt = build_prompt("Test question", chunks, include_citations=False)
        assert "source citation" not in prompt.lower()
        assert "CRITICAL" not in prompt

    def test_citation_instruction_uses_brackets_example(self):
        """The instruction includes the [Source 1] format example."""
        chunks = [(MockChunk("c1", "Content."), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "[Source " in prompt  # part of the example in the instruction


# ===================================================================
# 3. Conditional [Source N] labels on context chunks
# ===================================================================

class TestBuildPromptSourceLabels:
    """Verify [Source N] labels are conditionally added to context."""

    def test_citations_adds_source_label(self):
        """include_citations=True -> [Source 1]: prefix on context."""
        chunks = [(MockChunk("c1", "Content one."), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "[Source 1]:" in prompt

    def test_no_citations_still_has_source_label(self):
        """include_citations=False -> [Source N]: labels still present in context."""
        chunks = [(MockChunk("c1", "Content one."), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=False)
        assert "[Source 1]:" in prompt

    def test_sequential_numbering(self):
        """Multiple chunks receive sequential [Source 1], [Source 2], etc."""
        chunks = [
            (MockChunk("c1", "First content."), 0.9),
            (MockChunk("c2", "Second content."), 0.8),
            (MockChunk("c3", "Third content."), 0.7),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "[Source 1]:" in prompt
        assert "[Source 2]:" in prompt
        assert "[Source 3]:" in prompt

    def test_sequential_ordering_is_preserved(self):
        """Source labels appear in the same order as input chunks."""
        chunks = [
            (MockChunk("c1", "First."), 0.9),
            (MockChunk("c2", "Second."), 0.8),
            (MockChunk("c3", "Third."), 0.7),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        # Extract the context portion (before "Question:")
        context_section = prompt.split("Question:")[0]
        pos_1 = context_section.index("[Source 1]:")
        pos_2 = context_section.index("[Source 2]:")
        pos_3 = context_section.index("[Source 3]:")
        assert pos_1 < pos_2 < pos_3, "Source labels out of order"


# ===================================================================
# 4. Combined scenarios
# ===================================================================

class TestBuildPromptCombined:
    """Scenarios combining page stripping, citation instruction & source labels."""

    def test_no_citations_everything_off(self):
        """include_citations=False -> no citation block, still has [Source N], [Page N] stripped."""
        chunks = [(MockChunk("c1", "[Page 3] Some content here."), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=False)
        assert "CRITICAL" not in prompt
        assert "[Source 1]:" in prompt
        assert "[Page" not in prompt
        assert "Some content here." in prompt

    def test_citations_everything_on(self):
        """include_citations=True -> citation block, [Source N] labels, [Page N] stripped."""
        chunks = [(MockChunk("c1", "[Page 3] Some content here."), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "CRITICAL" in prompt
        assert "[Source 1]: Some content here." in prompt
        assert "[Page" not in prompt

    def test_non_pdf_chunks_unaffected_by_page_regex(self):
        """Non-PDF chunks without [Page N] are unchanged."""
        content = "This content came from a web page, not a PDF."
        chunks = [(MockChunk("c1", content), 0.9)]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert content in prompt
        assert "[Source 1]: " + content in prompt

    def test_mixed_pdf_and_non_pdf_chunks(self):
        """Mix of PDF (with [Page N]) and non-PDF chunks handled correctly."""
        chunks = [
            (MockChunk("c1", "[Page 1] PDF content here."), 0.9),
            (MockChunk("c2", "Non-PDF web content."), 0.8),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "PDF content here." in prompt
        assert "Non-PDF web content." in prompt
        assert "[Page" not in prompt
        assert "[Source 1]:" in prompt
        assert "[Source 2]:" in prompt


# ===================================================================
# 5. Object-format chunks (RetrievedChunkResult)
# ===================================================================

class TestBuildPromptObjectFormat:
    """Verify build_prompt works with object-format chunks (RetrievedChunkResult)."""

    def test_object_format_page_stripping(self):
        """Page markers stripped from object-format chunks."""
        chunks = [
            RetrievedChunkResult("id1", "[Page 5] Content from object.", 0.9, {}),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "[Page" not in prompt
        assert "Content from object." in prompt

    def test_object_format_source_labels(self):
        """Source labels applied to object-format chunks."""
        chunks = [
            RetrievedChunkResult("id1", "Object content.", 0.9, {}),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "[Source 1]: Object content." in prompt

    def test_object_format_citation_instruction(self):
        """Citation instruction included for object-format chunks."""
        chunks = [
            RetrievedChunkResult("id1", "Content.", 0.9, {}),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "CRITICAL" in prompt

    def test_object_format_no_citations_still_has_labels(self):
        """include_citations=False with object-format: has labels, no instruction."""
        chunks = [
            RetrievedChunkResult("id1", "Some content.", 0.9, {}),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=False)
        assert "CRITICAL" not in prompt
        assert "[Source 1]:" in prompt


# ===================================================================
# 6. Edge cases
# ===================================================================

class TestBuildPromptEdgeCases:
    """Edge cases and boundary conditions for build_prompt."""

    def test_empty_chunks_list(self):
        """Empty chunks list still produces a valid prompt."""
        prompt = build_prompt("What is the meaning of life?", [])
        assert "What is the meaning of life?" in prompt
        assert "Answer:" in prompt
        # Should still have grounding instruction (case-insensitive)
        assert "do not add information" in prompt.lower()

    def test_prompt_sources_limits_chunks(self):
        """prompt_sources caps the number of chunks in the prompt."""
        chunks = [
            (MockChunk(f"c{i}", f"Content chunk {i}."), 0.9 - i * 0.1)
            for i in range(5)
        ]
        prompt = build_prompt("Question?", chunks, prompt_sources=2)
        assert "Content chunk 0." in prompt
        assert "Content chunk 1." in prompt
        assert "Content chunk 2." not in prompt  # capped by prompt_sources

    def test_prompt_sources_larger_than_chunks(self):
        """prompt_sources larger than available chunks -> all chunks included."""
        chunks = [
            (MockChunk(f"c{i}", f"Content chunk {i}."), 0.9 - i * 0.1)
            for i in range(3)
        ]
        prompt = build_prompt("Question?", chunks, prompt_sources=10)
        for i in range(3):
            assert f"Content chunk {i}." in prompt

    def test_prompt_sources_zero(self):
        """prompt_sources=0 means no chunks in context."""
        chunks = [(MockChunk("c1", "Some content."), 0.9)]
        prompt = build_prompt("Question?", chunks, prompt_sources=0)
        assert "Some content." not in prompt  # context is empty

    def test_empty_question(self):
        """Empty question string still produces a valid prompt template."""
        chunks = [(MockChunk("c1", "Some content."), 0.9)]
        prompt = build_prompt("", chunks, include_citations=False)
        assert "Answer:" in prompt
        assert "Some content." in prompt
        assert "Question:" in prompt  # The question line is present

    def test_response_length_concise(self):
        """response_length='concise' embeds the concise instruction."""
        chunks = [(MockChunk("c1", "Content."), 0.9)]
        prompt = build_prompt("Question?", chunks, response_length="concise")
        assert "Be very brief" in prompt

    def test_response_length_normal(self):
        """response_length='normal' is the default."""
        chunks = [(MockChunk("c1", "Content."), 0.9)]
        prompt = build_prompt("Question?", chunks, response_length="normal")
        assert "balanced response" in prompt

    def test_response_length_detailed(self):
        """response_length='detailed' embeds the detailed instruction."""
        chunks = [(MockChunk("c1", "Content."), 0.9)]
        prompt = build_prompt("Question?", chunks, response_length="detailed")
        assert "thorough and comprehensive" in prompt

    def test_mixed_tuple_and_object_chunks(self):
        """Should handle a mix of tuple and object chunks in one call."""
        chunks = [
            (MockChunk("c1", "[Page 2] Tuple content."), 0.9),
            RetrievedChunkResult("id1", "[Page 3] Object content.", 0.8, {}),
        ]
        prompt = build_prompt("Question?", chunks, include_citations=True)
        assert "[Page" not in prompt
        assert "Tuple content." in prompt
        assert "Object content." in prompt
        assert "[Source 1]:" in prompt
        assert "[Source 2]:" in prompt

    def test_default_parameters(self):
        """Default parameter values produce a valid prompt."""
        chunks = [(MockChunk("c1", "Default param test."), 0.9)]
        prompt = build_prompt("Question?", chunks)
        # Defaults: prompt_sources=3, include_citations=True, response_length="normal"
        assert "Default param test." in prompt
        assert "balanced response" in prompt
        assert "[Source 1]:" in prompt
        assert "CRITICAL" in prompt

    def test_large_number_of_chunks(self):
        """Many chunks with [Page N] markers all stripped and labeled."""
        chunks = [
            (MockChunk(f"c{i}", f"[Page {i}] Content #{i}."), 0.9 - i * 0.01)
            for i in range(20)
        ]
        prompt = build_prompt("Question?", chunks, prompt_sources=5, include_citations=True)
        for i in range(5):
            assert f"Content #{i}." in prompt
            assert f"[Source {i+1}]:" in prompt
        assert "Content #5." not in prompt
        assert "[Page" not in prompt


# ============================================================================
# clean_response tests  (new)
# ============================================================================

# ---------------------------------------------------------------------------
# [Page N] — stripped unconditionally regardless of include_citations
# ---------------------------------------------------------------------------

class TestCleanResponsePageStripping:
    """[Page N] markers are always stripped, regardless of include_citations."""

    def test_single_page_marker_stripped(self):
        """A single '[Page 3]' marker should be removed."""
        result = clean_response("The answer is on [Page 3] of the document.")
        assert "[Page 3]" not in result
        assert "The answer is on of the document." == result

    def test_page_marker_with_colon_stripped(self):
        """'[Page 10]:' with trailing colon should be stripped."""
        result = clean_response("See figure [Page 10]: for details.")
        assert "[Page 10]" not in result
        assert "See figure for details." == result

    def test_multiple_page_markers_all_stripped(self):
        """Multiple [Page N] references should all be removed."""
        result = clean_response(
            "[Page 1] Introduction text. [Page 2] Middle section. [Page 3] Conclusion."
        )
        assert "[Page 1]" not in result
        assert "[Page 2]" not in result
        assert "[Page 3]" not in result
        assert "Introduction text. Middle section. Conclusion." == result

    def test_page_stripped_with_citations_enabled(self):
        """[Page N] is stripped even when include_citations=True."""
        result = clean_response(
            "According to [Page 5] the sky is blue.",
            include_citations=True,
        )
        assert "[Page 5]" not in result
        assert "According to the sky is blue." == result

    def test_page_stripped_with_citations_disabled(self):
        """[Page N] is stripped even when include_citations=False."""
        result = clean_response(
            "According to [Page 7] the earth is round.",
            include_citations=False,
        )
        assert "[Page 7]" not in result
        assert "According to the earth is round." == result

    def test_page_marker_with_large_number(self):
        """[Page N] with large N should still be stripped."""
        result = clean_response("Reference [Page 9999] noted here.")
        assert "[Page 9999]" not in result
        assert "Reference noted here." == result

    def test_page_marker_adjacent_to_text(self):
        """[Page N] with no surrounding spaces still stripped, and long enough for dedup."""
        result = clean_response("some text here[Page 3]followed by more content words")
        # After regex: "some text here followed by more content words" (47 chars)
        assert "some text here followed by more content words" == result

    def test_page_marker_with_extra_whitespace(self):
        """[Page N] surrounded by extra whitespace should be stripped cleanly."""
        result = clean_response("meaningful text   [Page 3]   continues here with details")
        # The \s* in the regex consumes all extra whitespace around the marker
        assert "meaningful text continues here with details" == result

    def test_section_marker_stripped(self):
        """[Section N] markers should also be stripped."""
        result = clean_response("Refer to [Section 2.1] for more details here.")
        assert "[Section 2.1]" not in result
        assert "Refer to for more details here." == result


# ---------------------------------------------------------------------------
# [Source N] — conditionally stripped based on include_citations
# ---------------------------------------------------------------------------

class TestCleanResponseSourceStripping:
    """[Source N] markers are preserved or stripped based on include_citations."""

    def test_source_preserved_when_citations_enabled(self):
        """When include_citations=True, [Source 1] should remain in output."""
        result = clean_response(
            "The sky is blue according to [Source 1] the document.",
            include_citations=True,
        )
        assert "[Source 1]" in result

    def test_source_stripped_when_citations_disabled(self):
        """When include_citations=False, [Source 1] should be removed.
        Note: The [Source N] regex does NOT consume surrounding whitespace,
        so the space before the marker becomes a double space."""
        result = clean_response(
            "The sky is blue according to [Source 1] the document.",
            include_citations=False,
        )
        assert "[Source 1]" not in result
        # The space before [Source 1] survives, resulting in a double space
        assert "The sky is blue according to  the document." == result

    def test_multiple_sources_preserved_with_citations(self):
        """All [Source N] markers preserved when include_citations=True."""
        result = clean_response(
            "Apples are fruit [Source 1]. Oranges are citrus [Source 2]. "
            "Bananas are berries according to [Source 3] the source.",
            include_citations=True,
        )
        assert "[Source 1]" in result
        assert "[Source 2]" in result
        assert "[Source 3]" in result

    def test_multiple_sources_stripped_without_citations(self):
        """All [Source N] markers removed when include_citations=False."""
        result = clean_response(
            "Apples are fruit [Source 1]. Oranges are citrus [Source 2].",
            include_citations=False,
        )
        assert "[Source 1]" not in result
        assert "[Source 2]" not in result
        # Should still contain the content without citations
        assert "Apples are fruit" in result
        assert "Oranges are citrus" in result

    def test_source_with_high_number_preserved(self):
        """[Source 42] with an arbitrary high number preserved when citations on."""
        result = clean_response(
            "Deep thought says 42 according to [Source 42] the text.",
            include_citations=True,
        )
        assert "[Source 42]" in result

    def test_source_with_high_number_stripped(self):
        """[Source 42] with an arbitrary high number stripped when citations off."""
        result = clean_response(
            "Deep thought says 42 according to [Source 42] the text.",
            include_citations=False,
        )
        assert "[Source 42]" not in result

    def test_regular_brackets_unaffected_by_source_regex(self):
        """Non-source bracket patterns like [note] should not be affected."""
        result = clean_response(
            "See [note] for additional context [Source 1] here.",
            include_citations=False,
        )
        # [Source 1] stripped, but [note] unrelated brackets preserved
        assert "[note]" in result
        assert "[Source 1]" not in result

    def test_source_and_page_mixed_with_citations(self):
        """With citations on: [Page N] stripped, [Source N] preserved."""
        result = clean_response(
            "[Page 3] The sky is blue according to [Source 1] the text.",
            include_citations=True,
        )
        assert "[Page 3]" not in result
        assert "[Source 1]" in result
        assert "The sky is blue according to [Source 1] the text." == result

    def test_source_and_page_mixed_without_citations(self):
        """With citations off: both [Page N] and [Source N] stripped.
        Note: the whitespace-before-[Source N] survives, creating a double space."""
        result = clean_response(
            "[Page 3] The sky is blue according to [Source 1] the text.",
            include_citations=False,
        )
        assert "[Page 3]" not in result
        assert "[Source 1]" not in result
        assert "The sky is blue according to  the text." == result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestCleanResponseEdgeCases:
    """Edge-case behavior of clean_response()."""

    def test_empty_string(self):
        """Empty string input should return empty string."""
        result = clean_response("")
        assert result == ""

    def test_only_whitespace(self):
        """Whitespace-only input should return empty string."""
        result = clean_response("   \t\n  ")
        assert result == ""

    def test_no_markers_passthrough(self):
        """Text with no special markers should pass through unchanged."""
        text = "The quick brown fox jumps over the lazy dog."
        result = clean_response(text)
        assert result == text

    def test_no_markers_with_punctuation(self):
        """Plain text with punctuation and numbers passes through unchanged."""
        text = (
            "According to the report, 73% of users prefer option A over option B. "
            "This represents a significant increase from last year's 58%."
        )
        result = clean_response(text)
        assert "73%" in result
        assert "option A" in result
        assert "58%" in result

    def test_mixed_page_and_source_with_citations(self):
        """Mixed [Page N] and [Source N] with citations on."""
        text = (
            "Introduction [Page 1] states the thesis according to [Source 1] the text. "
            "Evidence [Page 2] supports this claim according to [Source 2] the text."
        )
        result = clean_response(text, include_citations=True)
        assert "[Page 1]" not in result
        assert "[Page 2]" not in result
        assert "[Source 1]" in result
        assert "[Source 2]" in result

    def test_mixed_page_and_source_without_citations(self):
        """Mixed [Page N] and [Source N] with citations off."""
        text = (
            "Introduction [Page 1] states the thesis according to [Source 1] the text. "
            "Evidence [Page 2] supports this claim according to [Source 2] the text."
        )
        result = clean_response(text, include_citations=False)
        assert "[Page 1]" not in result
        assert "[Page 2]" not in result
        assert "[Source 1]" not in result
        assert "[Source 2]" not in result

    def test_short_text_dropped_by_dedup(self):
        """Text under 10 chars is dropped by dedup (known behavior).
        This is by design; callers should validate length before calling."""
        result = clean_response("Hi")
        assert result == ""

    def test_text_at_eleven_chars_kept(self):
        """Text exactly at the 11-char dedup boundary is kept."""
        result = clean_response("Hello World!")  # 12 chars
        assert "Hello World!" in result

    def test_html_tags_pass_through(self):
        """HTML tags are NOT explicitly neutralized by clean_response.
        This is a known gap: tags such as <script> pass through unmodified.
        Callers should sanitize HTML separately."""
        result = clean_response(
            "User input contains <script>alert('xss')</script> in text.",
            include_citations=False,
        )
        assert "<script>" in result
        assert "alert('xss')" in result

    def test_html_anchor_tag_preserved(self):
        """HTML anchor/img tags pass through unmodified."""
        result = clean_response(
            'Please visit <a href="http://example.com">the link</a> for details here.',
        )
        assert "<a href=" in result

    def test_very_long_text_with_many_markers_no_citations(self):
        """A long text with many [Page N] and [Source N] markers cleaned."""
        paragraphs = []
        for i in range(1, 21):
            paragraphs.append(
                f"This is paragraph number {i} containing meaningful content "
                f"about the topic being discussed [Page {i}]. Additional "
                f"supporting evidence can be found according to [Source {i}] the text."
            )
        text = " ".join(paragraphs)

        result = clean_response(text, include_citations=False)

        # No [Page N] or [Source N] markers should remain
        assert "[Page" not in result
        assert "[Source" not in result
        # Content should still be present (at least some paragraphs)
        assert "paragraph number" in result
        assert "meaningful content" in result

    def test_very_long_text_with_markers_and_citations(self):
        """Long text with citations enabled: [Page N] stripped, [Source N] preserved."""
        paragraphs = []
        for i in range(1, 11):
            paragraphs.append(
                f"Paragraph {i} with meaningful content [Page {i}] and citation "
                f"according to [Source {i}] the text."
            )
        text = " ".join(paragraphs)

        result = clean_response(text, include_citations=True)

        # [Page N] stripped, [Source N] preserved
        assert "[Page" not in result
        assert "[Source" in result
        for i in range(1, 11):
            assert f"[Source {i}]" in result


# ---------------------------------------------------------------------------
# Response length behavior
# ---------------------------------------------------------------------------

class TestCleanResponseLengthBehavior:
    """Behavior of the response_length parameter."""

    def test_normal_length_no_truncation(self):
        """response_length='normal' (default) does not truncate text."""
        text = (
            "The analysis reveals several key findings. First, the data "
            "shows a clear trend. Second, the results confirm the hypothesis. "
            "Third, additional research is needed to validate these conclusions."
        )
        result = clean_response(text, response_length="normal")
        assert result == text

    def test_detailed_length_no_truncation(self):
        """response_length='detailed' passes through without truncation."""
        text = (
            "A thorough examination of the data reveals multiple important "
            "findings. The primary result indicates a strong correlation "
            "between variables X and Y. Secondary analysis shows a moderate "
            "effect in subgroup Z. These findings are consistent with prior "
            "research in the field and suggest several avenues for future work."
        )
        result = clean_response(text, response_length="detailed")
        assert result == text

    def test_concise_truncates_incomplete_sentence(self):
        """response_length='concise' truncates text that does NOT end with punctuation.
        The guard only activates when the last character is not .!?)."""
        text = (
            "First complete sentence here. Second complete sentence here. "
            "Third sentence is cut off without a period"
        )
        result = clean_response(text, response_length="concise")
        # Should be truncated to approximately 2 sentences
        assert "First complete sentence here. Second complete sentence here." == result

    def test_concise_single_sentence_preserved(self):
        """A single sentence ending without punctuation stays as-is."""
        text = "This is just one complete sentence here but no period"
        result = clean_response(text, response_length="concise")
        assert result == text

    def test_concise_does_not_truncate_complete_sentences(self):
        """When text ends with . ! ? or ), concise mode does NOT truncate."""
        text = (
            "First sentence here. Second sentence here! Third sentence here? "
            "Fourth sentence here."
        )
        result = clean_response(text, response_length="concise")
        # All content preserved because text ends with '.'
        assert "First sentence here." in result
        assert "Fourth sentence here." in result

    def test_normal_length_default(self):
        """Default response_length is 'normal' (no truncation)."""
        text = (
            "Sentence one here. Sentence two here. Sentence three here. "
            "Sentence four here. Sentence five here."
        )
        result = clean_response(text)  # No response_length arg -> default
        assert result == text


# ---------------------------------------------------------------------------
# Token and chat-template artifact cleaning
# ---------------------------------------------------------------------------

class TestCleanResponseTokenCleaning:
    """Special-token and chat-template artifact removal."""

    def test_endoftext_token_removed(self):
        """<|endoftext|> token should be removed."""
        result = clean_response("Hello<|endoftext|> world")
        assert "<|endoftext|>" not in result
        assert "Hello world" in result

    def test_im_end_token_removed(self):
        """<|im_end|> token should be removed."""
        result = clean_response("<|im_end|>Final answer here")
        assert "<|im_end|>" not in result

    def test_inst_token_stripped(self):
        """[INST] text is split and only content after is kept."""
        result = clean_response("[INST] instruction text here")
        assert "[INST]" not in result

    def test_human_marker_keeps_before(self):
        """'Human:' marker — text BEFORE the marker is kept."""
        result = clean_response("the important context Human: discard this")
        assert "the important context" in result
        assert "discard this" not in result

    def test_assistant_marker_keeps_before(self):
        """'Assistant:' marker — text BEFORE the marker is kept."""
        result = clean_response("user query text Assistant: model output here")
        assert "user query text" in result
        assert "model output here" not in result

    def test_answer_marker_keeps_before(self):
        """'Answer:' marker — text BEFORE the marker is kept."""
        result = clean_response("What is the capital? Answer: Paris here")
        assert "What is the capital?" in result
        assert "Paris here" not in result

    def test_chat_template_artifact_partially_removed(self):
        """<|im_start|> is replaced first, so the regex matching
        <|im_start|>assistant never fires — 'assistant' is preserved."""
        result = clean_response("<|im_start|>assistant The answer is 42.")
        assert "<|im_start|>" not in result
        # The word 'assistant' survives because <|im_start|> was already removed
        assert "assistant The answer is 42." == result

    def test_inline_marker_phrases_stripped(self):
        """Phrases like 'You Can Ask', 'Examples:', 'Key Points:' cause splits."""
        result = clean_response("main content here You Can Ask more questions now")
        assert "You Can Ask" not in result
        assert "main content here" in result


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------

class TestCleanResponseMarkdownStripping:
    """Markdown formatting is stripped from responses."""

    def test_bold_markers_stripped(self):
        """**bold** should become 'bold'."""
        result = clean_response("This is **very important** text here.")
        assert "**" not in result
        assert "This is very important text here." == result

    def test_italic_markers_stripped(self):
        """*italic* (non-bold) should become 'italic'."""
        result = clean_response("This is *italic* text right here.")
        assert "*italic*" not in result
        assert "This is italic text right here." == result

    def test_strikethrough_markers_stripped(self):
        """~~strikethrough~~ should become 'strikethrough'."""
        result = clean_response("This is ~~strikethrough~~ text here.")
        assert "~~" not in result
        assert "This is strikethrough text here." == result

    def test_heading_markers_stripped(self):
        """# Heading markers should be removed."""
        result = clean_response("# Title text\nSome content here with more words")
        assert "# Title text" not in result


# ---------------------------------------------------------------------------
# Line deduplication
# ---------------------------------------------------------------------------

class TestCleanResponseLineDedup:
    """Duplicate/very-similar lines are removed."""

    def test_exact_duplicate_lines_removed(self):
        """Exactly repeated lines should be deduplicated."""
        text = (
            "This is a sentence about the topic here.\n"
            "This is a sentence about the topic here.\n"
            "This is a different sentence entirely."
        )
        result = clean_response(text)
        assert "This is a sentence about the topic here." in result
        assert "This is a different sentence entirely." in result
        count = result.count("This is a sentence about the topic here.")
        assert count == 1

    def test_similar_line_keys_deduplicated(self):
        """Lines whose first 40 chars lowercase overlap are deduplicated."""
        text = (
            "The capital of France is Paris and it is known for its culture.\n"
            "The capital of France is Paris and it has many museums nearby."
        )
        result = clean_response(text)
        # Both lines share first 40 chars "the capital of france is paris and it "
        assert "The capital of France is Paris" in result


# ---------------------------------------------------------------------------
# Consecutive repetition
# ---------------------------------------------------------------------------

class TestCleanResponseConsecutiveRepetition:
    """Exact consecutive repetition (3+ copies) is collapsed by regex."""

    def test_triple_repetition_collapsed(self):
        """Three consecutive identical 67-char passages collapse to one.
        Note: requires back-to-back repetition with NO separator between
        copies, because strip() removes any trailing whitespace before the
        regex runs."""
        passage = (
            "Experimental results confirm that the hypothesis is supported "
            "by the data collected during the trial period"
        )
        text = passage * 3  # back-to-back, no separators
        result = clean_response(text)
        # After collapse, the passage should appear only once
        assert result.count(passage) == 1
        assert result == passage  # exact match after dedup

    def test_repetition_with_separator_not_collapsed(self):
        """When copies are separated by spaces (after strip), the regex
        does NOT match because the repetition is not contiguous."""
        text = "Repeat this. Repeat this. Repeat this. " * 3
        result = clean_response(text)
        # Not collapsed due to spaces between copies
        assert result.count("Repeat this.") >= 1


# ---------------------------------------------------------------------------
# Default parameter behavior
# ---------------------------------------------------------------------------

class TestCleanResponseDefaults:
    """Default parameter values for clean_response."""

    def test_default_include_citations_is_true(self):
        """Default include_citations=True preserves [Source N] markers."""
        result = clean_response("Some statement according to [Source 1] the text.")
        assert "[Source 1]" in result

    def test_default_strips_pages(self):
        """Default include_citations=True still strips [Page N] markers."""
        result = clean_response("[Page 5] Some statement about the text here.")
        assert "[Page 5]" not in result
