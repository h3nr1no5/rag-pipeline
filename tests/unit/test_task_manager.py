"""Unit tests for TaskManager in-memory task tracking service."""

from unittest.mock import patch

import pytest

from src.domain.services.task_manager import (
    BackendResult,
    TaskLimitError,
    TaskManager,
    TaskStatus,
)


class TestTaskManagerCreate:
    """Tests for TaskManager.create_task()."""

    async def test_create_task_initial_state(self):
        """A newly created task should have PENDING status, created_at and user_id set."""
        tm = TaskManager()
        task = await tm.create_task("task-1", "user-1")

        assert task.task_id == "task-1"
        assert task.status == TaskStatus.PENDING
        assert task.user_id == "user-1"
        assert task.created_at > 0
        assert task.completed_at is None
        assert task.results == []
        assert task.error is None
        assert task.progress == {}

    async def test_create_task_raises_when_max_tasks_reached(self):
        """Creating more than max_tasks tasks should raise TaskLimitError."""
        tm = TaskManager(max_tasks=3, max_tasks_per_user=50)
        for i in range(3):
            await tm.create_task(f"task-{i}", f"user-{i}")

        with pytest.raises(TaskLimitError, match="Task limit reached"):
            await tm.create_task("task-overflow", "another-user")

    async def test_create_task_raises_when_max_tasks_per_user_reached(self):
        """Creating more than max_tasks_per_user tasks for one user should raise."""
        tm = TaskManager(max_tasks=1000, max_tasks_per_user=3)
        for i in range(3):
            await tm.create_task(f"task-{i}", "user-1")

        with pytest.raises(TaskLimitError, match="Per-user task limit reached"):
            await tm.create_task("task-overflow", "user-1")

    async def test_create_task_does_not_affect_other_users(self):
        """Tasks for one user should not count against another user's limit."""
        tm = TaskManager(max_tasks=1000, max_tasks_per_user=3)
        for i in range(3):
            await tm.create_task(f"task-{i}", "user-1")

        # Another user should still be able to create tasks
        task = await tm.create_task("task-other", "user-2")
        assert task.task_id == "task-other"


