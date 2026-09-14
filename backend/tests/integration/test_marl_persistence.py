"""Live PostgreSQL contract proof for Phase 12 trajectory storage."""

from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.application.marl import MarlTrajectoryService, export_episode
from app.db.marl import SqlAlchemyMarlTrajectoryStore
from app.db.session import Database
from app.domain.marl import EpisodeStatus, MarlConflictError, MarlEpisodeV1
from tests.integration.test_reasoning_persistence import _insert_session_graph, _migrated_database
from tests.traceability import req
from tests.unit.test_marl import CODE_HASH, _transition

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]


def _open(workspace_id: UUID, session_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
    return MarlEpisodeV1(
        episode_id=episode_id,
        workspace_id=workspace_id,
        session_id=session_id,
        environment_version="agora-marl-v1",
        code_identity=CODE_HASH,
        status=EpisodeStatus.OPEN,
    )


@req("FR-906", "NFR-003", "NFR-010", "NFR-016")
async def test_marl_store_round_trip_rollback_rls_append_only_and_no_commit() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "marl")
        database = Database(engine)
        transition = _transition(
            0,
            terminal=True,
            workspace_id=fixture.workspace_id,
            session_id=fixture.session_id,
        )
        episode = _open(fixture.workspace_id, fixture.session_id, transition.episode_id)

        async with database.session(fixture.workspace_id) as session:
            service = MarlTrajectoryService(SqlAlchemyMarlTrajectoryStore(session))
            await service.open(episode)
            await service.capture(fixture.workspace_id, transition.boundary)
            await service.close(fixture.workspace_id, transition)
            completed = await service.complete(fixture.workspace_id, episode.episode_id)
            assert completed.status is EpisodeStatus.COMPLETE
            assert export_episode(completed).trajectory.endswith(b"\n")

        async with database.session(fixture.workspace_id) as session:
            stored = await SqlAlchemyMarlTrajectoryStore(session).get(
                fixture.workspace_id, episode.episode_id
            )
            assert stored == completed

        rollback_id = UUID("00000000-0000-0000-0000-000000000099")

        async def rolled_back_write() -> None:
            async with database.session(fixture.workspace_id) as session:
                await SqlAlchemyMarlTrajectoryStore(session).create(
                    _open(fixture.workspace_id, fixture.session_id, rollback_id)
                )
                raise RuntimeError("rollback")

        with pytest.raises(RuntimeError, match="rollback"):
            await rolled_back_write()
        async with database.session(fixture.workspace_id) as session:
            assert (
                await SqlAlchemyMarlTrajectoryStore(session).get(fixture.workspace_id, rollback_id)
                is None
            )

        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM marl_trajectory_records WHERE episode_id=:episode"),
                    {"episode": episode.episode_id},
                )

        async with engine.connect() as connection:
            forced = set(
                (
                    await connection.execute(
                        text(
                            "SELECT relname FROM pg_class WHERE relname = ANY(:tables) "
                            "AND relrowsecurity AND relforcerowsecurity"
                        ),
                        {"tables": ["marl_episodes", "marl_trajectory_records"]},
                    )
                ).scalars()
            )
            assert forced == {"marl_episodes", "marl_trajectory_records"}
        await database.close()


@req("FR-906", "NFR-003")
async def test_marl_store_idempotent_replay_conflict_and_gap_rejection() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "marl-conflict")
        database = Database(engine)
        transition = _transition(
            0,
            terminal=True,
            workspace_id=fixture.workspace_id,
            session_id=fixture.session_id,
        )
        episode = _open(fixture.workspace_id, fixture.session_id, transition.episode_id)
        async with database.session(fixture.workspace_id) as session:
            store = SqlAlchemyMarlTrajectoryStore(session)
            await store.create(episode)
            await store.capture(fixture.workspace_id, transition.boundary)
            assert await store.capture(fixture.workspace_id, transition.boundary)
            await store.close(fixture.workspace_id, transition)
            assert await store.close(fixture.workspace_id, transition)
            corrupted = transition.model_copy(update={"transition_hash": "sha256:" + "f" * 64})
            with pytest.raises(MarlConflictError):
                await store.close(fixture.workspace_id, corrupted)
        await database.close()
