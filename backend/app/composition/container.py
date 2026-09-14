"""Runtime adapter selection and lifecycle ownership.

Only this module imports concrete adapters. Application and API code receive ports from
``Container`` and therefore remain independent of infrastructure SDKs (ADR-012).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.adapters.inmemory.cache import InMemoryCache
from app.adapters.inmemory.event_bus import InMemoryEventBus
from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.inmemory.workflow import InMemoryWorkflowEngine
from app.adapters.minio.object_store import MinioObjectStore
from app.adapters.nats.event_bus import NatsJetStreamEventBus
from app.adapters.redis.cache import RedisCache
from app.adapters.secrets.providers import EnvSecretProvider, SwarmSecretProvider
from app.adapters.temporal.workflow import TemporalWorkflowEngine
from app.adapters.z3_symbolic import Z3SymbolicReasoner
from app.common.errors import ValidationFailed
from app.config.settings import Settings
from app.db import Database, create_database
from app.db.audit import (
    SqlAlchemyAccessLogRepository,
    SqlAlchemyAuditAnchorRepository,
    SqlAlchemySessionParticipantReader,
)
from app.db.citations import SqlAlchemyCitationRepository
from app.db.consensus import SqlAlchemyConsensusResultStore
from app.db.coordinator_policy import SqlAlchemyCoordinatorPolicyStore
from app.db.critique_handoff import SqlAlchemyCritiqueExplanationHandoffReader
from app.db.critique_response import SqlAlchemyCritiqueResponseStore
from app.db.dissent import SqlAlchemyDissentConsensusExplanationReader
from app.db.formalization import SqlAlchemyFormalizationRepository
from app.db.memory import SqlAlchemyMemoryProvider
from app.db.phase3_api import SqlAlchemyIdempotencyStore, SqlAlchemyPhase3SessionStore
from app.db.realtime import LedgerEventPublisher, RealtimeGateway
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.reasoning_graph import SqlAlchemyReasoningGraphStore
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.db.run_manifest import SqlAlchemyRunManifestRepository
from app.db.session_lifecycle import SqlAlchemySessionLifecycleStore
from app.db.source_impact import SqlAlchemySourceImpactRepository
from app.db.symbolic_evaluation import SqlAlchemySymbolicEvaluationRepository
from app.domain.audit import (
    AccessLogRepository,
    AuditAnchorRepository,
    SessionParticipantReader,
)
from app.domain.citations import CitationRepository
from app.domain.consensus import ConsensusResultStore
from app.domain.coordinator_policy import CoordinatorPolicyStore
from app.domain.critique import CritiqueResponseStore
from app.domain.critique_handoff import CritiqueExplanationHandoffReader
from app.domain.dissent import DissentConsensusExplanationReader
from app.domain.formalization import FormalizationRepository, FormalizationRevision
from app.domain.memory import MemoryProvider
from app.domain.phase3_api import IdempotencyStore, Phase3ArtifactStore, Phase3SessionStore
from app.domain.reasoning_graph import ReasoningGraphStore
from app.domain.reasoning_ledger import AgentProposalLedger
from app.domain.run_manifest import RunManifestRepository
from app.domain.session_lifecycle import SessionLifecycleStore
from app.domain.source_impact import SourceImpactRepository
from app.domain.symbolic_evaluation import SymbolicEvaluationRepository
from app.ports.auth import AccessTokenVerifier
from app.ports.data import Cache
from app.ports.event_bus import EventBus
from app.ports.health import ComponentHealth, HealthStatus
from app.ports.storage import ObjectStore, SecretProvider
from app.ports.symbolic import SymbolicReasoner
from app.ports.workflow import WorkflowEngine
from app.security.auth import UnconfiguredAccessTokenVerifier

__all__ = ["Container", "StartupConfigurationError", "build_container"]

HealthCheck = Callable[[], Awaitable[ComponentHealth]]
Closer = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ReasoningTransaction:
    artifacts: Phase3ArtifactStore
    citations: CitationRepository
    graph: ReasoningGraphStore
    ledger: AgentProposalLedger
    sessions: Phase3SessionStore
    idempotency: IdempotencyStore
    lifecycle: SessionLifecycleStore
    memory: MemoryProvider
    coordinator_policy: CoordinatorPolicyStore
    critique_responses: CritiqueResponseStore
    critique_handoffs: CritiqueExplanationHandoffReader
    source_impacts: SourceImpactRepository
    consensus_results: ConsensusResultStore
    dissent_explanations: DissentConsensusExplanationReader
    formalizations: FormalizationRepository
    symbolic_evaluations: SymbolicEvaluationRepository
    access_logs: AccessLogRepository
    audit_anchors: AuditAnchorRepository
    session_participants: SessionParticipantReader
    run_manifests: RunManifestRepository


class StartupConfigurationError(ValueError):
    """The selected deployment configuration is unsafe or incomplete."""


@dataclass(slots=True)
class Container:
    """Process-scoped ports plus deterministic dependency cleanup."""

    event_bus: EventBus
    workflow_engine: WorkflowEngine
    cache: Cache
    object_store: ObjectStore
    secret_provider: SecretProvider
    access_token_verifier: AccessTokenVerifier
    symbolic_reasoner: SymbolicReasoner[FormalizationRevision]
    database: Database
    settings: Settings
    realtime_gateway: RealtimeGateway
    readiness_checks: Mapping[str, HealthCheck]
    _closers: tuple[Closer, ...] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @asynccontextmanager
    async def reasoning_transaction(
        self, workspace_id: UUID
    ) -> AsyncIterator[ReasoningTransaction]:
        """Build caller-scoped adapters that share one tenant transaction."""
        ledger: SqlAlchemyReasoningLedger | None = None
        try:
            async with self.database.session(workspace_id) as session:
                ledger = SqlAlchemyReasoningLedger(session)
                yield ReasoningTransaction(
                    artifacts=SqlAlchemyReasoningArtifactStore(session),
                    memory=SqlAlchemyMemoryProvider(session),
                    citations=SqlAlchemyCitationRepository(session),
                    graph=SqlAlchemyReasoningGraphStore(session),
                    ledger=ledger,
                    sessions=SqlAlchemyPhase3SessionStore(session),
                    idempotency=SqlAlchemyIdempotencyStore(session),
                    lifecycle=SqlAlchemySessionLifecycleStore(session, ledger),
                    coordinator_policy=SqlAlchemyCoordinatorPolicyStore(session),
                    critique_responses=SqlAlchemyCritiqueResponseStore(session),
                    critique_handoffs=SqlAlchemyCritiqueExplanationHandoffReader(session),
                    source_impacts=SqlAlchemySourceImpactRepository(
                        session, SqlAlchemyReasoningGraphStore(session)
                    ),
                    consensus_results=SqlAlchemyConsensusResultStore(session),
                    dissent_explanations=SqlAlchemyDissentConsensusExplanationReader(session),
                    formalizations=SqlAlchemyFormalizationRepository(session),
                    symbolic_evaluations=SqlAlchemySymbolicEvaluationRepository(session),
                    access_logs=SqlAlchemyAccessLogRepository(session),
                    audit_anchors=SqlAlchemyAuditAnchorRepository(session),
                    session_participants=SqlAlchemySessionParticipantReader(session),
                    run_manifests=SqlAlchemyRunManifestRepository(session),
                )
        except IntegrityError as exc:
            raise ValidationFailed("request conflicts with persisted tenant state") from exc
        if ledger is not None:
            await LedgerEventPublisher(
                self.event_bus, code_version=self.settings.code_version
            ).publish(ledger.appended)

    async def close(self) -> None:
        """Close initialized resources once, in reverse construction order."""
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for closer in reversed(self._closers):
            try:
                await closer()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


async def build_container(settings: Settings) -> Container:
    """Validate policy, construct selected adapters, and initialize eager dependencies."""
    _validate(settings)

    if settings.event_bus == "nats":
        event_bus: EventBus = NatsJetStreamEventBus(settings.nats_url, stream=settings.nats_stream)
    else:
        event_bus = InMemoryEventBus()

    if settings.workflow_engine == "temporal":
        workflow_engine: WorkflowEngine = await TemporalWorkflowEngine.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            connect_timeout_s=settings.temporal_connect_timeout_s,
            health_timeout_s=settings.temporal_health_timeout_s,
        )
    else:
        workflow_engine = InMemoryWorkflowEngine()

    if settings.cache == "redis":
        cache: Cache = RedisCache(settings.redis_url)
    else:
        cache = InMemoryCache()

    if settings.object_store == "minio":
        object_store: ObjectStore = MinioObjectStore(
            settings.minio_endpoint,
            settings.minio_access_key.get_secret_value(),
            settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
            bucket=settings.minio_bucket,
        )
    else:
        object_store = InMemoryObjectStore()

    if settings.secret_provider == "swarm_secret":
        secret_provider: SecretProvider = SwarmSecretProvider()
    else:
        secret_provider = EnvSecretProvider()

    database = create_database(settings)
    realtime_gateway = RealtimeGateway(database, event_bus, code_version=settings.code_version)

    closers: tuple[Closer, ...] = (
        event_bus.close,
        cache.close,
        object_store.close,
        database.close,
        workflow_engine.close,
    )
    try:
        if isinstance(event_bus, NatsJetStreamEventBus):
            await event_bus.connect()
        await realtime_gateway.start()
    except Exception:
        await _close_safely(closers)
        raise

    return Container(
        event_bus=event_bus,
        workflow_engine=workflow_engine,
        cache=cache,
        object_store=object_store,
        secret_provider=secret_provider,
        access_token_verifier=UnconfiguredAccessTokenVerifier(),
        symbolic_reasoner=Z3SymbolicReasoner(timeout_ms=settings.symbolic_timeout_ms),
        database=database,
        settings=settings,
        realtime_gateway=realtime_gateway,
        readiness_checks={
            "database": _health_check("database", database.health),
            "workflow_engine": _health_check("workflow_engine", workflow_engine.health),
            "event_bus": _health_check("event_bus", event_bus.health),
            "cache": _health_check("cache", cache.health),
            "object_store": _health_check("object_store", object_store.health),
            "secret_provider": _health_check("secret_provider", secret_provider.health),
        },
        _closers=closers,
    )


def _validate(settings: Settings) -> None:
    problems = settings.startup_problems()
    if settings.object_store == "inmemory" and not settings.is_test:
        problems.append("the in-memory object store is allowed only in the test environment")
    if settings.object_store == "minio":
        if not settings.minio_access_key.get_secret_value():
            problems.append("minio_access_key is empty while the MinIO adapter is selected")
        if not settings.minio_secret_key.get_secret_value():
            problems.append("minio_secret_key is empty while the MinIO adapter is selected")
    if problems:
        raise StartupConfigurationError("invalid startup configuration: " + "; ".join(problems))


def _health_check(name: str, check: Callable[[], Awaitable[HealthStatus]]) -> HealthCheck:
    async def wrapped() -> ComponentHealth:
        return ComponentHealth(name, await check())

    return wrapped


async def _close_safely(closers: tuple[Closer, ...]) -> None:
    for closer in reversed(closers):
        with suppress(Exception):
            await closer()
