"""SQLAlchemy implementation of the tenant-scoped agent registry port."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentDefinitionRow,
    LLMCallRecordRow,
    LLMConfigurationRow,
    LLMCredentialEnvelopeRow,
)
from app.db.session import Database
from app.domain.agent_registry import (
    AgentDefinition,
    AgentRegistry,
    AgentRoleKind,
    AgentStatus,
    CredentialEnvelope,
    LLMCallRecord,
    LLMConfiguration,
    ProviderKind,
)
from app.ports.errors import PermanentPortError
from app.ports.storage import SecretRef

__all__ = ["SqlAlchemyAgentRegistry", "SqlAlchemyAgentRegistryFacade"]


class SqlAlchemyAgentRegistry:
    """Map domain values to rows inside one caller-owned RLS transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_configuration(self, configuration: LLMConfiguration) -> None:
        self._session.add(
            LLMConfigurationRow(
                id=configuration.id,
                workspace_id=configuration.workspace_id,
                name=configuration.name,
                provider_kind=configuration.provider_kind.value,
                base_url=configuration.base_url,
                model=configuration.model,
                embedding_model=configuration.embedding_model,
                api_version=configuration.api_version,
                secret_provider=configuration.secret_ref.provider,
                secret_name=configuration.secret_ref.name,
                secret_version=configuration.secret_ref.version,
                capabilities=dict(configuration.capabilities),
                rate_limit=dict(configuration.rate_limit),
                is_active=configuration.is_active,
            )
        )
        await self._session.flush()

    async def get_configuration(self, configuration_id: UUID) -> LLMConfiguration | None:
        row = await self._session.get(LLMConfigurationRow, configuration_id)
        if row is None:
            return None
        return LLMConfiguration(
            id=row.id,
            workspace_id=row.workspace_id,
            name=row.name,
            provider_kind=ProviderKind(row.provider_kind),
            base_url=row.base_url,
            model=row.model,
            embedding_model=row.embedding_model,
            api_version=row.api_version,
            secret_ref=SecretRef(
                provider=row.secret_provider, name=row.secret_name, version=row.secret_version
            ),
            capabilities=dict(row.capabilities),
            rate_limit=dict(row.rate_limit),
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def put_credential_envelope(
        self, configuration_id: UUID, workspace_id: UUID, envelope: CredentialEnvelope
    ) -> None:
        self._session.add(
            LLMCredentialEnvelopeRow(
                llm_config_id=configuration_id,
                workspace_id=workspace_id,
                ciphertext=envelope.ciphertext,
                credential_nonce=envelope.credential_nonce,
                wrapped_data_key=envelope.wrapped_data_key,
                wrapping_nonce=envelope.wrapping_nonce,
                algorithm=envelope.algorithm,
                master_key_provider=envelope.master_key_ref.provider,
                master_key_name=envelope.master_key_ref.name,
                master_key_version=envelope.master_key_ref.version,
            )
        )
        await self._session.flush()

    async def get_credential_envelope(self, configuration_id: UUID) -> CredentialEnvelope | None:
        row = await self._session.get(LLMCredentialEnvelopeRow, configuration_id)
        if row is None:
            return None
        return CredentialEnvelope(
            ciphertext=row.ciphertext,
            credential_nonce=row.credential_nonce,
            wrapped_data_key=row.wrapped_data_key,
            wrapping_nonce=row.wrapping_nonce,
            algorithm=row.algorithm,
            master_key_ref=SecretRef(
                provider=row.master_key_provider,
                name=row.master_key_name,
                version=row.master_key_version,
            ),
        )

    async def add_definition(self, definition: AgentDefinition) -> None:
        self._session.add(
            AgentDefinitionRow(
                id=definition.id,
                workspace_id=definition.workspace_id,
                logical_id=definition.logical_id,
                version=definition.version,
                name=definition.name,
                domain=definition.domain,
                role_kind=definition.role_kind.value,
                objectives=list(definition.objectives),
                constraints=list(definition.constraints),
                knowledge_ns=list(definition.knowledge_ns),
                strategy_ref=definition.strategy_ref,
                strategy_ver=definition.strategy_ver,
                prompt_ref=definition.prompt_ref,
                prompt_hash=definition.prompt_hash,
                llm_config_id=definition.llm_config_id,
                tool_perms=list(definition.tool_perms),
                budget=dict(definition.budget),
                status=definition.status.value,
                superseded_by=definition.superseded_by,
                referenced_at=definition.referenced_at,
            )
        )
        await self._session.flush()

    async def add_definition_version(self, previous_id: UUID, definition: AgentDefinition) -> None:
        previous = await self.get_definition(previous_id)
        if previous is None:
            raise ValueError("previous agent definition does not exist")
        if (
            definition.logical_id != previous.logical_id
            or definition.version != previous.version + 1
        ):
            raise ValueError("agent definition version must follow the same logical definition")
        await self.add_definition(definition)
        await self._session.execute(
            update(AgentDefinitionRow)
            .where(AgentDefinitionRow.id == previous_id)
            .values(superseded_by=definition.id, status=AgentStatus.DEPRECATED.value)
        )
        await self._session.flush()

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
        row = await self._session.get(AgentDefinitionRow, definition_id)
        if row is None:
            return None
        return AgentDefinition(
            id=row.id,
            workspace_id=row.workspace_id,
            logical_id=row.logical_id,
            version=row.version,
            name=row.name,
            domain=row.domain,
            role_kind=AgentRoleKind(row.role_kind),
            objectives=tuple(row.objectives),
            constraints=tuple(row.constraints),
            knowledge_ns=tuple(row.knowledge_ns),
            strategy_ref=row.strategy_ref,
            strategy_ver=row.strategy_ver,
            prompt_ref=row.prompt_ref,
            prompt_hash=row.prompt_hash,
            llm_config_id=row.llm_config_id,
            tool_perms=tuple(row.tool_perms),
            budget=dict(row.budget),
            status=AgentStatus(row.status),
            superseded_by=row.superseded_by,
            referenced_at=row.referenced_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add_call_record(self, record: LLMCallRecord) -> None:
        inserted_id = await self._session.scalar(
            insert(LLMCallRecordRow)
            .values(
                id=record.id,
                workspace_id=record.workspace_id,
                session_id=record.session_id,
                agent_def_id=record.agent_def_id,
                llm_config_id=record.llm_config_id,
                provider=record.provider,
                model=record.model,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cost_usd=record.cost_usd,
                latency_ms=record.latency_ms,
                finish_reason=record.finish_reason,
                retry_attempts=record.retry_attempts,
                raw_artifact_ref=record.raw_artifact_ref,
                correlation_id=record.correlation_id,
            )
            .on_conflict_do_nothing(index_elements=[LLMCallRecordRow.id])
            .returning(LLMCallRecordRow.id)
        )
        if inserted_id is not None:
            return
        existing = await self._session.get(LLMCallRecordRow, record.id)
        if existing is None or not _same_call_record(_call_record(existing), record):
            raise PermanentPortError(
                "LLM call id was reused with different content", port="agent_registry"
            )

    async def list_call_records(self) -> tuple[LLMCallRecord, ...]:
        rows = (
            await self._session.scalars(
                select(LLMCallRecordRow).order_by(LLMCallRecordRow.created_at, LLMCallRecordRow.id)
            )
        ).all()
        return tuple(_call_record(row) for row in rows)


def _call_record(row: LLMCallRecordRow) -> LLMCallRecord:
    return LLMCallRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        agent_def_id=row.agent_def_id,
        llm_config_id=row.llm_config_id,
        provider=row.provider,
        model=row.model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        latency_ms=row.latency_ms,
        finish_reason=row.finish_reason,
        retry_attempts=row.retry_attempts,
        raw_artifact_ref=row.raw_artifact_ref,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
    )


def _same_call_record(left: LLMCallRecord, right: LLMCallRecord) -> bool:
    return (
        left.id,
        left.workspace_id,
        left.session_id,
        left.agent_def_id,
        left.llm_config_id,
        left.provider,
        left.model,
        left.input_tokens,
        left.output_tokens,
        left.cost_usd,
        left.latency_ms,
        left.finish_reason,
        left.retry_attempts,
        left.raw_artifact_ref,
        left.correlation_id,
    ) == (
        right.id,
        right.workspace_id,
        right.session_id,
        right.agent_def_id,
        right.llm_config_id,
        right.provider,
        right.model,
        right.input_tokens,
        right.output_tokens,
        right.cost_usd,
        right.latency_ms,
        right.finish_reason,
        right.retry_attempts,
        right.raw_artifact_ref,
        right.correlation_id,
    )


class SqlAlchemyAgentRegistryFacade:
    """Process-safe registry facade opening one tenant transaction per operation.

    Temporal activity instances are process-lived, while ``AsyncSession`` is transaction-local.
    Keeping only ``Database`` and the verified workspace identity here prevents a session from
    leaking across activity invocations or concurrent turns.
    """

    def __init__(self, database: Database, workspace_id: UUID) -> None:
        self._database = database
        self._workspace_id = workspace_id

    async def add_configuration(self, configuration: LLMConfiguration) -> None:
        self._require_workspace(configuration.workspace_id)
        async with self._database.session(self._workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).add_configuration(configuration)

    async def get_configuration(self, configuration_id: UUID) -> LLMConfiguration | None:
        async with self._database.session(self._workspace_id) as session:
            return await SqlAlchemyAgentRegistry(session).get_configuration(configuration_id)

    async def put_credential_envelope(
        self, configuration_id: UUID, workspace_id: UUID, envelope: CredentialEnvelope
    ) -> None:
        self._require_workspace(workspace_id)
        async with self._database.session(self._workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).put_credential_envelope(
                configuration_id, workspace_id, envelope
            )

    async def get_credential_envelope(self, configuration_id: UUID) -> CredentialEnvelope | None:
        async with self._database.session(self._workspace_id) as session:
            return await SqlAlchemyAgentRegistry(session).get_credential_envelope(configuration_id)

    async def add_definition(self, definition: AgentDefinition) -> None:
        self._require_workspace(definition.workspace_id)
        async with self._database.session(self._workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).add_definition(definition)

    async def add_definition_version(self, previous_id: UUID, definition: AgentDefinition) -> None:
        self._require_workspace(definition.workspace_id)
        async with self._database.session(self._workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).add_definition_version(previous_id, definition)

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
        async with self._database.session(self._workspace_id) as session:
            return await SqlAlchemyAgentRegistry(session).get_definition(definition_id)

    async def add_call_record(self, record: LLMCallRecord) -> None:
        self._require_workspace(record.workspace_id)
        async with self._database.session(self._workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).add_call_record(record)

    async def list_call_records(self) -> tuple[LLMCallRecord, ...]:
        async with self._database.session(self._workspace_id) as session:
            return await SqlAlchemyAgentRegistry(session).list_call_records()

    def _require_workspace(self, workspace_id: UUID) -> None:
        if workspace_id != self._workspace_id:
            raise ValueError("registry value belongs to another workspace")


_REGISTRY_PORT: type[AgentRegistry] = SqlAlchemyAgentRegistry
_REGISTRY_FACADE_PORT: type[AgentRegistry] = SqlAlchemyAgentRegistryFacade