class TestTaskManagerGetTask:
    """Tests for TaskManager.get_task()."""

    async def test_get_task_returns_none_for_unknown(self):
        """Getting a non-existent task should return None."""
        tm = TaskManager()
        assert await tm.get_task("nonexistent") is None

    async def test_get_task_returns_correct_record(self):
        """Getting an existing task should return the correct record."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        task = await tm.get_task("task-1")

        assert task is not None
        assert task.task_id == "task-1"
        assert task.user_id == "user-1"

    async def test_get_task_returns_none_after_cleanup(self):
        """After cleanup removes a task, get_task should return None."""
        tm = TaskManager()
        with patch("time.time", return_value=1000.0):
            task = await tm.create_task("old-task", "user-1")

        # Manually set created_at to 2 hours ago
        task.created_at = 1000.0 - 7200

        with patch("time.time", return_value=1000.0):
            await tm.cleanup()

        assert await tm.get_task("old-task") is None


class TestTaskManagerUpdateStatus:
    """Tests for TaskManager.update_status()."""

    async def test_update_status_sets_status(self):
        """Updating a task's status should change its status field."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        await tm.update_status("task-1", TaskStatus.RUNNING)

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.status == TaskStatus.RUNNING

    async def test_update_status_sets_completed_at_for_completed(self):
        """Setting status to COMPLETED should set completed_at."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        with patch("time.time", return_value=5000.0):
            await tm.update_status("task-1", TaskStatus.COMPLETED)

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.completed_at == 5000.0

    async def test_update_status_sets_completed_at_for_failed(self):
        """Setting status to FAILED should set completed_at."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        with patch("time.time", return_value=6000.0):
            await tm.update_status("task-1", TaskStatus.FAILED)

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.completed_at == 6000.0

    async def test_update_status_does_not_set_completed_at_for_running(self):
        """Setting status to RUNNING should NOT set completed_at."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        with patch("time.time", return_value=5000.0):
            await tm.update_status("task-1", TaskStatus.RUNNING)

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.completed_at is None

    async def test_update_status_sets_error_message(self):
        """update_status should set the error message when provided."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        await tm.update_status("task-1", TaskStatus.FAILED, error="Something went wrong")

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.error == "Something went wrong"

    async def test_update_status_noop_for_unknown_task(self):
        """Updating status for a non-existent task should be a silent no-op."""
        tm = TaskManager()
        # Should not raise
        await tm.update_status("nonexistent", TaskStatus.COMPLETED)

    async def test_update_status_preserves_completed_at_on_second_update(self):
        """completed_at should not change when updating status after already completed."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        with patch("time.time", return_value=5000.0):
            await tm.update_status("task-1", TaskStatus.COMPLETED)

        with patch("time.time", return_value=6000.0):
            await tm.update_status("task-1", TaskStatus.RUNNING)

        task = await tm.get_task("task-1")
        assert task is not None
        # completed_at was set on first transition to COMPLETED
        assert task.completed_at == 5000.0


class TestTaskManagerAppendResult:
    """Tests for TaskManager.append_result()."""

    async def test_append_result_adds_to_results_list(self):
        """Appending a BackendResult should add it to the task's results list."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        result = BackendResult(backend="cosine", answer="test answer", sources=[])
        await tm.append_result("task-1", result)

        task = await tm.get_task("task-1")
        assert task is not None
        assert len(task.results) == 1
        assert task.results[0].backend == "cosine"
        assert task.results[0].answer == "test answer"

    async def test_append_result_multiple_results(self):
        """Appending multiple results should accumulate in order."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        for backend in ("cosine", "langchain", "llamaindex"):
            await tm.append_result(
                "task-1",
                BackendResult(backend=backend, answer=f"{backend} answer", sources=[]),
            )

        task = await tm.get_task("task-1")
        assert task is not None
        assert len(task.results) == 3
        assert task.results[1].backend == "langchain"

    async def test_append_result_noop_for_unknown_task(self):
        """Appending a result for a non-existent task should be a silent no-op."""
        tm = TaskManager()
        result = BackendResult(backend="cosine", answer="test", sources=[])
        await tm.append_result("nonexistent", result)  # Should not raise


class TestTaskManagerUpdateProgress:
    """Tests for TaskManager.update_progress()."""

    async def test_update_progress_sets_message(self):
        """Updating progress should set the message for the given backend."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        await tm.update_progress("task-1", "cosine", "Starting cosine...")

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.progress["cosine"] == "Starting cosine..."

    async def test_update_progress_overwrites_previous(self):
        """Updating progress for the same backend should overwrite the previous message."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        await tm.update_progress("task-1", "cosine", "Starting...")
        await tm.update_progress("task-1", "cosine", "Running...")

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.progress["cosine"] == "Running..."

    async def test_update_progress_multiple_backends(self):
        """Different backends should have independent progress messages."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        await tm.update_progress("task-1", "cosine", "Starting...")
        await tm.update_progress("task-1", "langchain", "Starting LangChain...")

        task = await tm.get_task("task-1")
        assert task is not None
        assert task.progress["cosine"] == "Starting..."
        assert task.progress["langchain"] == "Starting LangChain..."


class TestTaskManagerCleanup:
    """Tests for TaskManager.cleanup()."""

    async def test_cleanup_removes_old_tasks(self):
        """Tasks older than 1 hour should be removed by cleanup."""
        tm = TaskManager()
        # Create two tasks, one old and one new
        with patch("time.time", return_value=1000.0):
            t1 = await tm.create_task("old", "user-1")
            t1.created_at = 1000.0 - 7200  # 2 hours ago

        with patch("time.time", return_value=1000.0):
            await tm.create_task("new", "user-1")  # current time (1000.0)

        with patch("time.time", return_value=1000.0):
            await tm.cleanup()

        assert await tm.get_task("old") is None
        assert await tm.get_task("new") is not None

    async def test_cleanup_keeps_tasks_just_under_one_hour(self):
        """Tasks younger than 1 hour should survive cleanup."""
        tm = TaskManager()
        with patch("time.time", return_value=1000.0):
            t = await tm.create_task("recent", "user-1")
            t.created_at = 1000.0 - 3599  # 59 min 59 sec ago

        with patch("time.time", return_value=1000.0):
            await tm.cleanup()

        assert await tm.get_task("recent") is not None

    async def test_cleanup_keeps_tasks_exactly_one_hour_old(self):
        """A task created exactly 3600 seconds ago should NOT survive."""
        tm = TaskManager()
        with patch("time.time", return_value=1000.0):
            t = await tm.create_task("boundary", "user-1")
            t.created_at = 1000.0 - 3600

        with patch("time.time", return_value=1000.0):
            await tm.cleanup()

        # 3600 is NOT < 3600, so it should be removed
        assert await tm.get_task("boundary") is None

    async def test_cleanup_removes_only_old_tasks(self):
        """Multiple old tasks should all be removed while new tasks remain."""
        tm = TaskManager()
        with patch("time.time", return_value=1000.0):
            for i in range(5):
                t = await tm.create_task(f"old-{i}", "user-1")
                t.created_at = 1000.0 - 7200

            for i in range(3):
                await tm.create_task(f"new-{i}", "user-1")

        with patch("time.time", return_value=1000.0):
            await tm.cleanup()

        for task_id in [f"old-{i}" for i in range(5)]:
            assert await tm.get_task(task_id) is None

        for task_id in [f"new-{i}" for i in range(3)]:
            assert await tm.get_task(task_id) is not None

    async def test_cleanup_empty_task_manager(self):
        """Calling cleanup on an empty TaskManager should not raise."""
        tm = TaskManager()
        await tm.cleanup()  # Should not raise


