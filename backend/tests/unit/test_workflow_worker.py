"""Worker lifecycle boundaries remain separate from workflow client commands."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from temporalio.worker import Worker

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.inmemory.workflow_worker import InMemoryWorkflowWorker
from app.adapters.temporal.workflow_worker import TemporalWorkflowWorker
from app.composition.workflow_worker import build_workflow_worker
from app.config import Settings
from app.db.session import Database
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.workflow import WorkflowWorker
from tests.traceability import req


@req("FR-105", "NFR-020")
async def test_inmemory_worker_run_stops_on_shutdown() -> None:
    worker = InMemoryWorkflowWorker()
    assert isinstance(worker, WorkflowWorker)
    running = asyncio.create_task(worker.run())

    await worker.shutdown()
    await asyncio.wait_for(running, timeout=1.0)


@req("FR-105", "NFR-020")
async def test_temporal_wrapper_delegates_run_and_shutdown() -> None:
    calls: list[str] = []

    class FakeWorker:
        async def run(self) -> None:
            calls.append("run")

        async def shutdown(self) -> None:
            calls.append("shutdown")

    worker = TemporalWorkflowWorker(cast(Worker, FakeWorker()))

    await worker.run()
    await worker.shutdown()

    assert calls == ["run", "shutdown"]


@req("FR-105", "NFR-020")
async def test_temporal_worker_requires_definitions() -> None:
    with pytest.raises(PermanentPortError, match="at least one workflow"):
        await TemporalWorkflowWorker.connect(
            "temporal:7233",
            namespace="default",
            task_queue="session-workflows",
            workflows=(),
        )


@req("FR-105", "NFR-020")
async def test_temporal_worker_never_leaks_runtime_failure() -> None:
    class FailingWorker:
        async def run(self) -> None:
            raise RuntimeError("SDK worker failed")

        async def shutdown(self) -> None:
            raise RuntimeError("SDK shutdown failed")

    worker = TemporalWorkflowWorker(cast(Worker, FailingWorker()))

    with pytest.raises(TransientPortError, match="worker failed"):
        await worker.run()
    with pytest.raises(TransientPortError, match="shutdown failed"):
        await worker.shutdown()


@req("FR-105", "NFR-020")
async def test_production_composition_registers_bootstrap_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeDatabase:
        async def close(self) -> None:
            captured["database_closed"] = True

    class FakeObjectStore(InMemoryObjectStore):
        async def close(self) -> None:
            captured["object_store_closed"] = True
            await super().close()

    class FakeWorker:
        @classmethod
        async def connect(cls, address: str, **options: Any) -> FakeWorker:
            captured.update(address=address, **options)
            return cls()

        async def run(self) -> None:
            return None

        async def shutdown(self) -> None:
            captured["worker_closed"] = True

    fake_database = cast(Database, FakeDatabase())
    monkeypatch.setattr(
        "app.composition.workflow_worker.create_database", lambda _settings: fake_database
    )
    monkeypatch.setattr(
        "app.composition.workflow_worker._object_store", lambda _settings: FakeObjectStore()
    )
    monkeypatch.setattr("app.composition.workflow_worker.TemporalWorkflowWorker", FakeWorker)
    settings = Settings(
        environment="test",
        temporal_address="workflow.internal:7233",
        temporal_namespace="agora-test",
        temporal_task_queue="bootstrap-test",
    )

    runtime = await build_workflow_worker(settings)

    assert captured["address"] == "workflow.internal:7233"
    assert captured["namespace"] == "agora-test"
    assert captured["task_queue"] == "bootstrap-test"
    assert captured["workflows"][0].__name__ == "SessionBootstrapWorkflow"
    assert [item.__name__ for item in captured["activities"]] == [
        "commit_transition",
        "commit_transition",
        "run_turn",
        "ingest_source",
    ]
    await runtime.close()
    assert captured["worker_closed"] is True
    assert captured["object_store_closed"] is True
    assert captured["database_closed"] is True
