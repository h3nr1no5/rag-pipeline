import time
import asyncio
import logging
import threading
from typing import AsyncGenerator
from ...domain.ports.llm import LLM
from ...core.config import get_settings
from ...core.exceptions import LLMError

settings = get_settings()
logger = logging.getLogger(__name__)

_llm_instance = None
_llm_load_time = None
_llm_load_status = "idle"
_llm_load_progress = ""
_llm_load_error = None


class MLXLLM(LLM):
    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._model_loaded = False
        self._model_path = None
        self._generation_count = 0
        self._total_tokens_generated = 0
        try:
            from mlx_lm import load
            self._load = load
            self._model_loaded = True
            logger.info("MLX LM package loaded successfully")
        except Exception as e:
            logger.warning(f"MLX LM not available: {type(e).__name__}: {e}")
            self._model_loaded = False

    def _ensure_model_loaded(self):
        global _llm_load_status, _llm_load_progress, _llm_load_error
        
        if self._model is None:
            start_time = time.time()
            model_path = settings.llm_model
            if not model_path.startswith("mlx-community/"):
                model_path = f"mlx-community/{model_path}"
            
            _llm_load_status = "downloading"
            _llm_load_progress = f"Downloading {model_path}..."
            logger.info(f"Loading LLM: {model_path}")
            
            try:
                self._model, self._tokenizer = self._load(model_path)
                self._model_path = model_path
                load_time = time.time() - start_time
                _llm_load_status = "ready"
                _llm_load_progress = f"Loaded in {load_time:.2f}s"
                logger.info(f"LLM loaded in {load_time:.2f}s")
            except Exception as e:
                _llm_load_status = "error"
                _llm_load_error = str(e)
                _llm_load_progress = f"Error: {e}"
                logger.error(f"Failed to load LLM: {type(e).__name__}: {e}", exc_info=True)
                raise

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.5,
    ) -> AsyncGenerator[str, None]:
        if not self._model_loaded:
            async def mock_stream():
                words = ["This", " is", " a", " demo", " response", " since", " MLX", " is", " not", " available", "."]
                for word in words:
                    yield word
            async for token in mock_stream():
                yield token
            return
        
        self._ensure_model_loaded()
        
        start_time = time.time()
        token_count = 0
        
        try:
            from mlx_lm import stream_generate
            
            logger.debug(f"Starting generation (max_tokens={max_tokens})")
            
            def generate_tokens():
                for response in stream_generate(
                    self._model,
                    self._tokenizer,
                    prompt,
                    max_tokens=max_tokens,
                ):
                    yield response.text
            
            for token in await asyncio.to_thread(lambda: list(generate_tokens())):
                token_count += 1
                self._generation_count += 1
                self._total_tokens_generated += 1
                yield token
            
            duration = time.time() - start_time
            logger.info(f"Generation completed: {token_count} tokens in {duration:.2f}s ({token_count/max(max(duration, 0.01), 1):.1f} tokens/sec)")
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Generation failed after {duration:.2f}s: {type(e).__name__}: {e}")
            raise LLMError(f"Failed to generate response: {str(e)}")

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.5,
    ) -> str:
        if not self._model_loaded or self._model is None:
            return "This is a demo response since MLX is not available."
        
        start_time = time.time()
        try:
            self._ensure_model_loaded()
            from mlx_lm import generate
            result = await asyncio.to_thread(
                generate,
                self._model,
                self._tokenizer,
                prompt,
                max_tokens=max_tokens,
            )
            duration = time.time() - start_time
            token_count = len(result.split())
            self._generation_count += 1
            self._total_tokens_generated += token_count
            logger.info(f"Sync generation: {token_count} tokens in {duration:.2f}s")
            return result
        except Exception as e:
            logger.error(f"Sync generation failed: {type(e).__name__}: {e}")
            raise LLMError(f"Failed to generate response: {str(e)}")

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
        start_time = time.time()
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
