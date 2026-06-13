import time
import logging
from typing import Sequence

from .context import PipelineContext
from .stage import PipelineStage
from ..errors import SemanticChunkingError

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self, stages: Sequence[PipelineStage]):
        self.stages = list(stages)

    async def run(self, context: PipelineContext) -> PipelineContext:
        for stage in self.stages:
            stage_name = type(stage).__name__
            start = time.time()
            try:
                logger.info(f"Running pipeline stage: {stage_name}")
                context = await stage.process(context)
                elapsed = time.time() - start
                context.stats.setdefault("stage_timing", {})[stage_name] = round(elapsed, 3)
                logger.info(f"Stage {stage_name} completed in {elapsed:.3f}s")
            except SemanticChunkingError:
                raise
            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"Stage {stage_name} failed after {elapsed:.3f}s: {e}")
                raise SemanticChunkingError(
                    error=f"Pipeline stage {stage_name} failed: {str(e)}",
                    stage=stage_name,
                    exception=str(e),
                    context_snapshot={
                        "file_path": context.file_path,
                        "parser_type": context.parser_type,
                    },
                    traceback_summary=str(e),
                )
        return context
