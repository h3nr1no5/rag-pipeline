"""Shared types and protocols for the API documentation RAG pipeline.

Security note on ``ProgressReporter``:
    This protocol must never accept user-supplied callables.  Using a typed
    protocol instead of a raw ``Callable[[str, str], Awaitable[None]]``
    prevents callback injection from untrusted sources by making the expected
    interface explicit and auditable at the type level.
"""

from __future__ import annotations

from typing import Protocol


class ProgressReporter(Protocol):
    """Protocol for reporting progress during long-running operations.

    Security constraint — must never be backed by user-supplied code.
    Only trusted internal implementations (or their wrappers) should satisfy
    this protocol.

    Usage::

        class MyReporter:
            async def report(self, step: str, message: str) -> None:
                print(f"[{step}] {message}")

        reporter: ProgressReporter = MyReporter()
        await reporter.report("indexing", "Embedding chunks…")
    """

    async def report(self, step: str, message: str) -> None:
        """Report a progress update.

        Args:
            step: The processing step identifier
                  (e.g. ``"extracting"``, ``"indexing"``).
            message: A human-readable progress message.
        """
        ...
