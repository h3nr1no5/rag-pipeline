"""
Unit tests for the ResponseVerifier class.

Tests the full verification pipeline including sentence splitting,
citation parsing, source matching via cosine similarity, and the
overall verify() orchestration method.
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.services.verification import ResponseVerifier, VerifiedResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings():
    """Fixture that patches settings with verification defaults."""
    with patch('src.domain.services.verification.settings') as s:
        s.verification_enabled = True
        s.verification_similarity_threshold = 0.65
        s.verification_remove_unsupported = True
        yield s


@pytest.fixture
def verifier(mock_settings):
    """Return a bare ResponseVerifier (no mocks attached)."""
    v = ResponseVerifier()
    return v


def _make_cross_encoder_mock(scores, use_side_effect=False):
    """Create a mock for the cross-encoder pipeline.

    Args:
        scores: Either a fixed list (e.g. [0.95]) for return_value,
                or a list-of-lists (e.g. [[0.95], [0.3]]) for side_effect.
        use_side_effect: If True, treat scores as side_effect list.
    """
    mock_model = MagicMock()  # predict() called via asyncio.to_thread — must be sync
    if use_side_effect:
        mock_model.predict.side_effect = scores
    else:
        mock_model.predict.return_value = scores
    mock_reranker = AsyncMock()
    mock_reranker._ensure_model = AsyncMock(return_value=mock_model)
    return mock_reranker


def _setup_verifier(verifier, cross_scores, use_side_effect=False):
    """Attach a cross-encoder mock to a ResponseVerifier instance."""
    verifier._get_reranker = AsyncMock(
        return_value=_make_cross_encoder_mock(cross_scores, use_side_effect)
    )


# ===================================================================
# _split_sentences
# ===================================================================

class TestSplitSentences:
    """Unit tests for ResponseVerifier._split_sentences()."""

    def test_empty_string(self, verifier):
        """Empty string yields empty list."""
        assert verifier._split_sentences("") == []

    def test_only_whitespace(self, verifier):
        """Whitespace-only string yields empty list."""
        assert verifier._split_sentences("   \n  ") == []

    def test_single_sentence(self, verifier):
        """Single sentence without trailing punctuation."""
        result = verifier._split_sentences("Hello world")
        assert result == ["Hello world"]

    def test_single_sentence_with_period(self, verifier):
        """Single sentence with trailing period."""
        result = verifier._split_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_multiple_sentences_period(self, verifier):
        """Multiple sentences separated by period+space."""
        result = verifier._split_sentences("First sentence. Second sentence. Third.")
        assert result == ["First sentence.", "Second sentence.", "Third."]

    def test_sentences_with_exclamation(self, verifier):
        """Sentences separated by ! and whitespace."""
        result = verifier._split_sentences("Wow! Amazing! Incredible.")
        assert result == ["Wow!", "Amazing!", "Incredible."]

    def test_sentences_with_question_mark(self, verifier):
        """Sentences separated by ? and whitespace."""
        result = verifier._split_sentences("How are you? I am fine. Good.")
        assert result == ["How are you?", "I am fine.", "Good."]

    def test_mixed_punctuation(self, verifier):
        """Mixed punctuation: . ! ?"""
        result = verifier._split_sentences("Stop! Are you sure? I think so.")
        assert result == ["Stop!", "Are you sure?", "I think so."]

    def test_abbreviations_not_split(self, verifier):
        """Abbreviations like 'Dr.' or 'U.S.' should NOT split mid-sentence
        because the regex splits on punctuation FOLLOWED BY whitespace,
        and 'Dr.' followed by a space would incorrectly split.

        NOTE: 'Dr. Smith' WILL split because the pattern (?<=[.!?])\\s+
        matches the space after 'Dr.'. This is an accepted limitation of
        the simple regex approach — the feature spec documents this.
        """
        result = verifier._split_sentences("Dr. Smith went to Washington.")
        # 'Dr.' matches (?<=[.!?])\s+, so it splits after 'Dr.'
        # This is the expected behaviour for the simple regex
        assert len(result) >= 2

    def test_newline_separator(self, verifier):
        """Newlines should act as sentence separators."""
        result = verifier._split_sentences("Line one.\nLine two.\nLine three.")
        assert result == ["Line one.", "Line two.", "Line three."]

    def test_trailing_whitespace(self, verifier):
        """Leading/trailing whitespace is stripped per-sentence."""
        result = verifier._split_sentences("  Hello.   World.  ")
        assert result == ["Hello.", "World."]

    def test_newline_without_punctuation(self, verifier):
        """A bare newline without preceding punctuation does NOT split."""
        result = verifier._split_sentences("Hello\nWorld")
        assert result == ["Hello\nWorld"]


# ===================================================================
# _parse_citations
# ===================================================================

class TestParseCitations:
    """Unit tests for ResponseVerifier._parse_citations()."""

    def test_no_citations(self, verifier):
        """Text with no [Source N] patterns."""
        result = verifier._parse_citations("Hello world. This is a test.")
        assert result == {0: [], 1: []}

    def test_single_citation(self, verifier):
        """Single [Source 1] in text."""
        result = verifier._parse_citations("According to the docs [Source 1].")
        assert result == {0: [1]}

    def test_multiple_citations_one_sentence(self, verifier):
        """Multiple citations [Source 1] and [Source 2] in same sentence."""
        result = verifier._parse_citations(
            "Data from [Source 1] and [Source 2] supports this."
        )
        assert result == {0: [1, 2]}

    def test_citations_in_multiple_sentences(self, verifier):
        """Citations in different sentences."""
        text = "First source [Source 1]. Second source [Source 2]. No citation here."
        result = verifier._parse_citations(text)
        assert result == {0: [1], 1: [2], 2: []}

    def test_large_source_number(self, verifier):
        """[Source 9999] should be parsed as integer 9999."""
        result = verifier._parse_citations("Refer to [Source 9999] for details.")
        assert result == {0: [9999]}

    def test_source_zero(self, verifier):
        """[Source 0] should parse as integer 0 (validation is separate)."""
        result = verifier._parse_citations("See [Source 0].")
        assert result == {0: [0]}

    def test_lowercase_source_not_matched(self, verifier):
        """[source 1] (lowercase) should NOT be matched by regex."""
        result = verifier._parse_citations("See [source 1].")
        assert result == {0: []}

    def test_malformed_brackets(self, verifier):
        """Missing closing bracket should not match."""
        result = verifier._parse_citations("See [Source 1 for reference.")
        assert result == {0: []}

    def test_empty_text(self, verifier):
        """Empty text yields empty dict."""
        result = verifier._parse_citations("")
        assert result == {}

    def test_no_spaces_in_pattern(self, verifier):
        """[Source1] (no space) should NOT match [Source N]."""
        result = verifier._parse_citations("See [Source1].")
        assert result == {0: []}

    def test_consecutive_citations(self, verifier):
        """Consecutive citations like [Source 1][Source 2]."""
        result = verifier._parse_citations("See [Source 1][Source 2].")
        assert result == {0: [1, 2]}


# ===================================================================
# _find_best_source_match
# ===================================================================

class TestScoreWithCrossEncoder:
    """Unit tests for ResponseVerifier._score_with_cross_encoder()."""

    @pytest.fixture
    def verifier(self):
        return ResponseVerifier()

    @pytest.mark.asyncio
    async def test_returns_list_of_scores(self, verifier):
        """Returns one score per source text."""
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.9, 0.3, 0.7]
        mock_reranker = AsyncMock()
        mock_reranker._ensure_model = AsyncMock(return_value=mock_model)
        verifier._get_reranker = AsyncMock(return_value=mock_reranker)

        scores = await verifier._score_with_cross_encoder(
            "Test sentence.", ["Source A", "Source B", "Source C"]
        )
        assert len(scores) == 3
        assert scores == [0.9, 0.3, 0.7]

    @pytest.mark.asyncio
    async def test_empty_source_texts(self, verifier):
        """Empty source list returns empty scores."""
        mock_model = MagicMock()
        mock_model.predict.return_value = []
        mock_reranker = AsyncMock()
        mock_reranker._ensure_model = AsyncMock(return_value=mock_model)
        verifier._get_reranker = AsyncMock(return_value=mock_reranker)

        scores = await verifier._score_with_cross_encoder("Test.", [])
        assert scores == []

    @pytest.mark.asyncio
    async def test_single_source(self, verifier):
        """Single source returns single score."""
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.85]
        mock_reranker = AsyncMock()
        mock_reranker._ensure_model = AsyncMock(return_value=mock_model)
        verifier._get_reranker = AsyncMock(return_value=mock_reranker)

        scores = await verifier._score_with_cross_encoder("Sentence.", ["Source"])
        assert len(scores) == 1
        assert scores[0] == 0.85

    @pytest.mark.asyncio
    async def test_negative_score(self, verifier):
        """Cross-encoder can return negative scores."""
        mock_model = MagicMock()
        mock_model.predict.return_value = [-0.5, 0.2]
        mock_reranker = AsyncMock()
        mock_reranker._ensure_model = AsyncMock(return_value=mock_model)
        verifier._get_reranker = AsyncMock(return_value=mock_reranker)

        scores = await verifier._score_with_cross_encoder("Bad.", ["Src A", "Src B"])
        assert scores[0] == -0.5

    @pytest.mark.asyncio
    async def test_empty_sentence(self, verifier):
        """Empty sentence still returns valid scores."""
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.1]
        mock_reranker = AsyncMock()
        mock_reranker._ensure_model = AsyncMock(return_value=mock_model)
        verifier._get_reranker = AsyncMock(return_value=mock_reranker)

        scores = await verifier._score_with_cross_encoder("", ["Source"])
        assert len(scores) == 1
        assert isinstance(scores[0], float)


# ===================================================================
# verify — full pipeline
# ===================================================================

class TestVerifyBypass:
    """When verification_enabled=False, response passes through unchanged."""

    @pytest.mark.asyncio
    async def test_bypass_when_disabled(self):
        """verification_enabled=False returns original text with confidence=1.0."""
        with patch('src.domain.services.verification.settings') as s:
            s.verification_enabled = False
            verifier = ResponseVerifier()
            result = await verifier.verify("Some response.", ["source"])
            assert result.verified_text == "Some response."
            assert result.citations == []
            assert result.unsupported == []
            assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_bypass_empty_response(self):
        """Bypass with empty response still returns it."""
        with patch('src.domain.services.verification.settings') as s:
            s.verification_enabled = False
            verifier = ResponseVerifier()
            result = await verifier.verify("", ["source"])
            assert result.verified_text == ""
            assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_bypass_no_sources(self):
        """Bypass with no sources still returns original."""
        with patch('src.domain.services.verification.settings') as s:
            s.verification_enabled = False
            verifier = ResponseVerifier()
            result = await verifier.verify("Test.", [])
            assert result.verified_text == "Test."
            assert result.confidence == 1.0


class TestVerifyNoSources:
    """When sources list is empty, verification returns original text."""

    @pytest.mark.asyncio
    async def test_no_sources_returns_original(self, mock_settings, caplog):
        """Empty sources => warning logged, text returned unchanged, confidence=1.0."""
        verifier = ResponseVerifier()

        with caplog.at_level(logging.WARNING):
            result = await verifier.verify("Some response.", [])

            assert "No source texts provided" in caplog.text
            assert result.verified_text == "Some response."
            assert result.confidence == 1.0


class TestVerifyEmptyResponse:
    """Empty response should return confidence 0.0."""

    @pytest.mark.asyncio
    async def test_empty_response_confidence_zero(self, mock_settings):
        """Empty response => confidence=0.0 regardless of sources."""
        verifier = ResponseVerifier()

        result = await verifier.verify("", ["source one", "source two"])

        assert result.verified_text == ""
        assert result.confidence == 0.0
        assert result.citations == []
        assert result.unsupported == []

    @pytest.mark.asyncio
    async def test_whitespace_only_response(self, mock_settings):
        """Whitespace-only response => confidence=0.0."""
        verifier = ResponseVerifier()

        result = await verifier.verify("   \n  ", ["source"])

        assert result.confidence == 0.0
        assert result.verified_text == "   \n  "


class TestVerifySourcesContentAttribute:
    """Sources can be objects with .content or plain strings."""

    @pytest.mark.asyncio
    async def test_source_objects_with_content_attr(self, mock_settings):
        """Sources with .content attribute are handled."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        class SourceObj:
            def __init__(self, content):
                self.content = content

        sources = [SourceObj("Python is great for data science.")]
        result = await verifier.verify("Python is great.", sources)

        # Sentence should match source
        assert "Python is great" in result.verified_text
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_source_strings(self, mock_settings):
        """Plain string sources are handled."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        result = await verifier.verify("Python is great.", ["Python source content."])
        assert "Python is great" in result.verified_text
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_mixed_source_types(self, mock_settings):
        """Mix of string and object sources."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95, 0.2])

        class SourceObj:
            def __init__(self, content):
                self.content = content

        sources = ["string source", SourceObj("object source")]
        result = await verifier.verify("String source.", sources)

        assert "String source" in result.verified_text

    @pytest.mark.asyncio
    async def test_source_without_content_and_not_string(self, mock_settings):
        """Source that is neither string nor has .content is skipped."""
        verifier = ResponseVerifier()

        result = await verifier.verify("Test.", [42])  # int has no .content

        # No valid source texts => same as no sources
        assert result.verified_text == "Test."
        assert result.confidence == 1.0


