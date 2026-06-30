import asyncio
import hashlib
import logging
import threading
import time
from collections.abc import AsyncGenerator

from ...core.config import get_settings
from ...core.exceptions import LLMError
from ...core.logging import log_structured
from ...domain.ports.llm import LLM

settings = get_settings()
logger = logging.getLogger(__name__)

_GENERATE_LOCK_TIMEOUT = 300.0  # 5 minutes max wait for GPU lock

# WARNING: This module-level singleton is mutated by test fixtures
# (tests/integration/conftest.py, tests/integration/test_rag_pipelines_e2e.py)
# to inject test doubles. NEVER mutate this in production code.
_llm_instance = None
_llm_load_time = None
_llm_load_status = "idle"
_llm_load_progress = ""
_llm_load_error = None


def _apply_chat_template(tokenizer, prompt: str) -> str:
    """Apply the model's chat template if available, splitting into system/user messages.

    The prompt from build_prompt() has the structure:

        [system instructions]

        [Source 1]: ...context...
        ...

        Question: ...

        Answer:

    We split at the first `[Source N]` marker so system instructions go
    to the system message and context + question go to the user message.
    """
    if not (hasattr(tokenizer, "chat_template") and tokenizer.chat_template is not None):
        return prompt

    # Find the boundary between instructions and context
    source_idx = prompt.find("\n[Source ")
    if source_idx >= 0:
        instructions = prompt[:source_idx].strip()
        context_and_question = prompt[source_idx:].strip()
        # Remove trailing "Answer:" since add_generation_prompt adds the assistant marker
        if context_and_question.endswith("Answer:"):
            context_and_question = context_and_question[:-len("Answer:")].strip()
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": context_and_question},
        ]
    else:
        # No context chunks — wrap entire prompt as user message
        messages = [{"role": "user", "content": prompt}]

    try:
        formatted = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        return formatted
    except Exception as e:
        logger.warning(f"Chat template failed, falling back to raw prompt: {e}")
        return prompt


def _detect_repetition(text: str, min_span: int = 20) -> int | None:
    """Detect if the output has entered a repetition loop.

    Returns the character index where repetition starts, or None.
    Uses sliding window: if the last min_span chars match a previous
    span in the last ~200 chars of output, repetition is likely.
    """
    if len(text) < min_span * 3:
        return None

    tail = text[-300:]  # only scan recent output
    last_span = tail[-min_span:]
    earlier = tail[:-min_span]

    # Check if the last span repeats at least twice in recent output
    count = earlier.count(last_span)
    if count >= 2:
        # Find the first occurrence in full text
        idx = text.find(last_span)
        if idx >= 0 and idx < len(text) - min_span * 3:
            return idx + min_span

    return None


