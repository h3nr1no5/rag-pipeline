from __future__ import annotations

from typing import Protocol

from .context import PipelineContext


class PipelineStage(Protocol):
    async def process(self, context: PipelineContext) -> PipelineContext:
        ...