class TestTaskManagerGetTaskCount:
    """Tests for TaskManager.get_task_count()."""

    async def test_get_task_count_returns_zero_initially(self):
        """A fresh TaskManager should report 0 tasks."""
        tm = TaskManager()
        assert tm.get_task_count() == 0

    async def test_get_task_count_increases_with_tasks(self):
        """Each new task should increment the count."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")
        assert tm.get_task_count() == 1

        await tm.create_task("task-2", "user-2")
        assert tm.get_task_count() == 2

    async def test_get_task_count_decreases_after_cleanup(self):
        """Cleanup should decrease the task count."""
        tm = TaskManager()
        with patch("time.time", return_value=1000.0):
            t = await tm.create_task("old", "user-1")
            t.created_at = 1000.0 - 7200
            await tm.create_task("new", "user-1")

        with patch("time.time", return_value=1000.0):
            await tm.cleanup()

        assert tm.get_task_count() == 1


class TestTaskManagerThreadSafety:
    """Tests for TaskManager async lock concurrency safety."""

    async def test_concurrent_create_and_update(self):
        """Concurrent create and update operations should not corrupt state."""
        tm = TaskManager()

        async def create_and_update(task_id: str, user_id: str):
            await tm.create_task(task_id, user_id)
            await tm.update_status(task_id, TaskStatus.RUNNING)
            await tm.update_status(task_id, TaskStatus.COMPLETED)
            await tm.append_result(
                task_id,
                BackendResult(backend="cosine", answer="result", sources=[]),
            )

        tasks = [create_and_update(f"task-{i}", f"user-{i}") for i in range(20)]
        await asyncio.gather(*tasks)

        assert tm.get_task_count() == 20
        for i in range(20):
            task = await tm.get_task(f"task-{i}")
            assert task is not None
            assert task.status == TaskStatus.COMPLETED
            assert len(task.results) == 1

    async def test_concurrent_create_same_user_hits_limit(self):
        """Concurrent creates for the same user should respect per-user limit."""
        tm = TaskManager(max_tasks=1000, max_tasks_per_user=5)

        async def create_for_user(i: int):
            try:
                await tm.create_task(f"user1-task-{i}", "user-1")
                return "ok"
            except TaskLimitError:
                return "limit"

        results = await asyncio.gather(*[create_for_user(i) for i in range(20)])

        # At most 5 should succeed
        ok_count = sum(1 for r in results if r == "ok")
        assert ok_count <= 5

        # The rest should hit the limit
        limit_count = sum(1 for r in results if r == "limit")
        assert limit_count >= 15

    async def test_lock_prevents_race_conditions(self):
        """The async Lock should prevent interleaving that could cause data loss."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        async def fast_append():
            await tm.append_result(
                "task-1",
                BackendResult(backend="cosine", answer="a", sources=[]),
            )

        # Run many concurrent appends
        await asyncio.gather(*[fast_append() for _ in range(100)])

        task = await tm.get_task("task-1")
        assert task is not None
        assert len(task.results) == 100

    async def test_progress_updates_under_concurrency(self):
        """Concurrent progress updates should not lose entries."""
        tm = TaskManager()
        await tm.create_task("task-1", "user-1")

        async def update(backend: str):
            await tm.update_progress("task-1", backend, f"Running {backend}")

        await asyncio.gather(
            update("cosine"),
            update("langchain"),
            update("llamaindex"),
        )

        task = await tm.get_task("task-1")
        assert task is not None
        assert set(task.progress.keys()) == {"cosine", "langchain", "llamaindex"}


# Import asyncio for concurrency tests
import asyncio  # noqa: E402 (needed for concurrency test fixtures)
