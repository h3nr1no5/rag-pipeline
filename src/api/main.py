import os

import time
import logging
import warnings
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.config import get_settings
settings = get_settings()

# Validate log level against whitelist for security
VALID_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

log_level_name = settings.log_level.upper()
if log_level_name not in VALID_LOG_LEVELS:
    warnings.warn(f"Invalid LOG_LEVEL '{settings.log_level}', valid values are: {list(VALID_LOG_LEVELS.keys())}. Falling back to INFO.")
    log_level = logging.INFO
else:
    log_level = VALID_LOG_LEVELS[log_level_name]

logging.basicConfig(level=log_level)

from .routes import auth_router, documents_router, query_router, cache_router, health_router
from ..infrastructure.database import init_db
from ..domain.services.embedding import reset_embedder
logger = logging.getLogger(__name__)
logger.info(f"HF_HUB_OFFLINE = {os.environ.get('HF_HUB_OFFLINE', 'NOT SET')}")


class MonitoringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = f"{int(start_time * 1000)}"
        
        logger.info(
            f"Request started | ID: {request_id} | "
            f"Method: {request.method} | Path: {request.url.path}"
        )
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            logger.info(
                f"Request completed | ID: {request_id} | "
                f"Status: {response.status_code} | "
                f"Duration: {process_time:.3f}s"
            )
            
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.3f}"
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Request failed | ID: {request_id} | "
                f"Error: {type(e).__name__}: {str(e)} | "
                f"Duration: {process_time:.3f}s"
            )
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    from ..domain.services.warmup import warmup_models

    logger.info("Starting RAG Pipeline API...")
    logger.info(f"LLM Model: {settings.llm_model}")
    logger.info(f"Embedding Model: {settings.embedding_model}")
    
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.vectorstore_dir, exist_ok=True)
    
    try:
        from src.infrastructure.database.session import ensure_db
        await ensure_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        await init_db()

    from ..infrastructure.database import async_session_maker
    from sqlalchemy import select, text as sa_text
    from ..infrastructure.database.models import ChunkingStrategy, Document

    # Phase 1: Schema migration — add use_hyperlinks column if missing (runs unconditionally)
    async with async_session_maker() as schema_session:
        try:
            result = await schema_session.execute(
                sa_text("PRAGMA table_info(chunking_strategies)")
            )
            columns = {row[1] for row in result.fetchall()}
            if "use_hyperlinks" not in columns:
                logger.info("Migrating chunking_strategies: adding use_hyperlinks column")
                await schema_session.execute(
                    sa_text("ALTER TABLE chunking_strategies ADD COLUMN use_hyperlinks BOOLEAN DEFAULT 0")
                )
                await schema_session.commit()
                logger.info("Schema migration: added use_hyperlinks column")
            if "is_api_aware" in columns:
                logger.info("Migrating chunking_strategies: dropping old is_api_aware column")
                await schema_session.execute(
                    sa_text("ALTER TABLE chunking_strategies DROP COLUMN is_api_aware")
                )
                await schema_session.commit()
                logger.info("Schema migration: dropped is_api_aware column")
        except Exception as e:
            logger.error(f"Schema migration failed: {e}", exc_info=True)

    async with async_session_maker() as session:
        result = await session.execute(select(ChunkingStrategy).where(ChunkingStrategy.id == "default"))
        if not result.scalar_one_or_none():
            default_strategy = ChunkingStrategy(
                id="default",
                name="Default",
                description="Standard recursive chunking for general documents",
                chunk_size=settings.default_chunk_size,
                chunk_overlap=settings.default_chunk_overlap,
                separators=["\n\n", "\n", ". "],
                embedding_model=settings.embedding_model,
                is_system=True,
            )
            session.add(default_strategy)

            semantic_strategy = ChunkingStrategy(
                id="semantic",
                name="Semantic Chunking",
                description="Semantic chunking for structured content with optional hyperlink support",
                chunk_size=300,
                chunk_overlap=30,
                separators=["\n## ", "\n### ", "\n", "## ", "### "],
                embedding_model=settings.embedding_model,
                engine_type="semantic",
                use_hyperlinks=False,
                is_system=True,
            )
            session.add(semantic_strategy)

            await session.commit()
            logger.info("Default chunking strategies created")
        else:
            # Only need semantic if default already exists (existing DB)
            semantic_result = await session.execute(
                select(ChunkingStrategy).where(ChunkingStrategy.id == "semantic")
            )
            if not semantic_result.scalar_one_or_none():
                semantic_strategy = ChunkingStrategy(
                    id="semantic",
                    name="Semantic Chunking",
                    description="Semantic chunking for structured content with optional hyperlink support",
                    chunk_size=300,
                    chunk_overlap=30,
                    separators=["\n## ", "\n### ", "\n", "## ", "### "],
                    embedding_model=settings.embedding_model,
                    engine_type="semantic",
                    use_hyperlinks=False,
                    is_system=True,
                )
                session.add(semantic_strategy)
                await session.commit()
                logger.info("Semantic chunking strategy created (existing DB)")

            # Migrate documents from old "api-docs" strategy to new "semantic" strategy
            try:
                from sqlalchemy import update
                old_result = await session.execute(
                    select(ChunkingStrategy).where(ChunkingStrategy.id == "api-docs")
                )
                old_strategy = old_result.scalar_one_or_none()
                if old_strategy:
                    await session.execute(
                        update(Document)
                        .where(Document.chunking_strategy_id == "api-docs")
                        .values(chunking_strategy_id="semantic")
                    )
                    from ..infrastructure.database.models import QueryCache
                    await session.execute(
                        update(QueryCache)
                        .where(QueryCache.chunking_strategy_id == "api-docs")
                        .values(chunking_strategy_id="semantic")
                    )
                    await session.delete(old_strategy)
                    await session.commit()
                    logger.info("Migrated documents from 'api-docs' to 'semantic' strategy")
            except Exception as e:
                logger.error(f"Strategy migration skipped (non-fatal): {e}", exc_info=True)
                await session.rollback()
    
    # Launch async model warmup (non-blocking, models load in background)
    asyncio.create_task(warmup_models())
    logger.info("Model warmup task launched")

    yield
    logger.info("Shutting down RAG Pipeline API...")
    reset_embedder()


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Pipeline API",
        description="RAG pipeline with local LLM, MLX acceleration, and query caching",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    app.add_middleware(MonitoringMiddleware)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {type(exc).__name__}: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred. Please try again later."},
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(query_router, prefix="/api/v1")
    app.include_router(cache_router, prefix="/api/v1")
    
    return app


app = create_app()
