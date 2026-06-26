import asyncio
import logging
import os
import time
import warnings
from contextlib import asynccontextmanager

# DSPy 3.2.1 emits a DeprecationWarning from its own Actor signature
# (dspy/predict/avatar/signatures.py) which uses the deprecated `prefix`
# argument.  The warning fires on every import and is a DSPy bug, not ours.
warnings.filterwarnings(
    "ignore",
    message="The 'prefix' argument in InputField/OutputField is deprecated",
    category=DeprecationWarning,
)

from fastapi import FastAPI, HTTPException, Request, status
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

from ..core.logging import DevModeFilter, ModuleLevelFilter

logging.getLogger().addFilter(DevModeFilter())
logging.getLogger().addFilter(ModuleLevelFilter())

from ..domain.services.embedding import reset_embedder
from ..infrastructure.database import init_db
from .routes import (
    auth_router,
    cache_router,
    debug_router,
    documents_router,
    health_router,
    query_router,
)

logger = logging.getLogger(__name__)
logger.info(f"HF_HUB_OFFLINE = {os.environ.get('HF_HUB_OFFLINE', 'NOT SET')}")


class MonitoringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = f"{int(start_time * 1000)}"

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            logger.debug(
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
                f"Error: {type(e).__name__}: {e!s} | "
                f"Duration: {process_time:.3f}s"
            )
            raise


_warmup_task: asyncio.Task | None = None


