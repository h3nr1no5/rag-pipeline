import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


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
    llm_temperature: float = 0.5
    llm_repetition_penalty: float = 1.15
    llm_repetition_context_size: int = Field(default=20, ge=1, le=100)

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_batch_size: int = 32

    default_chunk_size: int = 500
    default_chunk_overlap: int = 50

    cache_expiry_days: int = 3

    streamlit_server_port: int = 8501
    frontend_origin: str = "http://localhost:8501"
    api_base_url: str = "http://localhost:8000"

    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")


@lru_cache
def get_settings() -> Settings:
    return Settings()
