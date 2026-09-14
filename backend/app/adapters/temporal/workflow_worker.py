"""Temporal workflow-worker lifecycle adapter.

Definition registration is constructor-time infrastructure composition. It does not belong on
the client-side ``WorkflowEngine`` port and cannot be mutated after polling starts.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from temporalio.client import Client
from temporalio.exceptions import TemporalError
from temporalio.worker import Worker

from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.workflow import WorkflowWorker

__all__ = ["TemporalWorkflowWorker"]

_PORT = "workflow_worker"


class TemporalWorkflowWorker:
    """Run one immutable set of definitions on one Temporal task queue."""

    def __init__(self, worker: Worker) -> None:
        self._worker = worker

    @classmethod
    async def connect(
        cls,
        address: str,
        *,
        namespace: str,
        task_queue: str,
        workflows: Sequence[type[object]],
        activities: Sequence[Callable[..., object]] = (),
    ) -> TemporalWorkflowWorker:
        if not address.strip() or not namespace.strip() or not task_queue.strip():
            raise PermanentPortError(
                "Temporal address, namespace, and task queue must not be blank", port=_PORT
            )
        if not workflows:
            raise PermanentPortError(
                "a workflow worker requires at least one workflow definition", port=_PORT
            )
        try:
            client = await Client.connect(address, namespace=namespace, lazy=False)
            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=workflows,
                activities=activities,
            )
        except ValueError as exc:
            raise PermanentPortError(
                f"invalid Temporal worker configuration: {exc}", port=_PORT, cause=exc
            ) from exc
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal worker connect failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal worker connect failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        return cls(worker)

    async def run(self) -> None:
        try:
            await self._worker.run()
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal worker failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal worker failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc

    async def shutdown(self) -> None:
        try:
            await self._worker.shutdown()
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal worker shutdown failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal worker shutdown failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc


_WORKER_PORT: type[WorkflowWorker] = TemporalWorkflowWorker
