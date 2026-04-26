from datetime import datetime, timedelta, timezone
from typing import Any
import hashlib
import hmac

from jose import jwt, JWTError
from passlib.context import CryptContext

from .config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    settings = get_settings()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


def generate_cache_key(
    document_id: str,
    query_text: str,
    chunking_strategy_id: str,
    embedding_model: str,
) -> str:
    normalized_query = query_text.lower().strip()
    key_input = f"{document_id}|{normalized_query}|{chunking_strategy_id}|{embedding_model}"
    return hashlib.sha256(key_input.encode()).hexdigest()


def sanitize_filename(filename: str) -> str:
    import re
    filename = re.sub(r"[^\w\s.-]", "", filename)
    filename = re.sub(r"\s+", "_", filename)
    return filename[:200]