class MLXLLM(LLM):
    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._load_lock = threading.Lock()
        self._generate_lock = asyncio.Lock()
        self._model_loaded = False
        self._model_path = None
        self._generation_count = 0
        self._total_tokens_generated = 0
        self._last_truncated = False
        try:
            from mlx_lm import load
            self._load = load
            self._model_loaded = True
            logger.info("MLX LM package loaded successfully")
        except Exception as e:
            logger.warning(f"MLX LM not available: {type(e).__name__}: {e}")
            self._model_loaded = False

    def _ensure_model_loaded(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:  # Double-checked locking
                    global _llm_load_status, _llm_load_progress, _llm_load_error

                    start_time = time.time()
                    model_path = settings.llm_model
                    if not model_path.startswith("mlx-community/"):
                        model_path = f"mlx-community/{model_path}"

                    _llm_load_status = "downloading"
                    _llm_load_progress = f"Downloading {model_path}..."

                    try:
                        self._model, self._tokenizer = self._load(model_path)
                        self._model_path = model_path
                        load_time = time.time() - start_time
                        _llm_load_status = "ready"
                        _llm_load_progress = f"Loaded in {load_time:.2f}s"
                    except Exception as e:
                        _llm_load_status = "error"
                        _llm_load_error = str(e)
                        _llm_load_progress = f"Error: {e}"
                        logger.error(f"Failed to load LLM: {type(e).__name__}: {e}", exc_info=True)
                        raise

                    log_structured("src.domain.services.llm", "init",
                        model_path=model_path,
                        load_time_s=round(time.time() - start_time, 2),
                        status=_llm_load_status,
                    )

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ) -> AsyncGenerator[str, None]:
        if not self._model_loaded:
            async def mock_stream():
                words = ["This", " is", " a", " demo", " response", " since", " MLX", " is", " not", " available", "."]  # noqa: E501
                for word in words:
                    yield word
            async for token in mock_stream():
                yield token
            return

        await asyncio.to_thread(self._ensure_model_loaded)

        start_time = time.time()
        token_count = 0
        self._last_truncated = False

        try:
            from mlx_lm import stream_generate

            formatted_prompt = _apply_chat_template(self._tokenizer, prompt)

            if formatted_prompt != prompt:
                logger.debug("Applied chat template to prompt")

            prompt_hash = hashlib.sha256(formatted_prompt.encode()).hexdigest()[:12]
            logger.debug(f"Prompt: hash={prompt_hash} len={len(formatted_prompt)}")
            logger.debug(f"Starting generation (max_tokens={max_tokens})")

            def generate_tokens():
                from mlx_lm.sample_utils import make_repetition_penalty, make_sampler
                sampler = make_sampler(temp=temperature)

                logits_processors = []
                if settings.llm_repetition_penalty != 1.0:
                    logits_processors.append(
                        make_repetition_penalty(
                            penalty=settings.llm_repetition_penalty,
                            context_size=settings.llm_repetition_context_size,
                        )
                    )

                for response in stream_generate(
                    self._model,
                    self._tokenizer,
                    formatted_prompt,
                    max_tokens=max_tokens,
                    sampler=sampler,
                    logits_processors=logits_processors,
                ):
                    yield response.text

            try:
                async with asyncio.timeout(_GENERATE_LOCK_TIMEOUT):
                    async with self._generate_lock:
                        all_tokens = await asyncio.to_thread(lambda: list(generate_tokens()))
            except TimeoutError:
                logger.error(
                    "GPU generation lock timed out after %ss — possible stuck inference",
                    _GENERATE_LOCK_TIMEOUT,
                )
                raise LLMError("GPU inference queue timed out. Please try again.")

            output_buffer = ""
            for token in all_tokens:
                output_buffer += token
                token_count += 1
                self._generation_count += 1
                self._total_tokens_generated += 1
                yield token

                # Check for repetition every 5 tokens to avoid perf overhead
                if token_count % 5 == 0:
                    stop_at = _detect_repetition(output_buffer)
                    if stop_at is not None:
                        truncated = output_buffer[:stop_at]
                        logger.warning(f"Repetition detected at token {token_count}, truncating. "
                                      f"Buffer: {len(output_buffer)} chars → {len(truncated)} chars")  # noqa: E501
                        self._last_truncated = True
                        # We already yielded the full tokens; clean_response will handle truncation
                        break

            duration = time.time() - start_time
            logger.info(f"Generation completed: {token_count} tokens in {duration:.2f}s "
                       f"({'truncated' if self._last_truncated else 'normal'})")

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Generation failed after {duration:.2f}s: {type(e).__name__}: {e}")
            raise LLMError(f"Failed to generate response: {e!s}")

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ) -> str:
        if not self._model_loaded:
            return "This is a demo response since MLX is not available."

        start_time = time.time()
        try:
            await asyncio.to_thread(self._ensure_model_loaded)

            formatted_prompt = _apply_chat_template(self._tokenizer, prompt)

            if formatted_prompt != prompt:
                logger.debug("Applied chat template to prompt")

            prompt_hash = hashlib.sha256(formatted_prompt.encode()).hexdigest()[:12]
            logger.debug(f"Prompt: hash={prompt_hash} len={len(formatted_prompt)}")
            from mlx_lm import generate
            from mlx_lm.sample_utils import make_repetition_penalty, make_sampler

            sampler = make_sampler(temp=temperature)

            logits_processors = []
            if settings.llm_repetition_penalty != 1.0:
                logits_processors.append(
                    make_repetition_penalty(
                        penalty=settings.llm_repetition_penalty,
                        context_size=settings.llm_repetition_context_size,
                    )
                )

            try:
                async with asyncio.timeout(_GENERATE_LOCK_TIMEOUT):
                    async with self._generate_lock:
                        result = await asyncio.to_thread(
                            generate,
                            self._model,
                            self._tokenizer,
                            formatted_prompt,
                            max_tokens=max_tokens,
                            sampler=sampler,
                            logits_processors=logits_processors,
                        )
            except TimeoutError:
                logger.error(
                    "GPU generation lock timed out after %ss — possible stuck inference",
                    _GENERATE_LOCK_TIMEOUT,
                )
                raise LLMError("GPU inference queue timed out. Please try again.")
            duration = time.time() - start_time
            token_count = len(result.split())
            self._generation_count += 1
            self._total_tokens_generated += token_count
            logger.info(f"Sync generation: {token_count} tokens in {duration:.2f}s")
            return result
        except Exception as e:
            logger.error(f"Sync generation failed: {type(e).__name__}: {e}")
            raise LLMError(f"Failed to generate response: {e!s}")

    def get_model_name(self) -> str:
        return self._model_path or settings.llm_model

    def get_stats(self) -> dict:
        return {
            "model": self.get_model_name(),
            "loaded": self._model is not None,
            "generation_count": self._generation_count,
            "total_tokens": self._total_tokens_generated,
        }


async def get_llm() -> MLXLLM:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MLXLLM()
        logger.info("LLM instance created")
    return _llm_instance


def get_llm_stats() -> dict:
    return _llm_instance.get_stats() if _llm_instance else {}


def get_llm_load_status() -> dict:
    global _llm_load_status, _llm_load_progress, _llm_load_error

    status = "not_started"
    progress = ""
    error = None

    if _llm_instance:
        if _llm_instance._model is not None:
            status = "ready"
            progress = f"Model ready ({_llm_instance.get_model_name()})"
        elif _llm_instance._model_loaded:
            status = _llm_load_status
            progress = _llm_load_progress
            error = _llm_load_error
        else:
            status = "error"
            progress = "MLX not available"
            error = "MLX LM package not installed"

    return {
        "status": status,
        "progress": progress,
        "error": error,
    }


def reset_llm():
    global _llm_instance, _llm_load_status, _llm_load_progress, _llm_load_error
    logger.info("Resetting LLM instance")
    _llm_instance = None
    _llm_load_status = "idle"
    _llm_load_progress = ""
    _llm_load_error = None
