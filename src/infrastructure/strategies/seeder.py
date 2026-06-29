import logging

import yaml
from sqlalchemy import select

logger = logging.getLogger(__name__)


def load_strategies_from_yaml(path: str) -> dict | None:
    """Open and parse a YAML file at *path*.

    Validates the top-level ``strategies`` key exists and is a list.
    Returns the parsed dict on success, or ``None`` on any error
    (file not found, invalid YAML, missing key).
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("Strategies YAML file not found: %s", path)
        return None
    except yaml.YAMLError as e:
        logger.error("Invalid YAML in %s: %s", path, e)
        return None
    except Exception as e:
        logger.error("Error reading YAML file %s: %s", path, e)
        return None

    if not isinstance(data, dict) or "strategies" not in data:
        logger.error("YAML file %s is missing the required 'strategies' key", path)
        return None

    if not isinstance(data["strategies"], list):
        logger.error("YAML key 'strategies' must be a list in %s", path)
        return None

    return data


async def seed_strategies_from_yaml(db_session, yaml_path: str, settings) -> int:
    """Read system strategies from *yaml_path* and upsert them into the database.

    For each strategy entry in the YAML list:

    * If a system strategy with the same **name** already exists → update all
      fields to match the YAML values.
    * Otherwise, if a system strategy with the same **id** (engine_type)
      exists → update it (backward-compatible lookup).
    * Otherwise → create a new ``ChunkingStrategy`` row.

    Strategies whose ``is_system`` is explicitly ``false`` are skipped.

    Returns the number of upserted strategies (0 when the YAML file is
    unavailable or contains no valid system entries).
    """
    from ..database.models import ChunkingStrategy

    data = load_strategies_from_yaml(yaml_path)
    if data is None:
        return 0

    strategies = data["strategies"]
    count = 0

    for entry in strategies:
        strategy_id = entry.get("engine_type", "")
        if not strategy_id:
            logger.warning(
                "YAML strategy entry missing engine_type, skipping: %s",
                entry.get("name", "unknown"),
            )
            continue

        name = entry.get("name", strategy_id)
        chunk_size = entry.get("chunk_size", 0)
        chunk_overlap = entry.get("chunk_overlap", 0)
        separators = entry.get("separators", [])
        use_hyperlinks = entry.get("use_hyperlinks", False)
        config = entry.get("config")  # None if absent — fine for JSON column
        is_system = entry.get("is_system", True)  # default True for YAML seeding

        if is_system is False:
            logger.info(
                "Skipping non-system strategy '%s' in YAML seeding", name
            )
            continue

        # Lookup strategy by name (matching is_system=True)
        result = await db_session.execute(
            select(ChunkingStrategy).where(
                ChunkingStrategy.name == name,
                ChunkingStrategy.is_system,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            # Fallback: lookup by id (engine_type) for backward compatibility
            result_by_id = await db_session.execute(
                select(ChunkingStrategy).where(
                    ChunkingStrategy.id == strategy_id,
                    ChunkingStrategy.is_system,
                )
            )
            existing = result_by_id.scalar_one_or_none()

        if existing is not None:
            # Update existing strategy with YAML values
            existing.id = strategy_id
            existing.name = name
            existing.chunk_size = chunk_size
            existing.chunk_overlap = chunk_overlap
            existing.separators = separators
            existing.engine_type = entry.get("engine_type", existing.engine_type)
            existing.use_hyperlinks = use_hyperlinks
            existing.config = config
            existing.embedding_model = settings.embedding_model
            logger.info(
                "Updated system strategy '%s' (id=%s) from YAML", name, strategy_id
            )
        else:
            # Create new strategy
            new_strategy = ChunkingStrategy(
                id=strategy_id,
                name=name,
                description=entry.get("description", f"{name} chunking strategy"),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
                embedding_model=settings.embedding_model,
                engine_type=entry.get("engine_type", strategy_id),
                use_hyperlinks=use_hyperlinks,
                is_system=True,
                config=config,
            )
            db_session.add(new_strategy)
            logger.info(
                "Created system strategy '%s' (id=%s) from YAML", name, strategy_id
            )

        count += 1

    await db_session.commit()
    logger.info("Seeded %d strategies from %s", count, yaml_path)
    return count
