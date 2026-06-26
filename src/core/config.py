import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

if os.environ.get("HF_HUB_OFFLINE", "0") == "1":
    os.environ["HF_HUB_OFFLINE"] = "1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    database_url: str = "sqlite+aiosqlite:///./data/db.sqlite"
    upload_dir: str = "./data/uploads"
    vectorstore_dir: str = "./data/vectorstore"
    models_dir: str = "./models"

    llm_model: str = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
    llm_max_tokens: int = 600
    llm_temperature: float = 0.1
    api_docs_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    llm_repetition_penalty: float = 1.2
    llm_repetition_context_size: int = Field(default=100, ge=1, le=200)

    # Cross-encoder re-ranker settings
    reranker_model: str = "Alibaba-NLP/gte-reranker-modernbert-base"  # lightweight cross-encoder optimized for relevance scoring
    reranker_enabled: bool = True

    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    embedding_batch_size: int = 32

    # API documentation RAG pipeline
    api_docs_enabled: bool = True

    # DSPy pipeline for API doc answer generation
    api_docs_dspy_enabled: bool = Field(
        default=True,
        description="Use DSPy pipeline for API doc answer generation. "
        "Set to false to fall back to prompt-based generation.",
    )

    default_chunk_size: int = 500
    default_chunk_overlap: int = 50

    max_upload_size_mb: int = 50
    cache_expiry_days: int = 3

    # Response verification settings
    verification_enabled: bool = True
    # Threshold for cross-encoder verification scores (cross-encoder range differs from cosine).
    # BGE reranker gives ~0-20 for relevant pairs; set low (0.0) to accept any positive signal.
    verification_similarity_threshold: float = 0.0
    verification_remove_unsupported: bool = True

    # Embedding normalization
    embedding_normalization_enabled: bool = True

    # Retrieval quality gating
    min_relevance_score: float = Field(default=0.15, ge=0.0, le=1.0)

    streamlit_server_port: int = 8501
    frontend_origin: str = "http://localhost:8501"
    api_base_url: str = "http://localhost:8000"

    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    debug_endpoints_enabled: bool = Field(default=False, description="Enable /api/v1/debug/* endpoints for runtime log level control (dev-only)")


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=".env")  # type: ignore[call-arg]
