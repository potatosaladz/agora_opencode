"""Temporal implementation of the typed ``WorkflowEngine`` client port."""

from __future__ import annotations

from datetime import timedelta

from temporalio.client import Client
from temporalio.client import WorkflowExecutionStatus as TemporalExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import TemporalError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus
from app.ports.workflow import (
    WorkflowEngine,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowInput,
    WorkflowSignal,
    WorkflowStart,
)

__all__ = ["TemporalWorkflowEngine"]

_PORT = "workflow_engine"
_PERMANENT_RPC_STATUSES = frozenset(
    {
        RPCStatusCode.INVALID_ARGUMENT,
        RPCStatusCode.NOT_FOUND,
        RPCStatusCode.ALREADY_EXISTS,
        RPCStatusCode.PERMISSION_DENIED,
        RPCStatusCode.FAILED_PRECONDITION,
        RPCStatusCode.OUT_OF_RANGE,
        RPCStatusCode.UNIMPLEMENTED,
        RPCStatusCode.UNAUTHENTICATED,
    }
)
_STATUS_MAP = {
    TemporalExecutionStatus.RUNNING: WorkflowExecutionStatus.RUNNING,
    TemporalExecutionStatus.COMPLETED: WorkflowExecutionStatus.COMPLETED,
    TemporalExecutionStatus.FAILED: WorkflowExecutionStatus.FAILED,
    TemporalExecutionStatus.CANCELED: WorkflowExecutionStatus.CANCELED,
    TemporalExecutionStatus.TERMINATED: WorkflowExecutionStatus.TERMINATED,
    TemporalExecutionStatus.CONTINUED_AS_NEW: WorkflowExecutionStatus.CONTINUED_AS_NEW,
    TemporalExecutionStatus.TIMED_OUT: WorkflowExecutionStatus.TIMED_OUT,
}


