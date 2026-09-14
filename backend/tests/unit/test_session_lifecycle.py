"""T4-02 lifecycle graph, persistence, and start idempotency tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.adapters.inmemory.session_lifecycle import InMemorySessionLifecycleStore
from app.application.session_start import SessionStartService
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import LedgerAppend, LedgerEvent
from app.domain.session_bootstrap import SessionBootstrapInput, session_workflow_id
from app.domain.session_lifecycle import (
    InvalidSessionTransition,
    SessionLifecycleState,
    SessionTransition,
    validate_session_transition,
)
from app.ports.health import HealthStatus
from app.ports.workflow import WorkflowExecution, WorkflowInput, WorkflowSignal, WorkflowStart
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 10))
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


class RecordingLedger:
    def __init__(self) -> None:
        self.events: list[LedgerAppend] = []

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        try:
            index = next(index for index, item in enumerate(self.events) if item.id == event.id)
        except StopIteration:
            self.events.append(event)
            index = len(self.events) - 1
        else:
            if self.events[index].model_dump(exclude={"recorded_at"}) != event.model_dump(
                exclude={"recorded_at"}
            ):
                raise ValueError("event id reused with different content")
        return LedgerEvent(
            **event.model_dump(),
            ledger_seq=index + 1,
            payload_hash="sha256:" + "1" * 64,
            prev_hash="sha256:" + "0" * 64,
            event_hash="sha256:" + "2" * 64,
        )

    async def read(self, *_args: object, **_kwargs: object) -> tuple[LedgerEvent, ...]:
        return ()

    async def verify(self, *_args: object, **_kwargs: object) -> Any:
        raise NotImplementedError


def transition(
    event_id: UUID,
    source: SessionLifecycleState,
    target: SessionLifecycleState,
    *,
    round_: int = 0,
) -> SessionTransition:
    return SessionTransition(
        source=source,
        target=target,
        round=round_,
        event=LedgerAppend(
            id=event_id,
            workspace_id=U[0],
            session_id=U[1],
            event_type="SESSION_INITIALIZED",
            payload_schema_version=1,
            correlation_id=U[2],
            actor_class=ActorClass.SERVICE,
            actor_id=U[3],
            round=round_,
            payload={"from": source.value, "to": target.value},
            recorded_at=NOW,
        ),
    )


@req("FR-104", "FR-107", "FR-207")
@pytest.mark.parametrize(
    ("source", "target"),
    [
        (SessionLifecycleState.DRAFT, SessionLifecycleState.RUNNING),
        (SessionLifecycleState.COMPLETED, SessionLifecycleState.RUNNING),
        (SessionLifecycleState.PAUSED, SessionLifecycleState.COMPLETED),
    ],
)
def test_transition_graph_rejects_skips_and_terminal_restarts(
    source: SessionLifecycleState, target: SessionLifecycleState
) -> None:
    with pytest.raises(InvalidSessionTransition):
        validate_session_transition(source, target, current_round=0, next_round=0)


@req("FR-104", "FR-107", "FR-207")
def test_transition_graph_allows_only_single_round_advance_into_running() -> None:
    validate_session_transition(
        SessionLifecycleState.INITIALIZING,
        SessionLifecycleState.RUNNING,
        current_round=0,
        next_round=1,
    )
    with pytest.raises(InvalidSessionTransition, match="at most one"):
        validate_session_transition(
            SessionLifecycleState.INITIALIZING,
            SessionLifecycleState.RUNNING,
            current_round=0,
            next_round=2,
        )


@req("FR-104", "FR-107", "FR-207")
async def test_inmemory_transition_is_atomic_and_exact_event_retry_is_idempotent() -> None:
    ledger = RecordingLedger()
    store = InMemorySessionLifecycleStore(ledger)
    await store.add_draft(U[0], U[1], created_at=NOW - timedelta(seconds=1))
    command = transition(U[4], SessionLifecycleState.DRAFT, SessionLifecycleState.INITIALIZING)

    first = await store.transition(command)
    replay = await store.transition(command)

    assert first == replay
    assert first.state is SessionLifecycleState.INITIALIZING
    assert first.initialized_at == first.started_at == NOW
    assert [event.id for event in ledger.events] == [U[4]]
    with pytest.raises(InvalidSessionTransition, match="expected session state"):
        await store.transition(
            transition(U[5], SessionLifecycleState.DRAFT, SessionLifecycleState.INITIALIZING)
        )


class RecordingWorkflowEngine:
    def __init__(self) -> None:
        self.input: WorkflowInput | None = None
        self.workflow_id: str | None = None

    async def start(
        self,
        workflow_id: str,
        workflow_type: str,
        workflow_input: WorkflowInput,
        *,
        task_queue: str,
        timeout_s: float,
    ) -> WorkflowStart:
        del workflow_type, task_queue, timeout_s
        started = self.input is None
        if started:
            self.input, self.workflow_id = workflow_input, workflow_id
        return WorkflowStart(workflow_id=workflow_id, run_id="original-run", started=started)

    async def describe(self, workflow_id: str, *, timeout_s: float) -> WorkflowExecution:
        del workflow_id, timeout_s
        raise NotImplementedError

    async def signal(
        self, workflow_id: str, workflow_signal: WorkflowSignal, *, timeout_s: float
    ) -> None:
        del workflow_id, workflow_signal, timeout_s
        raise NotImplementedError

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        return None


class FailsFirstAttachment(InMemorySessionLifecycleStore):
    def __init__(self, ledger: RecordingLedger) -> None:
        super().__init__(ledger)
        self.fail = True

    async def attach_workflow(
        self, workspace_id: UUID, session_id: UUID, *, workflow_id: str, run_id: str
    ) -> Any:
        if self.fail:
            self.fail = False
            raise RuntimeError("transaction rolled back")
        return await super().attach_workflow(
            workspace_id, session_id, workflow_id=workflow_id, run_id=run_id
        )


@req("FR-104", "FR-107", "FR-207")
async def test_retry_after_attachment_rollback_reattaches_original_run_and_input() -> None:
    store = FailsFirstAttachment(RecordingLedger())
    engine = RecordingWorkflowEngine()
    await store.add_draft(U[0], U[1], created_at=NOW)
    original = SessionBootstrapInput(
        workspace_id=U[0],
        session_id=U[1],
        initialized_event_id=U[2],
        round_started_event_id=U[3],
        failed_event_id=U[4],
        correlation_id=U[5],
    )
    retry = original.model_copy(
        update={
            "initialized_event_id": U[6],
            "round_started_event_id": U[7],
            "failed_event_id": U[8],
        }
    )
    service = SessionStartService(store, engine)

    with pytest.raises(RuntimeError, match="rolled back"):
        await service.start(original)
    attached = await service.start(retry)

    assert attached.workflow_id == session_workflow_id(U[1])
    assert attached.run_id == "original-run"
    assert engine.input is not None
    assert engine.input.payload["initialized_event_id"] == str(U[2])
    assert engine.input.payload["round_started_event_id"] == str(U[3])
    assert engine.input.payload["failed_event_id"] == str(U[4])
