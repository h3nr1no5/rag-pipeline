"""Unit tests for RealisticTestLLM test double."""

import pytest

from tests.doubles.llm import RealisticTestLLM


class TestExtractSourceTexts:
    """Tests for RealisticTestLLM._extract_source_texts()."""

    def test_extracts_multiple_sources(self) -> None:
        """_extract_source_texts parses [Source N]: chunks from build_prompt() output."""
        prompt = (
            "You are a helpful assistant. Answer questions based ONLY\n"
            "on the provided sources below.\n"
            "...\n\n"
            "[Source 1]: The material addition process requires heating to 150°C\n"
            "[Source 2]: Always wear protective equipment when handling chemicals\n\n"
            "Question: how to add material?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        sources = llm._extract_source_texts(prompt)
        assert len(sources) == 2
        assert sources[0] == "The material addition process requires heating to 150°C"
        assert sources[1] == "Always wear protective equipment when handling chemicals"

    def test_no_sources_returns_empty_list(self) -> None:
        """_extract_source_texts returns an empty list when no [Source N]: lines exist."""
        prompt = (
            "You are a helpful assistant.\n\n"
            "Question: how to add material?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        sources = llm._extract_source_texts(prompt)
        assert sources == []

    def test_single_source(self) -> None:
        """_extract_source_texts handles a single source."""
        prompt = (
            "[Source 1]: Just one piece of content here\n\n"
            "Question: test?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        sources = llm._extract_source_texts(prompt)
        assert len(sources) == 1
        assert sources[0] == "Just one piece of content here"

    def test_no_false_match_on_nested_brackets(self) -> None:
        """_extract_source_texts does not match literal [Source X] in content text."""
        prompt = (
            "[Source 1]: The function signature is `process_data(source: str)`\n"
            "[Source 2]: See [Note 1] for details\n\n"
            "Question: test?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        sources = llm._extract_source_texts(prompt)
        assert len(sources) == 2
        assert "[Note 1]" in sources[1]

    def test_single_newline_separator_between_sources(self) -> None:
        """_extract_source_texts handles sources separated by single newline (no blank line)."""
        prompt = (
            "[Source 1]: First source content\n"
            "[Source 2]: Second source content\n\n"
            "Question: test?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        sources = llm._extract_source_texts(prompt)
        assert len(sources) == 2
        assert sources[1] == "Second source content"

    def test_source_with_multiline_content(self) -> None:
        """_extract_source_texts captures multi-line content until the next source."""
        prompt = (
            "[Source 1]: First line of content\n"
            "Second line still in source 1\n"
            "[Source 2]: Next source content\n\n"
            "Question: test?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        sources = llm._extract_source_texts(prompt)
        assert len(sources) == 2
        assert sources[0] == "First line of content\nSecond line still in source 1"


@pytest.mark.asyncio
class TestRealisticTestLLMGenerate:
    """Tests for RealisticTestLLM.generate()."""

    async def test_generate_returns_first_source_when_sources_present(self) -> None:
        """generate() returns a response containing the first source text."""
        prompt = (
            "[Source 1]: The material addition process requires heating to 150°C\n"
            "[Source 2]: Always wear protective equipment\n\n"
            "Question: how to add material?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        result = await llm.generate(prompt)
        assert "material" in result.lower()
        assert "heating" in result.lower()
        assert "Based on the provided material" in result
        assert "The material addition process requires heating to 150°C" in result

    async def test_generate_returns_fallback_when_no_sources(self) -> None:
        """generate() returns the fallback message when no sources are present."""
        prompt = (
            "You are a helpful assistant.\n\n"
            "Question: how to do something?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        result = await llm.generate(prompt)
        assert result == "I don't have enough information to answer this question."

    async def test_generate_truncates_long_source(self) -> None:
        """generate() truncates source text to 200 characters."""
        long_content = "word " * 100  # ~500 chars
        prompt = (
            f"[Source 1]: {long_content}\n\n"
            "Question: test?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        result = await llm.generate(prompt)
        # The response wraps the first 200 chars of the source
        assert len(result) < len(f"Based on the provided material: {long_content}")

    async def test_get_model_name(self) -> None:
        """get_model_name() returns 'realistic-test-llm'."""
        llm = RealisticTestLLM()
        assert llm.get_model_name() == "realistic-test-llm"


@pytest.mark.asyncio
class TestRealisticTestLLMGenerateStream:
    """Tests for RealisticTestLLM.generate_stream()."""

    async def test_generate_stream_yields_same_as_generate_with_sources(self) -> None:
        """generate_stream() yields the same result as generate() when sources present."""
        prompt = (
            "[Source 1]: The material addition process requires heating to 150°C\n\n"
            "Question: how to add material?\n\n"
            "Answer:"
        )
        llm = RealisticTestLLM()
        expected = await llm.generate(prompt)
        chunks = [chunk async for chunk in llm.generate_stream(prompt)]
        assert len(chunks) == 1
        assert chunks[0] == expected

    async def test_generate_stream_yields_same_as_generate_without_sources(self) -> None:
        """generate_stream() yields the same result as generate() when no sources."""
        prompt = "Question: how to add material?\n\nAnswer:"
        llm = RealisticTestLLM()
        expected = await llm.generate(prompt)
        chunks = [chunk async for chunk in llm.generate_stream(prompt)]
        assert len(chunks) == 1
        assert chunks[0] == expected
        assert chunks[0] == "I don't have enough information to answer this question."