class TemporalWorkflowEngine:
    """Durable execution client backed by Temporal Python SDK 1.32.x."""

    def __init__(self, client: Client, *, health_timeout_s: float = 3.0) -> None:
        self._client = client
        self._health_timeout_s = health_timeout_s
        self._closed = False

    @classmethod
    async def connect(
        cls,
        address: str,
        *,
        namespace: str,
        connect_timeout_s: float = 5.0,
        health_timeout_s: float = 3.0,
    ) -> TemporalWorkflowEngine:
        if not address.strip() or not namespace.strip():
            raise PermanentPortError("Temporal address and namespace must not be blank", port=_PORT)
        if connect_timeout_s <= 0 or health_timeout_s <= 0:
            raise PermanentPortError("Temporal timeouts must be positive", port=_PORT)
        try:
            client = await Client.connect(
                address,
                namespace=namespace,
                lazy=False,
            )
            serving = await client.service_client.check_health(
                timeout=timedelta(seconds=connect_timeout_s)
            )
        except RPCError as exc:
            raise _port_error("connect", exc) from exc
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal connect failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal connect failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        if not serving:
            raise TransientPortError("Temporal workflow service is not serving", port=_PORT)
        return cls(client, health_timeout_s=health_timeout_s)

    async def start(
        self,
        workflow_id: str,
        workflow_type: str,
        workflow_input: WorkflowInput,
        *,
        task_queue: str,
        timeout_s: float,
    ) -> WorkflowStart:
        self._guard("start")
        _validate_command(workflow_id, workflow_type, task_queue, timeout_s)
        try:
            handle = await self._client.start_workflow(
                workflow_type,
                workflow_input.model_dump(mode="json"),
                id=workflow_id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                rpc_timeout=timedelta(seconds=timeout_s),
            )
        except WorkflowAlreadyStartedError as exc:
            run_id = exc.run_id or await self._run_id(workflow_id, timeout_s=timeout_s)
            return WorkflowStart(workflow_id=workflow_id, run_id=run_id, started=False)
        except ValueError as exc:
            raise PermanentPortError(
                f"invalid Temporal start request: {exc}", port=_PORT, cause=exc
            ) from exc
        except RPCError as exc:
            raise _port_error("start", exc) from exc
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal start failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal start failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc

        run_id = handle.result_run_id or await self._run_id(workflow_id, timeout_s=timeout_s)
        return WorkflowStart(workflow_id=workflow_id, run_id=run_id, started=True)

    async def describe(self, workflow_id: str, *, timeout_s: float) -> WorkflowExecution:
        self._guard("describe")
        if not workflow_id.strip():
            raise PermanentPortError("workflow_id must not be blank", port=_PORT)
        if timeout_s <= 0:
            raise PermanentPortError("timeout_s must be positive", port=_PORT)
        try:
            description = await self._client.get_workflow_handle(workflow_id).describe(
                rpc_timeout=timedelta(seconds=timeout_s)
            )
        except RPCError as exc:
            raise _port_error("describe", exc) from exc
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal describe failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal describe failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        return WorkflowExecution(
            workflow_id=description.id,
            run_id=description.run_id,
            workflow_type=description.workflow_type,
            task_queue=description.task_queue,
            status=(
                _STATUS_MAP.get(description.status, WorkflowExecutionStatus.UNKNOWN)
                if description.status is not None
                else WorkflowExecutionStatus.UNKNOWN
            ),
            started_at=description.start_time,
            closed_at=description.close_time,
        )

    async def signal(
        self, workflow_id: str, workflow_signal: WorkflowSignal, *, timeout_s: float
    ) -> None:
        self._guard("signal")
        if not workflow_id.strip() or not workflow_signal.name.strip():
            raise PermanentPortError("workflow and signal names must not be blank", port=_PORT)
        if timeout_s <= 0:
            raise PermanentPortError("timeout_s must be positive", port=_PORT)
        try:
            await self._client.get_workflow_handle(workflow_id).signal(
                workflow_signal.name,
                workflow_signal.model_dump(mode="json"),
                rpc_timeout=timedelta(seconds=timeout_s),
            )
        except ValueError as exc:
            raise PermanentPortError(
                f"invalid Temporal signal request: {exc}", port=_PORT, cause=exc
            ) from exc
        except RPCError as exc:
            raise _port_error("signal", exc) from exc
        except TemporalError as exc:
            raise TransientPortError(
                f"Temporal signal failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc
        except Exception as exc:
            raise TransientPortError(
                f"Temporal signal failed: {type(exc).__name__}", port=_PORT, cause=exc
            ) from exc

    async def health(self) -> HealthStatus:
        if self._closed:
            return HealthStatus.DOWN
        try:
            serving = await self._client.service_client.check_health(
                timeout=timedelta(seconds=self._health_timeout_s)
            )
        except Exception:
            return HealthStatus.DOWN
        return HealthStatus.OK if serving else HealthStatus.DEGRADED

    async def close(self) -> None:
        # Temporal's Python client owns shared Core runtime resources and has no close API.
        # Marking the adapter closed prevents accidental use after its composition scope ends.
        self._closed = True

    async def _run_id(self, workflow_id: str, *, timeout_s: float) -> str:
        return (await self.describe(workflow_id, timeout_s=timeout_s)).run_id

    def _guard(self, operation: str) -> None:
        if self._closed:
            raise TransientPortError(f"workflow engine is closed; cannot {operation}", port=_PORT)


def _validate_command(
    workflow_id: str, workflow_type: str, task_queue: str, timeout_s: float
) -> None:
    if not workflow_id.strip():
        raise PermanentPortError("workflow_id must not be blank", port=_PORT)
    if not workflow_type.strip():
        raise PermanentPortError("workflow_type must not be blank", port=_PORT)
    if not task_queue.strip():
        raise PermanentPortError("task_queue must not be blank", port=_PORT)
    if timeout_s <= 0:
        raise PermanentPortError("timeout_s must be positive", port=_PORT)


def _port_error(operation: str, exc: RPCError) -> PermanentPortError | TransientPortError:
    message = f"Temporal {operation} failed with {exc.status.name}"
    if exc.status in _PERMANENT_RPC_STATUSES:
        return PermanentPortError(message, port=_PORT, cause=exc)
    return TransientPortError(message, port=_PORT, cause=exc)


_WORKFLOW_PORT: type[WorkflowEngine] = TemporalWorkflowEngine