class TestVerifyAllSentencesSupported:
    """All sentences find a matching source."""

    @pytest.mark.asyncio
    async def test_single_sentence_supported(self, mock_settings):
        """Single sentence matches a source."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [1.0])

        result = await verifier.verify("Supported claim.", ["Source content."])

        assert result.verified_text == "Supported claim."
        assert result.unsupported == []
        assert result.confidence == pytest.approx(1.0, rel=1e-6)
        assert len(result.citations) == 1
        assert result.citations[0]["source_indices"] == [1]

    @pytest.mark.asyncio
    async def test_multiple_sentences_all_supported(self, mock_settings):
        """Multiple sentences each match a source."""
        verifier = ResponseVerifier()
        # First sentence best-matches source 1, second best-matches source 2
        _setup_verifier(verifier, [[0.95, 0.1], [0.1, 0.95]], use_side_effect=True)

        result = await verifier.verify(
            "First claim. Second claim.",
            ["Source one.", "Source two."],
        )

        assert "First claim." in result.verified_text
        assert "Second claim." in result.verified_text
        assert result.unsupported == []
        assert result.confidence > 0.0


class TestVerifyAllSentencesUnsupported:
    """Sentences that do not match any source."""

    @pytest.mark.asyncio
    async def test_remove_unsupported_true(self, mock_settings):
        """remove_unsupported=True removes all unsupported sentences,
        returns fallback message."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.0])  # below threshold 0.5

        result = await verifier.verify(
            "Unsupported claim.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=True,
        )

        # All sentences removed => fallback message
        assert result.verified_text == "I don't have enough information to answer this question."
        assert result.unsupported == ["Unsupported claim."]
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_remove_unsupported_false(self, mock_settings):
        """remove_unsupported=False keeps sentences but flags them."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.0])  # below threshold 0.5

        result = await verifier.verify(
            "Unsupported claim.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=False,
        )

        # Sentence kept but flagged
        assert result.verified_text == "Unsupported claim."
        assert result.unsupported == ["Unsupported claim."]
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_multiple_all_unsupported_removed(self, mock_settings):
        """Multiple unsupported sentences with remove=True all removed."""
        verifier = ResponseVerifier()
        # Both sentences get score 0.0 (below threshold 0.5)
        _setup_verifier(verifier, [0.0])

        result = await verifier.verify(
            "First bad. Second bad.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=True,
        )

        assert result.verified_text == "I don't have enough information to answer this question."
        assert len(result.unsupported) == 2
        assert result.confidence == 0.0


class TestVerifyMixedSupportedUnsupported:
    """Mix of supported and unsupported sentences."""

    @pytest.mark.asyncio
    async def test_mixed_with_remove_true(self, mock_settings):
        """Supported kept, unsupported removed."""
        verifier = ResponseVerifier()
        # S1 best-match src 1, S2 best-match src 2, S3 no match
        _setup_verifier(verifier, [[0.95, 0.1], [0.1, 0.95], [-0.5, -0.5]], use_side_effect=True)

        result = await verifier.verify(
            "First claim. Second claim. Made up claim.",
            ["Source one.", "Source two."],
            similarity_threshold=0.5,
            remove_unsupported=True,
        )

        assert "First claim." in result.verified_text
        assert "Second claim." in result.verified_text
        assert "Made up claim." not in result.verified_text
        assert result.unsupported == ["Made up claim."]
        assert len(result.citations) == 3

    @pytest.mark.asyncio
    async def test_mixed_with_remove_false(self, mock_settings):
        """Supported kept, unsupported flagged but kept."""
        verifier = ResponseVerifier()
        # S1 matches, S2 no match
        _setup_verifier(verifier, [[0.95], [-0.5]], use_side_effect=True)

        result = await verifier.verify(
            "Good sentence. Bad sentence.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=False,
        )

        assert "Good sentence." in result.verified_text
        assert "Bad sentence." in result.verified_text
        assert result.unsupported == ["Bad sentence."]


class TestVerifyWithCitations:
    """Tests involving explicit [Source N] citations in the response."""

    @pytest.mark.asyncio
    async def test_valid_citation(self, mock_settings):
        """Valid [Source 1] citation is kept when score passes threshold."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95, 0.3])

        result = await verifier.verify(
            "Claim from source one [Source 1].",
            ["Source one.", "Source two."],
            similarity_threshold=0.5,
        )

        assert result.citations[0]["source_indices"] == [1]

    @pytest.mark.asyncio
    async def test_invalid_citation_out_of_range(self, mock_settings, caplog):
        """Citation [Source 999] out of range: logged as warning and dropped,
        falls back to retroactive matching."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        with caplog.at_level(logging.WARNING):
            result = await verifier.verify(
                "Claim [Source 999].",
                ["Only source."],
                similarity_threshold=0.5,
            )

        assert "out of range" in caplog.text
        assert "999" in caplog.text
        # Invalid citation dropped; retroactive matching picks source 1
        assert result.citations[0]["source_indices"] == [1]

    @pytest.mark.asyncio
    async def test_citation_source_zero(self, mock_settings, caplog):
        """Citation [Source 0] is out of range (sources are 1-based)."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        with caplog.at_level(logging.WARNING):
            result = await verifier.verify(
                "Claim [Source 0].",
                ["Only source."],
                similarity_threshold=0.5,
            )

        assert "out of range" in caplog.text
        # Drops invalid citation, picks the right one via retroactive matching
        assert result.citations[0]["source_indices"] == [1]

    @pytest.mark.asyncio
    async def test_citation_fails_similarity_check(self, mock_settings):
        """Cited source exists but score is below threshold,
        falls back to retroactive matching."""
        verifier = ResponseVerifier()
        # Cited source 1 has score 0.1 (below 0.5), source 2 has 0.95 (above)
        _setup_verifier(verifier, [0.1, 0.95])

        result = await verifier.verify(
            "Claim citing source one [Source 1].",
            ["Source one.", "Source two."],
            similarity_threshold=0.5,
        )

        # Cited source (Src1) fails threshold, so retroactive picks Src2
        assert result.citations[0]["source_indices"] == [2]