async def _load_models():
    """Load models in background — sets module-level singletons directly."""
    try:
        from ..domain.services.retrieval_langchain import CrossEncoderReRanker
        reranker = CrossEncoderReRanker()
        await asyncio.wait_for(reranker._ensure_model(), timeout=120)
        logger.info("Cross-encoder loaded")
    except Exception as e:
        logger.error(f"Cross-encoder failed: {e}")

    try:
        from ..domain.services.llm import get_llm
        llm = await get_llm()
        await asyncio.wait_for(
            asyncio.to_thread(llm._ensure_model_loaded),
            timeout=120,
        )
        logger.info("LLM loaded")
    except Exception as e:
        logger.error(f"LLM failed: {e}")

    try:
        import src.domain.services.embedding as emb_mod
        embedder = emb_mod.SentenceTransformerEmbedder()
        emb_mod._embedder_instance = embedder
        logger.info("Embedder loaded")
    except Exception as e:
        logger.error(f"Embedder failed: {e}")

    try:
        if settings.api_docs_enabled:
            import dspy

            from ..domain.rag.api_docs.pipeline.lm_adapter import get_mlx_dspy_lm
            dspy.configure(lm=get_mlx_dspy_lm())
            logger.info("DSPy LM configured")
    except Exception as e:
        logger.error(f"DSPy LM failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _warmup_task

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

    from sqlalchemy import select
    from sqlalchemy import text as sa_text

    from ..infrastructure.database import async_session_maker
    from ..infrastructure.database.models import ChunkingStrategy, Document

    # Phase 1: Schema migration — add/remove columns as needed (runs unconditionally)
    async with async_session_maker() as schema_session:
        try:
            # --- chunking_strategies table ---
            cs_result = await schema_session.execute(
                sa_text("PRAGMA table_info(chunking_strategies)")
            )
            cs_columns = {row[1] for row in cs_result.fetchall()}
            if "use_hyperlinks" not in cs_columns:
                logger.info("Migrating chunking_strategies: adding use_hyperlinks column")
                await schema_session.execute(
                    sa_text("ALTER TABLE chunking_strategies ADD COLUMN use_hyperlinks BOOLEAN DEFAULT 0")
                )
                await schema_session.commit()
                logger.info("Schema migration: added use_hyperlinks column")
            if "is_api_aware" in cs_columns:
                logger.info("Migrating chunking_strategies: dropping old is_api_aware column")
                await schema_session.execute(
                    sa_text("ALTER TABLE chunking_strategies DROP COLUMN is_api_aware")
                )
                await schema_session.commit()
                logger.info("Schema migration: dropped is_api_aware column")
            if "config" not in cs_columns:
                logger.info("Migrating chunking_strategies: adding config column")
                await schema_session.execute(
                    sa_text("ALTER TABLE chunking_strategies ADD COLUMN config JSON DEFAULT NULL")
                )
                await schema_session.commit()
                logger.info("Schema migration: added config column for strategy configuration")

            # --- documents table ---
            doc_result = await schema_session.execute(
                sa_text("PRAGMA table_info(documents)")
            )
            doc_columns = {row[1] for row in doc_result.fetchall()}
            if "is_api_doc" in doc_columns:
                logger.info("Migrating documents: dropping legacy is_api_doc column")
                await schema_session.execute(
                    sa_text("ALTER TABLE documents DROP COLUMN is_api_doc")
                )
                await schema_session.commit()
                logger.info("Schema migration: dropped is_api_doc column from documents")
        except Exception as e:
            logger.error(f"Schema migration failed: {e}", exc_info=True)

    async with async_session_maker() as session:
        # Try YAML-based seeding first
        yaml_seeded = False
        try:
            from src.infrastructure.strategies.seeder import seed_strategies_from_yaml

            seeded = await seed_strategies_from_yaml(
                session, "config/strategies.yaml", settings
            )
            if seeded > 0:
                logger.info(
                    "Seeded %d system strategies from config/strategies.yaml",
                    seeded,
                )
                yaml_seeded = True
            else:
                logger.warning("YAML seeding returned 0 strategies — file may be empty")
        except Exception as e:
            logger.warning("YAML seeding failed: %s", e)

        if not yaml_seeded:
            logger.warning(
                "YAML seeding unavailable, falling back to hardcoded seeding"
            )
            # === BEGIN hardcoded fallback (original lines 200-348) ===
            result = await session.execute(
                select(ChunkingStrategy).where(ChunkingStrategy.id == "recursive")
            )
            if not result.scalar_one_or_none():
                recursive_strategy = ChunkingStrategy(
                    id="recursive",
                    name="Recursive",
                    description="Recursive chunking for general documents",
                    chunk_size=settings.default_chunk_size,
                    chunk_overlap=settings.default_chunk_overlap,
                    separators=["\n\n", "\n", ". "],
                    embedding_model=settings.embedding_model,
                    is_system=True,
                )
                session.add(recursive_strategy)

                # Check if semantic already exists before creating (handles existing DBs)
                semantic_result = await session.execute(
                    select(ChunkingStrategy).where(ChunkingStrategy.id == "semantic")
                )
                if not semantic_result.scalar_one_or_none():
                    semantic_strategy = ChunkingStrategy(
                        id="semantic",
                        name="Semantic",
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
                # Only need semantic if recursive already exists (existing DB)
                semantic_result = await session.execute(
                    select(ChunkingStrategy).where(ChunkingStrategy.id == "semantic")
                )
                if not semantic_result.scalar_one_or_none():
                    semantic_strategy = ChunkingStrategy(
                        id="semantic",
                        name="Semantic",
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

                # Migrate documents from old "default" strategy to new "recursive" strategy
            try:
                from sqlalchemy import update

                default_result = await session.execute(
                    select(ChunkingStrategy).where(ChunkingStrategy.id == "default")
                )
                old_default = default_result.scalar_one_or_none()
                if old_default:
                    await session.execute(
                        update(Document)
                        .where(Document.chunking_strategy_id == "default")
                        .values(chunking_strategy_id="recursive")
                    )
                    from ..infrastructure.database.models import QueryCache

                    await session.execute(
                        update(QueryCache)
                        .where(QueryCache.chunking_strategy_id == "default")
                        .values(chunking_strategy_id="recursive")
                    )
                    # Check if "recursive" row exists and "default" still exists, then remove old default
                    recursive_exists = await session.execute(
                        select(ChunkingStrategy).where(ChunkingStrategy.id == "recursive")
                    )
                    if recursive_exists.scalar_one_or_none():
                        await session.delete(old_default)
                    await session.commit()
                    logger.info(
                        "Migrated documents from 'default' to 'recursive' strategy"
                    )
            except Exception as e:
                logger.error(
                    f"Strategy migration from 'default' to 'recursive' skipped (non-fatal): {e}",
                    exc_info=True,
                )
                await session.rollback()

            # Also check for system strategies named "Default" as a defensive fallback
            # (may exist in old DBs with different IDs)
            try:
                from sqlalchemy import update

                default_by_name = await session.execute(
                    select(ChunkingStrategy).where(
                        ChunkingStrategy.name == "Default",
                        ChunkingStrategy.id != "recursive",
                        ChunkingStrategy.is_system == True,
                    )
                )
                old_default_by_name = default_by_name.scalar_one_or_none()
                if old_default_by_name:
                    await session.execute(
                        update(Document)
                        .where(Document.chunking_strategy_id == old_default_by_name.id)
                        .values(chunking_strategy_id="recursive")
                    )
                    from ..infrastructure.database.models import QueryCache

                    await session.execute(
                        update(QueryCache)
                        .where(QueryCache.chunking_strategy_id == old_default_by_name.id)
                        .values(chunking_strategy_id="recursive")
                    )
                    recursive_exists = await session.execute(
                        select(ChunkingStrategy).where(ChunkingStrategy.id == "recursive")
                    )
                    if recursive_exists.scalar_one_or_none():
                        await session.delete(old_default_by_name)
                    await session.commit()
                    logger.info(
                        "Migrated documents from 'Default' (name) strategy to 'recursive'"
                    )
            except Exception as e:
                logger.error(
                    f"Strategy name-based migration from 'Default' to 'recursive' skipped (non-fatal): {e}",
                    exc_info=True,
                )
                await session.rollback()

        # Seed api-docs strategy (fallback only — YAML seeding covers it)
        if not yaml_seeded:
            try:
                async with async_session_maker() as seed_session:
                    api_docs_result = await seed_session.execute(
                        select(ChunkingStrategy).where(ChunkingStrategy.id == "api-docs")
                    )
                    if not api_docs_result.scalar_one_or_none():
                        api_docs_strategy = ChunkingStrategy(
                            id="api-docs",
                            name="API Documentation",
                            description="Structure-aware chunking for API documentation (DOCX/PDF)",
                            chunk_size=0,
                            chunk_overlap=0,
                            separators=[],
                            embedding_model=settings.embedding_model,
                            engine_type="api-docs",
                            use_hyperlinks=False,
                            is_system=True,
                        )
                        seed_session.add(api_docs_strategy)
                        await seed_session.commit()
                        logger.info("API Documentation chunking strategy created")
            except Exception as e:
                logger.error("Failed to seed api-docs strategy (non-fatal): %s", e)
            # === END hardcoded fallback ===

    # Launch async model warmup (non-blocking, models load in background)
    _warmup_task = asyncio.create_task(_load_models())
    logger.info("Model warmup task launched")


    # Wire load_all_from_db() into application startup
    if settings.api_docs_enabled:
        try:
            from src.domain.rag.api_docs.manager import get_manager
            from src.infrastructure.database import async_session_maker

            manager = get_manager()
            async with async_session_maker() as session:
                await manager.load_all_from_db(session)
                logger.info("API doc indexes restored from database on startup")
        except Exception:
            logger.warning(
                "Failed to load API doc indexes from DB on startup "
                "(non-fatal — fallback to on-the-fly ingestion)",
                exc_info=True,
            )

    yield

    # Shutdown: cancel warmup task if still running
    if _warmup_task is not None and not _warmup_task.done():
        _warmup_task.cancel()
        try:
            await asyncio.wait_for(_warmup_task, timeout=5)
        except (asyncio.CancelledError, TimeoutError):
            pass

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
        logger.error(f"Unhandled exception: {type(exc).__name__}: {exc!s}", exc_info=True)
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
    if settings.debug_endpoints_enabled:
        app.include_router(debug_router, prefix="/api/v1/debug")

    # Wire up API documentation RAG pipeline (Task 8.x)
    if settings.api_docs_enabled:
        from src.domain.rag.api_docs import api_docs_router
        app.include_router(api_docs_router, prefix="/api/v1")
        logger.info("API documentation RAG routes registered at /api/v1/query/api-docs")

    return app


app = create_app()
