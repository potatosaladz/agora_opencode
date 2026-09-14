"""PostgreSQL acceptance evidence for T13-04 run manifests.

trace: NFR-003, NFR-014
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.application.replay import (
    ReplayImplementation,
    ReplayImplementationRegistry,
    SessionReplayService,
)
from app.application.run_manifest import PersistedReplaySource, RunManifestService
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.db.run_manifest import SqlAlchemyRunManifestRepository
from app.domain.reasoning import content_hash
from app.domain.replay import (
    ReplayExecution,
    ReplayImplementationIdentity,
    ReplayMode,
    ReplayOutcome,
    ReplayRequest,
    ReplayStep,
    ReplayStepKind,
    ReplayStepPolicy,
)
from app.domain.run_manifest import (
    AgentPin,
    CodePin,
    ConsensusPin,
    ContentPin,
    MetricPin,
    RunManifestDocument,
    RunManifestStatus,
    SchemaPin,
    run_manifest_hash,
)
from tests.integration.test_reasoning_persistence import (
    TenantFixture,
    _database_url,
    _insert_session_graph,
    _ledger_append,
    _migrated_database,
)
from tests.traceability import req

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _database_url(), reason="PostgreSQL test settings are not configured"),
]

NOW = datetime(2026, 9, 14, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _identity() -> ReplayImplementationIdentity:
    return ReplayImplementationIdentity(
        implementation_id="agora.consensus.weighted",
        implementation_version="1.0.0",
        configuration_hash=DIGEST_B,
    )


def _document(
    fixture: TenantFixture, *, source_session_id: UUID | None = None
) -> RunManifestDocument:
    input_value = {"scores": [1, 2]}
    output = {"winner": "a"}
    return RunManifestDocument(
        workspace_id=fixture.workspace_id,
        session_id=fixture.session_id,
        source_session_id=source_session_id,
        code=CodePin(git_sha="1cad09a", image_digests={"backend": DIGEST_A}),
        schema_pin=SchemaPin(migration_head="20260914_0026", artifact_schema_version=1),
        configuration_hash=DIGEST_B,
        protocol="deliberative",
        rounds=6,
        budget={"max_rounds": 6, "max_tokens": 1000, "max_usd": "10.00"},
        consensus=ConsensusPin(
            strategy_id="weighted", strategy_version="1.0.0", parameters={"threshold": "0.6"}
        ),
        agents=(
            AgentPin(
                definition_id=fixture.agent_id,
                definition_version=1,
                prompt_ref="prompts/expert-v1.txt",
                prompt_hash=DIGEST_A,
                strategy_id="evidence-first",
                strategy_version="1.0.0",
            ),
        ),
        metrics=(MetricPin(metric_id="ep-01", metric_version="1"),),
        contents=(
            ContentPin(
                content_id=fixture.objective_id,
                kind="ARTIFACT",
                version=1,
                content_hash=DIGEST_B,
            ),
        ),
        replay_steps=(
            ReplayStep(
                step_id=uuid4(),
                order=1,
                kind=ReplayStepKind.CONSENSUS,
                policy=ReplayStepPolicy.DETERMINISTIC,
                implementation=_identity(),
                input=input_value,
                input_hash=content_hash(input_value),
                expected_output=output,
                expected_output_hash=content_hash(output),
            ),
        ),
        started_at=NOW,
    )


async def _insert_created_manifest(
    connection: AsyncConnection, fixture: TenantFixture, *, manifest_id: UUID | None = None
) -> UUID:
    value = manifest_id or uuid4()
    await connection.execute(
        text(
            "INSERT INTO reproducibility_manifests ("
            "id, workspace_id, session_id, manifest_version, status, git_sha, image_digests, "
            "model_pins, prompt_hashes, created_at) VALUES ("
            ":id, :workspace_id, :session_id, 1, 'CREATED', 'abc', "
            "CAST(:images AS jsonb), '{}'::jsonb, '{}'::jsonb, :created_at)"
        ),
        {
            "id": value,
            "workspace_id": fixture.workspace_id,
            "session_id": fixture.session_id,
            "images": '{"backend":"sha256:' + "a" * 64 + '"}',
            "created_at": NOW,
        },
    )
    return value


@req("NFR-003", "NFR-014")
async def test_manifest_round_trip_finalization_and_strict_replay() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "manifest-roundtrip")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        objects = InMemoryObjectStore()
        document = _document(fixture)
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            await ledger.append(_ledger_append(fixture, uuid4(), "manifest-event"))
            manifests = SqlAlchemyRunManifestRepository(session)
            service = RunManifestService(manifests, objects, bucket="manifests")
            created = await service.create(
                workspace_id=fixture.workspace_id,
                session_id=fixture.session_id,
                source_session_id=None,
                git_sha=document.code.git_sha,
                image_digests=document.code.image_digests,
                model_pins={},
                prompt_hashes={str(fixture.agent_id): DIGEST_A},
                seed=None,
                created_at=NOW,
            )
            finalized = await service.finalize(
                fixture.workspace_id,
                fixture.session_id,
                document,
                finalized_at=NOW + timedelta(seconds=1),
            )
            assert created.status is RunManifestStatus.CREATED
            assert finalized.manifest_hash == run_manifest_hash(document)

        async with sessions.begin() as session:
            source = PersistedReplaySource(
                SqlAlchemyRunManifestRepository(session),
                objects,
                SqlAlchemyReasoningLedger(session),
            )

            async def execute(input_value: object) -> ReplayExecution:
                output = {"winner": "a"}
                return ReplayExecution(
                    implementation=_identity(), output=output, output_hash=content_hash(output)
                )

            replay = SessionReplayService(
                source,
                SqlAlchemyReasoningLedger(session),
                ReplayImplementationRegistry(
                    (
                        ReplayImplementation(
                            _identity(), execute, deterministic=True, external=False
                        ),
                    )
                ),
            )
            result = await replay.replay(
                ReplayRequest(
                    workspace_id=fixture.workspace_id,
                    source_session_id=fixture.session_id,
                    manifest=finalized.ref(),
                    mode=ReplayMode.STRICT,
                )
            )
            assert result.outcome is ReplayOutcome.VERIFIED


@req("NFR-003", "NFR-014")
async def test_manifest_constraints_append_only_and_forced_rls() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "manifest-guards")
            manifest_id = await _insert_created_manifest(connection, fixture)

        async with engine.begin() as connection:
            with pytest.raises(DBAPIError) as mutation:
                await connection.execute(
                    text("UPDATE reproducibility_manifests SET git_sha = 'changed' WHERE id = :id"),
                    {"id": manifest_id},
                )
        assert getattr(mutation.value.orig, "sqlstate", None) == "27000"

        async with engine.begin() as connection:
            with pytest.raises(DBAPIError) as duplicate:
                await _insert_created_manifest(connection, fixture)
        assert getattr(duplicate.value.orig, "sqlstate", None) == "23505"

        async with engine.begin() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                        "WHERE oid = 'reproducibility_manifests'::regclass"
                    )
                )
                is True
            )

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE reproducibility_manifests SET status = 'FINALIZED', "
                    "manifest_bucket = 'manifests', manifest_ref = 'manifest.json', "
                    "manifest_hash = :manifest_hash, manifest_size = 2, "
                    "finalized_at = :finalized_at "
                    "WHERE id = :id"
                ),
                {"id": manifest_id, "manifest_hash": DIGEST_A, "finalized_at": NOW},
            )
        async with engine.begin() as connection:
            with pytest.raises(DBAPIError) as finalized_mutation:
                await connection.execute(
                    text(
                        "UPDATE reproducibility_manifests SET manifest_hash = :manifest_hash "
                        "WHERE id = :id"
                    ),
                    {"id": manifest_id, "manifest_hash": DIGEST_B},
                )
        assert getattr(finalized_mutation.value.orig, "sqlstate", None) == "27000"

        async with engine.begin() as connection:
            other = await _insert_session_graph(connection, "manifest-source-fk")
            with pytest.raises(DBAPIError) as source_fk:
                await connection.execute(
                    text(
                        "INSERT INTO reproducibility_manifests ("
                        "id, workspace_id, session_id, source_session_id, "
                        "manifest_version, status, "
                        "git_sha, image_digests, model_pins, prompt_hashes, created_at) VALUES ("
                        ":id, :workspace_id, :session_id, :source_session_id, 1, 'CREATED', 'abc', "
                        "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, :created_at)"
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": other.workspace_id,
                        "session_id": other.session_id,
                        "source_session_id": fixture.session_id,
                        "created_at": NOW,
                    },
                )
        assert getattr(source_fk.value.orig, "sqlstate", None) == "23503"

        role = "agora_t1304_manifest_reader"
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(
                text(f"GRANT SELECT, INSERT ON reproducibility_manifests TO {role}")
            )
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(fixture.workspace_id)},
            )
            assert (
                await connection.scalar(text("SELECT count(*) FROM reproducibility_manifests")) == 1
            )
            with pytest.raises(DBAPIError) as rls:
                await connection.execute(
                    text(
                        "INSERT INTO reproducibility_manifests ("
                        "id, workspace_id, session_id, manifest_version, status, git_sha, "
                        "image_digests, model_pins, prompt_hashes, created_at) VALUES ("
                        ":id, :workspace_id, :session_id, 1, 'CREATED', 'abc', "
                        "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, :created_at)"
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": uuid4(),
                        "session_id": fixture.session_id,
                        "created_at": NOW,
                    },
                )
        assert getattr(rls.value.orig, "sqlstate", None) == "42501"
