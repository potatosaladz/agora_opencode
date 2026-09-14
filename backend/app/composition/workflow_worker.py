"""Production composition root for Temporal workflows and nondeterministic activities."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from app.adapters.ingestion import parse_document
from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.llm.mock import MockLLMProvider
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.adapters.minio.object_store import MinioObjectStore
from app.adapters.secrets.providers import EnvSecretProvider, SwarmSecretProvider
from app.adapters.temporal.agent_activity import AgentActivities
from app.adapters.temporal.ingestion_activity import IngestionActivities
from app.adapters.temporal.session_bootstrap import (
    SessionBootstrapActivities,
    SessionBootstrapWorkflow,
)
from app.adapters.temporal.session_control import SessionControlActivities
from app.adapters.temporal.workflow_worker import TemporalWorkflowWorker
from app.application.agent_activity import AgentTurnRunner, ProviderFactory
from app.application.ingestion import SourceIngestionRunner
from app.config.settings import Settings, get_settings
from app.db import Database, create_database
from app.db.agent_registry import SqlAlchemyAgentRegistryFacade
from app.db.ingestion import SqlAlchemyIngestionCheckpointStore
from app.db.session_bootstrap import SqlAlchemySessionTransitionCommitter
from app.db.session_control import SqlAlchemySessionControlTransitionCommitter
from app.domain.agent_registry import LLMConfiguration, ProviderKind
from app.ports.llm import LLMProvider
from app.ports.storage import ObjectStore, SecretProvider

__all__ = ["WorkflowWorkerRuntime", "build_workflow_worker", "run_workflow_worker"]


@dataclass(slots=True)
class WorkflowWorkerRuntime:
    worker: TemporalWorkflowWorker
    database: Database
    object_store: ObjectStore

    async def run(self) -> None:
        await self.worker.run()

    async def close(self) -> None:
        try:
            await self.worker.shutdown()
        finally:
            try:
                await self.object_store.close()
            finally:
                await self.database.close()


async def build_workflow_worker(settings: Settings) -> WorkflowWorkerRuntime:
    database = create_database(settings)
    object_store = _object_store(settings)
    secret_provider = _secret_provider(settings)
    bootstrap_activities = SessionBootstrapActivities(
        SqlAlchemySessionTransitionCommitter(
            database, service_actor_id=settings.workflow_service_actor_id
        )
    )
    control_activities = SessionControlActivities(
        SqlAlchemySessionControlTransitionCommitter(database)
    )
    agent_activities = AgentActivities(
        AgentTurnRunner(
            lambda workspace_id: SqlAlchemyAgentRegistryFacade(database, workspace_id),
            _provider_factory(
                object_store,
                secret_provider,
                artifact_bucket=settings.minio_bucket,
            ),
            object_store,
            prompt_bucket=settings.minio_bucket,
            code_version=settings.code_version,
        )
    )
    ingestion_activities = IngestionActivities(
        SourceIngestionRunner(
            SqlAlchemyIngestionCheckpointStore(database),
            object_store,
            parse_document,
            bucket=settings.minio_bucket,
        )
    )
    try:
        worker = await TemporalWorkflowWorker.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            task_queue=settings.temporal_task_queue,
            workflows=(SessionBootstrapWorkflow,),
            activities=(
                bootstrap_activities.commit_transition,
                control_activities.commit_transition,
                agent_activities.run_turn,
                ingestion_activities.ingest_source,
            ),
        )
    except Exception:
        with suppress(Exception):
            await object_store.close()
        with suppress(Exception):
            await database.close()
        raise
    return WorkflowWorkerRuntime(worker, database, object_store)


def _object_store(settings: Settings) -> ObjectStore:
    if settings.object_store == "minio":
        return MinioObjectStore(
            settings.minio_endpoint,
            settings.minio_access_key.get_secret_value(),
            settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
            bucket=settings.minio_bucket,
        )
    return InMemoryObjectStore()


def _secret_provider(settings: Settings) -> SecretProvider:
    if settings.secret_provider == "swarm_secret":
        return SwarmSecretProvider()
    return EnvSecretProvider()


def _provider_factory(
    object_store: ObjectStore,
    secret_provider: SecretProvider,
    *,
    artifact_bucket: str,
) -> ProviderFactory:
    def build(configuration: LLMConfiguration) -> LLMProvider:
        if configuration.provider_kind is ProviderKind.OPENAI_COMPATIBLE:
            return OpenAICompatibleProvider(
                configuration.base_url,
                secret_provider,
                object_store,
                artifact_bucket=artifact_bucket,
            )
        return MockLLMProvider(object_store, {}, artifact_bucket=artifact_bucket)

    return build


async def run_workflow_worker(settings: Settings | None = None) -> None:
    runtime = await build_workflow_worker(settings or get_settings())
    try:
        await runtime.run()
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(run_workflow_worker())
