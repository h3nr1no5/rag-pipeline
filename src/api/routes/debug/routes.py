"""Debug endpoints — runtime logging control (dev-only)."""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from ....core.logging import LogLevelManager
from ...dependencies import get_current_user

router = APIRouter(tags=["debug"])

VALID_LOG_LEVELS_NAMES = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
LEVEL_TO_NAME = {v: k for k, v in VALID_LOG_LEVELS_NAMES.items()}


class LoggingLevelsResponse(BaseModel):
    overrides: dict[str, str]  # module_name -> level_name


class LoggingUpdateRequest(BaseModel):
    overrides: dict[str, str | None]  # module_name -> level_name or null to clear

    @field_validator("overrides")
    @classmethod
    def validate_levels(cls, v):
        for mod, lvl in v.items():
            if lvl is not None and lvl.upper() not in VALID_LOG_LEVELS_NAMES:
                raise ValueError(f"Invalid log level '{lvl}' for module '{mod}'. Valid: {list(VALID_LOG_LEVELS_NAMES.keys())}")
            # Validate module name is a valid Python identifier-like string
            if not mod or not isinstance(mod, str):
                raise ValueError(f"Invalid module name: {mod}")
        return v


@router.get("/logging", response_model=LoggingLevelsResponse)
async def get_logging_levels(current_user=Depends(get_current_user)):
    """Return current log level overrides as module -> level_name mappings."""
    manager = LogLevelManager()
    overrides = manager.get_all_overrides()
    return LoggingLevelsResponse(
        overrides={k: LEVEL_TO_NAME.get(v, str(v)) for k, v in overrides.items()}
    )


@router.put("/logging", response_model=LoggingLevelsResponse)
async def set_logging_levels(
    body: LoggingUpdateRequest,
    current_user=Depends(get_current_user),
):
    """Set or clear log level overrides.
    
    Body: { "overrides": { "module.name": "DEBUG" | null } }
    Setting null clears the override for that module.
    """
    manager = LogLevelManager()
    for mod, lvl in body.overrides.items():
        if lvl is None:
            manager.set_level(mod, None)
        else:
            level_int = VALID_LOG_LEVELS_NAMES[lvl.upper()]
            manager.set_level(mod, level_int)
    overrides = manager.get_all_overrides()
    return LoggingLevelsResponse(
        overrides={k: LEVEL_TO_NAME.get(v, str(v)) for k, v in overrides.items()}
    )