class TestVerifyParameterOverrides:
    """verify() accepts optional parameters to override settings."""

    @pytest.mark.asyncio
    async def test_similarity_threshold_override(self, mock_settings):
        """Passing similarity_threshold overrides the setting."""
        verifier = ResponseVerifier()
        # Score 0.7 is below the overridden threshold of 0.8
        _setup_verifier(verifier, [0.7])

        # Default is 0.65 in mock_settings, but we pass 0.8 (higher)
        result = await verifier.verify(
            "Test.",
            ["Source content."],
            similarity_threshold=0.8,
        )

        # 0.7 < 0.8 → not supported
        assert result.unsupported == ["Test."]

    @pytest.mark.asyncio
    async def test_remove_unsupported_override(self, mock_settings):
        """Passing remove_unsupported overrides the setting."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.0])  # below threshold 0.5

        # Default is True in mock_settings, but we pass False
        result = await verifier.verify(
            "Test.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=False,
        )

        # Sentence kept despite no match
        assert result.verified_text == "Test."
        assert result.unsupported == ["Test."]


class TestVerifyConfidenceCalculation:
    """Confidence is the average of per-sentence similarity scores."""

    @pytest.mark.asyncio
    async def test_all_perfect_matches(self, mock_settings):
        """All sentences have score=1.0 => confidence = 1.0."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [1.0])

        result = await verifier.verify(
            "A. B. C.",
            ["Source content."],
            similarity_threshold=0.5,
        )

        assert result.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_matches(self, mock_settings):
        """Some matches, some no-matches => mixed confidence.
        Both supported and unsupported sentences contribute to scores array
        (unsupported get score 0.0), so the average reflects both."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [[1.0], [0.0]], use_side_effect=True)

        result = await verifier.verify(
            "Supported. Unsupported.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=True,
        )

        # scores = [1.0, 0.0] → avg = 0.5
        assert result.confidence == pytest.approx(0.5, rel=1e-6)

    @pytest.mark.asyncio
    async def test_no_matches_with_remove_true(self, mock_settings):
        """All removed => confidence = 0.0."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.0])  # below threshold 0.5

        result = await verifier.verify(
            "Unsupported.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=True,
        )

        assert result.confidence == pytest.approx(0.0)


