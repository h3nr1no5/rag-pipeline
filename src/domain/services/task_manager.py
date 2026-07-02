"""In-memory task manager for async background query execution.

Provides a singleton TaskManager that tracks background RAG query tasks
with status, per-backend progressive results, and periodic cleanup.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum


class TaskLimitError(Exception):
    """Raised when a task cannot be created due to quota or capacity limits."""


class TaskStatus(StrEnum):
    """Status of an async background task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BackendResult:
    """Result from a single RAG backend execution."""

    backend: str  # e.g. "cosine", "langchain", "llamaindex", "api_docs"
    answer: str  # The generated answer text
    sources: list  # List of SourceChunk-like dicts
    error: str | None = None
    cached: bool = False


@dataclass
class TaskRecord:
    """Record for a single background RAG query task."""

    task_id: str
    status: TaskStatus
    created_at: float
    user_id: str
    completed_at: float | None = None
    results: list[BackendResult] = field(default_factory=list)
    error: str | None = None
    progress: dict[str, str] = field(default_factory=dict)


class TaskManager:
    """In-memory task manager with async lock for thread-safe operations."""

    def __init__(
        self,
        max_tasks: int = 1000,
        max_tasks_per_user: int = 50,
    ) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()
        self._max_tasks = max_tasks
        self._max_tasks_per_user = max_tasks_per_user

    async def create_task(
        self, task_id: str, user_id: str
    ) -> TaskRecord:
        """Create a new task record and store it."""
        async with self._lock:
            if len(self._tasks) >= self._max_tasks:
                raise TaskLimitError(
                    f"Task limit reached: {self._max_tasks} tasks maximum"
                )
            user_task_count = sum(
                1 for t in self._tasks.values() if t.user_id == user_id
            )
            if user_task_count >= self._max_tasks_per_user:
                raise TaskLimitError(
                    f"Per-user task limit reached: {self._max_tasks_per_user} tasks maximum"
                )
            record = TaskRecord(
                task_id=task_id,
                status=TaskStatus.PENDING,
                created_at=time.time(),
                user_id=user_id,
            )
            self._tasks[task_id] = record
            return record

    async def get_task(self, task_id: str) -> TaskRecord | None:
        """Retrieve a task record by ID, or None if not found."""
        return self._tasks.get(task_id)

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        """Update the status of a task and optionally set an error message."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = status
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    self._tasks[task_id].completed_at = time.time()
                if error:
                    self._tasks[task_id].error = error

    async def append_result(self, task_id: str, result: BackendResult) -> None:
        """Append a per-backend result to the task's results list."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].results.append(result)

    async def update_progress(
        self, task_id: str, backend: str, message: str
    ) -> None:
        """Update the progress message for a specific backend."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].progress[backend] = message

    async def cleanup(self) -> None:
        """Remove tasks older than 1 hour."""
        async with self._lock:
            now = time.time()
            self._tasks = {
                k: v
                for k, v in self._tasks.items()
                if now - v.created_at < 3600  # 1 hour
            }

    def get_task_count(self) -> int:
        """Return the number of tracked tasks."""
        return len(self._tasks)


# Module-level singleton
task_manager = TaskManager()
