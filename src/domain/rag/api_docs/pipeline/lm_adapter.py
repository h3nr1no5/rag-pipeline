"""DSPy LM adapter wrapping the local MLXLLM singleton.

Provides a `dspy.BaseLM` subclass that delegates text generation to
the existing MLXLLM instance, so DSPy modules (ChainOfThought, etc.)
can run inference on the local MLX backend without external API calls.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import dspy

from .....core.config import get_settings
from ....services.llm import MLXLLM, _llm_instance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal response helpers — produce an OpenAI-chat-compatible shape so that
# dspy.BaseLM._process_completion() can extract text correctly.
# ---------------------------------------------------------------------------


def _build_chat_completion(text: str, model_name: str) -> SimpleNamespace:
    """Build a minimal OpenAI chat-completion-like object.

    DSPy's ``_process_completion`` reads ``response.choices[i].message.content``,
    so we only need to provide the minimum structure required.
    """
    choice = SimpleNamespace(
        message=SimpleNamespace(content=text, reasoning_content=None),
        logprobs=None,
    )
    return SimpleNamespace(
        choices=[choice],
        model=model_name,
        usage={},
    )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_dspy_lm_instance: MLXDspyLM | None = None


def get_mlx_dspy_lm() -> MLXDspyLM:
    """Return the singleton ``MLXDspyLM`` instance (create on first call)."""
    global _dspy_lm_instance
    if _dspy_lm_instance is None:
        _dspy_lm_instance = MLXDspyLM()
        logger.info("MLXDspyLM singleton created")
    return _dspy_lm_instance


# ---------------------------------------------------------------------------
# LM adapter
# ---------------------------------------------------------------------------


class MLXDspyLM(dspy.BaseLM):
    """DSPy LM adapter that delegates generation to the local ``MLXLLM`` singleton.

    This adapter makes the local MLX model visible to DSPy as a standard LM,
    supporting ``dspy.configure(lm=mlx_dspy_lm)`` and subsequent use by
    ``dspy.Predict``, ``dspy.ChainOfThought``, etc.
    """

    def __init__(
        self,
        model_name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        repetition_penalty: float | None = None,
    ) -> None:
        settings = get_settings()

        # Resolve defaults from Settings
        model_name = model_name or settings.llm_model
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or settings.llm_max_tokens
        repetition_penalty = (
            repetition_penalty
            if repetition_penalty is not None
            else settings.llm_repetition_penalty
        )

        # Initialise the DSPy BaseLM layer
        super().__init__(
            model=model_name,
            model_type="text",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Store adapter-specific config (for introspection / debugging)
        self.repetition_penalty = repetition_penalty

        # Reuse the existing MLXLLM singleton if it has already been created,
        # otherwise create a fresh instance (the __init__ is lightweight and
        # only checks whether mlx-lm is importable — the actual model is loaded
        # lazily on first generate call).
        self._llm: MLXLLM = _llm_instance if _llm_instance is not None else MLXLLM()

        logger.debug(
            "MLXDspyLM initialised (model=%s, temperature=%s, max_tokens=%s)",
            model_name, temperature, max_tokens,
        )

    # -- Temperature property (per-call override support) ------------------

    @property
    def temperature(self) -> float:
        """Return the current generation temperature."""
        return self.kwargs.get("temperature", 0.1)

    @temperature.setter
    def temperature(self, value: float) -> None:
        """Override the generation temperature for subsequent calls."""
        if not 0.0 <= value <= 2.0:
            raise ValueError(f"temperature must be in [0.0, 2.0], got {value}")
        self.kwargs["temperature"] = value

    # -- DSPy interface ----------------------------------------------------

    def forward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        """Synchronous forward pass — delegates to ``MLXLLM.generate()``.

        Accepts either a raw string *prompt* or a list of *messages* in
        DSPy's chat format.  Messages are flattened by joining their
        ``content`` fields.
        """
        # 1. Resolve the prompt string ------------------------------------
        if prompt is not None:
            final_prompt: str = prompt
        elif messages is not None:
            parts: list[str] = []
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Some DSPy providers pass content as a list of parts
                    # (text, image, etc.).  Concatenate text parts only.
                    text_parts = [
                        p["text"]
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    parts.extend(text_parts)
                else:
                    parts.append(str(content))
            final_prompt = "\n".join(parts)
        else:
            raise ValueError("Either 'prompt' or 'messages' must be provided.")

        # 2. Merge generation parameters ----------------------------------
        temperature = kwargs.get("temperature", self.kwargs.get("temperature", 0.1))
        max_tokens = kwargs.get("max_tokens", self.kwargs.get("max_tokens", 600))

        # 3. Call MLXLLM.generate() via asyncio.run -----------------------
        # DSPy expects a synchronous forward(), but MLXLLM.generate() is
        # async, so we bridge with asyncio.run().
        try:
            response_text: str = asyncio.run(
                self._llm.generate(final_prompt, max_tokens=max_tokens, temperature=temperature)
            )
        except Exception:
            logger.exception("MLXLLM.generate() failed in DSPy forward()")
            raise

        # 4. Return in OpenAI-chat-completion format ----------------------
        return _build_chat_completion(response_text, self.model)

    # -- Deep-copy support -------------------------------------------------

    def __deepcopy__(self, memo: dict[int, Any]) -> MLXDspyLM:
        """Return ``self`` — the MLX model cannot be deep-copied.

        DSPy's compilation process (``MIPROv2.compile()``, etc.)
        deep-copies modules, which would try to deep-copy the LM.
        Returning ``self`` avoids attempting to serialise the
        underlying MLX model while still allowing compilation to
        proceed.
        """
        return self