class TestVerifyFallbackMessage:
    """When all sentences are removed, a fallback message is returned."""

    @pytest.mark.asyncio
    async def test_fallback_text(self, mock_settings):
        """All sentences unsupported with remove=True => fallback."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.0])  # below threshold 0.5

        result = await verifier.verify(
            "Totally unrelated.",
            ["Source content."],
            similarity_threshold=0.5,
            remove_unsupported=True,
        )

        assert result.verified_text == "I don't have enough information to answer this question."


# ===================================================================
# Edge cases for the full verify() method
# ===================================================================

class TestVerifyEdgeCases:
    """Additional edge cases."""

    @pytest.mark.asyncio
    async def test_verify_with_no_reranker_cache(self):
        """When _reranker is None, _get_reranker lazily loads it.
        We verify this by patching the import path."""
        with patch('src.domain.services.verification.settings') as s:
            s.verification_enabled = True
            s.verification_similarity_threshold = 0.5
            s.verification_remove_unsupported = True

            mock_model = MagicMock()
            mock_model.predict.return_value = [0.95]
            mock_reranker = AsyncMock()
            mock_reranker._ensure_model = AsyncMock(return_value=mock_model)

            with patch(
                'src.domain.services.verification.ResponseVerifier._get_reranker',
                new_callable=AsyncMock,
                return_value=mock_reranker,
            ):
                verifier = ResponseVerifier()
                # At this point _reranker is None
                assert verifier._reranker is None

                result = await verifier.verify(
                    "Test sentence.",
                    ["Source content."],
                )

                assert "Test sentence." in result.verified_text

    @pytest.mark.asyncio
    async def test_logging_warning_invalid_citation(self, mock_settings, caplog):
        """Invalid citation indices log a warning with details."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        with caplog.at_level(logging.WARNING):
            await verifier.verify(
                "Claim [Source 5].",
                ["Only source."],
                similarity_threshold=0.5,
            )

        assert any("Citation" in msg and "out of range" in msg for msg in caplog.messages)
        assert any("5" in msg for msg in caplog.messages)

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, mock_settings):
        """Confidence is always between 0.0 and 1.0."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        result = await verifier.verify(
            "Test.",
            ["Source content."],
            similarity_threshold=0.0,  # anything passes
        )

        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_very_long_response(self, mock_settings):
        """Very long response with many sentences is handled."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [1.0])

        sentences = " ".join(f"Sentence {i}." for i in range(50))
        result = await verifier.verify(
            sentences,
            ["Source content."],
            similarity_threshold=0.5,
        )

        assert len(result.citations) == 50
        assert result.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_response_with_only_citations(self, mock_settings):
        """Response with trailing citation markers."""
        verifier = ResponseVerifier()
        _setup_verifier(verifier, [0.95])

        result = await verifier.verify(
            "This is a fact [Source 1].",
            ["Source fact."],
            similarity_threshold=0.5,
        )

        assert result.citations[0]["source_indices"] == [1]


# ===================================================================
# VerifiedResponse dataclass
# ===================================================================

class TestVerifiedResponseDataclass:
    """Unit tests for the VerifiedResponse dataclass."""

    def test_default_values(self):
        """Default values are as expected."""
        vr = VerifiedResponse(verified_text="test")
        assert vr.verified_text == "test"
        assert vr.citations == []
        assert vr.unsupported == []
        assert vr.confidence == 0.0

    def test_custom_values(self):
        """All fields can be set."""
        vr = VerifiedResponse(
            verified_text="result",
            citations=[{"sentence": "test", "source_indices": [1]}],
            unsupported=["fake claim"],
            confidence=0.75,
        )
        assert vr.verified_text == "result"
        assert len(vr.citations) == 1
        assert vr.unsupported == ["fake claim"]
        assert vr.confidence == 0.75
