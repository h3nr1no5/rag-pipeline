"""Prompt builder functions for the domain layer."""
import re
import logging

logger = logging.getLogger(__name__)


def deduplicate_chunks(chunks: list, threshold: int = 50) -> list:
    """Remove duplicate chunks based on content signature.

    Handles both:
    - Tuples: (Chunk, float) - from cosine retrieval
    - RetrievedChunkResult/LlamaIndexRetrievedChunk objects - from LangChain/LlamaIndex
    """
    if not chunks:
        return []

    seen_signatures = []
    unique_chunks = []

    for item in chunks:
        # Extract content based on type
        if hasattr(item, 'content'):  # RetrievedChunkResult, LlamaIndexRetrievedChunk
            content = item.content
            score = getattr(item, 'score', 0.0)
        else:  # Tuple (Chunk, float)
            content = item[0].content
            score = item[1]

        sig = content[:threshold].lower().strip()
        if sig not in seen_signatures:
            seen_signatures.append(sig)
            # Keep original item type (if tuple, keep tuple; if object, keep object)
            if hasattr(item, 'content'):
                unique_chunks.append(item)
            else:
                unique_chunks.append((item[0], score))

    return unique_chunks


def build_prompt(question: str, context_chunks: list, prompt_sources: int = 3, include_citations: bool = True, response_length: str = "normal") -> str:
    """Build the prompt for the LLM with context chunks."""
    context_chunks = context_chunks[:prompt_sources]

    def _extract_chunk_content(item):
        if hasattr(item, 'content'):  # Has .content attribute (RetrievedChunkResult)
            return item.content
        else:  # Tuple (Chunk, float)
            return item[0].content

    # Handle both tuple (Chunk, float) and RetrievedChunkResult objects
    context_list = []
    for item in context_chunks:
        if hasattr(item, 'content'):  # RetrievedChunkResult or similar
            content = item.content
        else:  # Tuple (Chunk, float)
            content = item[0].content
        # Strip [Page N] markers from chunk content — these are parser artifacts,
        # not meaningful context for the LLM. Do this before [Source N] labels.
        content = re.sub(r'\s*\[Page \d+\]:?\s*', ' ', content).strip()
        context_list.append(content)

    # Always add [Source N] labels for prompt template splitting
    context_text = "\n\n".join([
        f"[Source {i+1}]: {content}"
        for i, content in enumerate(context_list)
    ])
    
    # Build citation instruction based on include_citations
    if include_citations:
        citation_block = (
            "CRITICAL — For EVERY factual statement you make, you MUST include "
            "a source citation in brackets like [Source 1] immediately after the "
            "statement. If a statement is not supported by any source, you MUST NOT make it. "
            "Do not guess or use outside knowledge.\n\n"
        )
    else:
        citation_block = ""

    # Grounding instruction (replaces "in your own words" anti-pattern)
    grounding_instruction = (
        "Quote or closely paraphrase the sources. "
        "Do not add information that is not present in the sources. "
        "It is better to say \"I don't know\" than to make up information."
    )

    # Set verbosity based on response_length
    verbosity = {
        "concise": "Be very brief (1-2 sentences).",
        "normal": "Give a clear, balanced response of appropriate length.",
        "detailed": "Provide a thorough and comprehensive answer with examples where possible."
    }.get(response_length, "")

    prompt = f"""You are a helpful assistant. Answer questions based ONLY on the provided sources below.
If the answer cannot be determined from the sources, say "I don't have enough information to answer this question."
{citation_block}{verbosity}

IMPORTANT: Avoid repeating information. Do not restate the same point multiple times.
Structure your response clearly using Markdown formatting — you may use headings, bold for emphasis, and bullet points for lists. Keep paragraphs concise and avoid repetition. Do NOT output raw HTML tags.
{grounding_instruction}

{context_text}

Question: {question}

Answer:"""
    
    if prompt:
        logger.debug(f"Prompt ({len(prompt)} chars): {prompt[:500]}{'...' if len(prompt) > 500 else ''}")
    else:
        logger.debug("Prompt: (empty or None)")
    
    return prompt


def _strip_repetition(text: str) -> str:
    """Remove repeated content where a long suffix already appeared earlier."""
    if len(text) < 60:
        return text
    for start in range(len(text) - 30, len(text) // 3, -1):
        suffix = text[start:]
        if len(suffix) < 20:
            continue
        earlier = text[:start]
        if suffix in earlier:
            return earlier + suffix
    return text


def clean_response(text: str, response_length: str = "normal", include_citations: bool = True) -> str:
    """Clean LLM response by removing special tokens and artifacts."""
    return text
    text = text.replace("<|endoftext|>", "")
    text = text.replace("<|eos|>", "")
    text = text.replace("<|eot|>", "")
    text = text.replace("<|end|>", "")
    text = text.replace("<|im_end|>", "")
    text = text.replace("<|im_start|>", "")
    
    text = text.split("<|")[0] if "<|" in text else text
    text = text.strip()
    
    for token in ["[INST]", "[/INST]", "[SYS]", "[/SYS]", "<<SYS>>", "<</SYS>>"]:
        if token in text:
            text = text.split(token)[-1]
    
    for marker in ["Human:", "human:", "Assistant:", "assistant:", "Question:", "Answer:", "Sources:"]:
        if marker in text:
            text = text.split(marker)[0]
    
    text = text.split("You Can Ask")[0].strip()
    text = text.split("Test Questions")[0].strip()
    text = text.split("Examples:")[0].strip()
    text = text.split("Key Points:")[0].strip()
    
    # Strip chat template artifacts that leak into output
    text = re.sub(r'<\|im_start\|>assistant\s*', '', text)
    text = re.sub(r'<\|im_start\|>user\s*', '', text)
    
    # Strip tokenization artifacts (e.g. ": rgan:" from "RAG" split across tokens)
    text = re.sub(r'\s*:\s*[a-z]{2,5}\s*:\s*', ' ', text)
    
    # Strip inline page/section references that leaked from source verbatim reproduction
    text = re.sub(r'\s*\[Page \d+\]:?\s*', ' ', text)
    text = re.sub(r'\s*\[Section \d+(\.\d+)*\]:?\s*', ' ', text)
    

    # Only strip citations if they weren't requested
    if not include_citations:
        text = re.sub(r'\[Source \d+\]', '', text)
    
    lines = text.split("\n")
    unique_lines = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        line_key = stripped.lower()[:40]
        is_dup = any(line_key in s or s in line_key for s in seen)
        if len(stripped) > 10 and not is_dup:
            seen.add(line_key)
            unique_lines.append(line)  # Keep original line (preserves indentation)

    text = "\n".join(unique_lines)
    
    # Remove exact consecutive repetition (3+ identical copies)
    text = re.sub(r'(.{20,200})\1{2,}', r'\1', text)
    
    # Remove repetition where the first occurrence differs from later ones
    text = _strip_repetition(text)
    
    text = text.strip()

    # Only truncate sentences for "concise" mode
    if response_length == "concise" and text and text[-1] not in '.!?)':
        last_period = text.rfind('. ')
        if last_period > 0:
            # Find second-to-last period for 1-2 sentences
            second_last = text.rfind('. ', last_period - 1)
            if second_last > 0:
                text = text[:second_last + 1]
            else:
                text = text[:last_period + 1]
    elif response_length == "detailed":
        # Don't truncate at all - return full response
        pass  # Keep as-is

    return text.strip()