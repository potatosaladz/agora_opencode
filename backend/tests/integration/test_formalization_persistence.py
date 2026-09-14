"""Live PostgreSQL proof for T11-01 authoritative formalization facts."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.application.formalization import FormalizationContext, FormalizationLifecycleService
from app.db.formalization import SqlAlchemyFormalizationRepository
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.session import Database
from app.domain.formalization import (
    FormalizationDecisionKind,
    FormalizationRevision,
    IntegerLiteral,
    Operation,
    Operator,
    Sort,
    SymbolDeclaration,
    SymbolReference,
    ast_hash,
    render_ast,
)
from app.domain.reasoning import ActorClass
from tests.integration.test_reasoning_persistence import (
    _alembic_config,
    _claim_artifact,
    _insert_session_graph,
    _migrated_database,
)
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]


@req("FR-707")
async def test_formalization_facts_are_forced_rls_append_only_and_guarded() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "formalization")
        source = _claim_artifact(fixture, uuid4(), uuid4())
        database = Database(engine)
        async with database.session(fixture.workspace_id) as session:
            await SqlAlchemyReasoningArtifactStore(session).add(source)

        tables = ["formalizations", "formalization_validations", "formalization_decisions"]
        async with engine.connect() as connection:
            forced = set(
                (
                    await connection.execute(
                        text(
                            "SELECT relname FROM pg_class WHERE relname = ANY(:tables) "
                            "AND relrowsecurity AND relforcerowsecurity"
                        ),
                        {"tables": tables},
                    )
                ).scalars()
            )
        assert forced == set(tables)

        node = Operation(
            operator=Operator.LE,
            arguments=(SymbolReference(name="cost"), IntegerLiteral(value="100")),
        )
        identity, now, correlation = uuid4(), datetime(2026, 9, 12, 12, tzinfo=UTC), uuid4()
        value = FormalizationRevision(
            id=identity,
            logical_id=identity,
            revision=1,
            supersedes_id=None,
            workspace_id=fixture.workspace_id,
            session_id=fixture.session_id,
            source_artifact_id=source.id,
            source_artifact_logical_id=source.logical_id,
            source_artifact_version=source.version,
            ast=node,
            ast_hash=ast_hash(node),
            symbols=(
                SymbolDeclaration(name="cost", sort=Sort.INTEGER, meaning="cost", unit="USD"),
            ),
            canonical_rendering=render_ast(node),
            premise_artifact_ids=(),
            limitations=("nominal",),
            fidelity_notes="timing omitted",
            created_at=now,
            actor_class=ActorClass.HUMAN,
            actor_id=fixture.user_id,
            correlation_id=correlation,
        )
        async with database.session(fixture.workspace_id) as session:
            service = FormalizationLifecycleService(SqlAlchemyFormalizationRepository(session))
            await service.create(
                value, context=FormalizationContext(fixture.user_id, correlation, now, uuid4())
            )
            await service.validate(
                fixture.workspace_id,
                identity,
                expected_revision=1,
                validation_id=uuid4(),
                context=FormalizationContext(fixture.user_id, correlation, now, uuid4()),
            )
            result = await service.decide(
                fixture.workspace_id,
                identity,
                expected_revision=1,
                decision_id=uuid4(),
                kind=FormalizationDecisionKind.CONFIRMED,
                reason="reviewed",
                context=FormalizationContext(fixture.user_id, correlation, now, uuid4()),
            )
            assert result.enforceable

        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE formalizations SET fidelity_notes='changed' WHERE id=:id"),
                    {"id": identity},
                )
        await asyncio.to_thread(command.check, _alembic_config())
        await database.close()
