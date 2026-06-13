import os


class SemanticChunkingError(Exception):
    def __init__(
        self,
        error: str,
        stage: str = "unknown",
        page: int | None = None,
        exception: str = "",
        context_snapshot: dict | None = None,
        traceback_summary: str = "",
    ):
        self.error = error
        self.stage = stage
        self.page = page
        self.exception = exception
        self.context_snapshot = context_snapshot or {}
        self.traceback_summary = traceback_summary
        super().__init__(self.error)

    def to_dict(self) -> dict:
        def _sanitize_value(v: object) -> object:
            if isinstance(v, str) and ("/" in v or "\\" in v):
                return os.path.basename(v)
            return v

        snapshot = {k: _sanitize_value(v) for k, v in self.context_snapshot.items()}

        return {
            "error": self.error,
            "stage": self.stage,
            "page": self.page,
            "exception": str(self.exception)[:200],
            "context_snapshot": snapshot,
        }
