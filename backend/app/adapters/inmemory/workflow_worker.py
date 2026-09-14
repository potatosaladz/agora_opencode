"""In-memory workflow-worker lifecycle adapter."""

from __future__ import annotations

import asyncio

from app.ports.workflow import WorkflowWorker

__all__ = ["InMemoryWorkflowWorker"]


class InMemoryWorkflowWorker:
    """A cancellable worker loop for offline process-lifecycle tests."""

    def __init__(self) -> None:
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        await self._shutdown.wait()

    async def shutdown(self) -> None:
        self._shutdown.set()


_WORKER_PORT: type[WorkflowWorker] = InMemoryWorkflowWorker
