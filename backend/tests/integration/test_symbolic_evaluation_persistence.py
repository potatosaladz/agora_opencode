"""Live PostgreSQL proof for T11-03 exact-revision symbolic evidence."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.adapters.z3_symbolic import Z3SymbolicReasoner
from app.application.formalization import FormalizationContext, FormalizationLifecycleService
from app.application.symbolic_evaluation import SymbolicEvaluationContext, SymbolicEvaluationService
from app.db.formalization import SqlAlchemyFormalizationRepository
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.session import Database
from app.db.symbolic_evaluation import SqlAlchemySymbolicEvaluationRepository
from app.domain.formalization import (
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
from app.ports.symbolic import SymbolicStatus
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


@req("FR-705", "FR-706")
async def test_symbolic_evidence_is_exact_idempotent_forced_rls_and_append_only() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "symbolic-evaluation")
        source = _claim_artifact(fixture, uuid4(), uuid4())
        database = Database(engine)
        async with database.session(fixture.workspace_id) as session:
            await SqlAlchemyReasoningArtifactStore(session).add(source)

        x = SymbolReference(name="x")
        node = Operation(
            operator=Operator.AND,
            arguments=(
                Operation(
                    operator=Operator.GT,
                    arguments=(x, IntegerLiteral(value="10")),
                ),
                Operation(
                    operator=Operator.LT,
                    arguments=(x, IntegerLiteral(value="5")),
                ),
            ),
        )
        identity, now, correlation = uuid4(), datetime(2026, 9, 12, 13, tzinfo=UTC), uuid4()
        revision = FormalizationRevision(
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
            symbols=(SymbolDeclaration(name="x", sort=Sort.INTEGER, meaning="test", unit="1"),),
            canonical_rendering=render_ast(node),
            premise_artifact_ids=(),
            limitations=("test scope",),
            fidelity_notes="exact test",
            created_at=now,
            actor_class=ActorClass.HUMAN,
            actor_id=fixture.user_id,
            correlation_id=correlation,
        )
        async with database.session(fixture.workspace_id) as session:
            await FormalizationLifecycleService(SqlAlchemyFormalizationRepository(session)).create(
                revision,
                context=FormalizationContext(fixture.user_id, correlation, now, uuid4()),
            )

        evaluation_id = uuid4()
        async with database.session(fixture.workspace_id) as session:
            service = SymbolicEvaluationService(
                Z3SymbolicReasoner(timeout_ms=500),
                SqlAlchemySymbolicEvaluationRepository(session),
            )
            first = await service.evaluate(
                revision,
                context=SymbolicEvaluationContext(evaluation_id, fixture.user_id, correlation, now),
            )
            replay = await service.evaluate(
                revision,
                context=SymbolicEvaluationContext(uuid4(), fixture.user_id, correlation, now),
            )
            assert replay == first
            assert first.result.status is SymbolicStatus.UNSAT
            assert [member.ast_path for member in first.result.unsat_core] == [
                "ast.arguments[0]",
                "ast.arguments[1]",
            ]

        async with engine.connect() as connection:
            forced = await connection.scalar(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                    "WHERE relname='symbolic_evaluations'"
                )
            )
        assert forced is True
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE symbolic_evaluations SET timeout_ms=1 WHERE id=:id"),
                    {"id": evaluation_id},
                )
        await asyncio.to_thread(command.check, _alembic_config())
        await database.close()
