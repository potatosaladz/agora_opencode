"""PostgreSQL acceptance evidence for Phase 13 audit persistence (T13-02).

Proves the append-only semantics, tenant isolation and the Q7/Q8 chain on the
real schema: access-log round trips and cursor pagination, the
``recommendations`` lookup, same-day anchor conflicts, two-day chain
verification, tamper detection on a bypassed append-only trigger, and forced
RLS. Reuses the phase-3 migrated-database harness.

trace: FR-807, NFR-006
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
)

from app.application.audit import AccessAuditService, ChainVerificationService
from app.db.audit import (
    SqlAlchemyAccessLogRepository,
    SqlAlchemyAuditAnchorRepository,
)
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.domain import ActorClass
from app.domain.audit import (
    AccessLogEntry,
    AccessResult,
    AuditAction,
    AuditConflictError,
    AuditResourceKind,
)
from tests.integration.test_reasoning_persistence import (
    TenantFixture,
    _alembic_config,
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

DAY1 = datetime(2026, 9, 5, tzinfo=UTC)
DAY2 = DAY1 + timedelta(days=1)


def _log_entry(
    fixture: TenantFixture, *, resource_id: UUID, recorded_at: datetime
) -> AccessLogEntry:
    return AccessLogEntry(
        workspace_id=fixture.workspace_id,
        session_id=fixture.session_id,
        principal_class=ActorClass.HUMAN,
        principal_id=fixture.user_id,
        resource_kind=AuditResourceKind.RECOMMENDATION,
        resource_id=resource_id,
        action=AuditAction.READ,
        result=AccessResult.ALLOWED,
        scope_ids=("scope-a",),
        trace_id="trace-integration",
        recorded_at=recorded_at,
    )


async def _insert_access_log_row(
    connection: AsyncConnection,
    *,
    workspace_id: UUID,
    session_id: UUID,
    resource_id: UUID,
    recorded_at: datetime = DAY1,
) -> UUID:
    row_id = uuid4()
    await connection.execute(
        text(
            "INSERT INTO access_log ("
            "id, workspace_id, session_id, principal_class, principal_id, "
            "resource_kind, resource_id, action, result, scope_ids, trace_id, recorded_at"
            ") VALUES ("
            ":id, :workspace_id, :session_id, 'HUMAN', :principal_id, "
            "'RECOMMENDATION', :resource_id, 'READ', 'ALLOWED', "
            "CAST(:scope_ids AS jsonb), :trace_id, :recorded_at)"
        ),
        {
            "id": row_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "principal_id": uuid4(),
            "resource_id": resource_id,
            "scope_ids": json.dumps(["scope-a"]),
            "trace_id": "trace-sql",
            "recorded_at": recorded_at,
        },
    )
    return row_id


async def _insert_recommendation(
    connection: AsyncConnection,
    fixture: TenantFixture,
    *,
    recommendation_id: UUID,
    created_at: datetime,
) -> None:
    consensus_id = uuid4()
    await connection.execute(
        text(
            "INSERT INTO consensus_results ("
            "id, workspace_id, session_id, round, strategy, strategy_version, outcome, "
            "pareto_set, constraint_report, conditions, input_hash, created_at"
            ") VALUES ("
            ":id, :workspace_id, :session_id, 1, 'weighted', '1.0.0', 'FULL_CONSENSUS', "
            "CAST(:pareto_set AS uuid[]), '{}'::jsonb, '[]'::jsonb, :input_hash, :created_at)"
        ),
        {
            "id": consensus_id,
            "workspace_id": fixture.workspace_id,
            "session_id": fixture.session_id,
            "pareto_set": [fixture.objective_id],
            "input_hash": "sha256:" + "1" * 64,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            "INSERT INTO recommendations ("
            "id, workspace_id, session_id, consensus_id, rank, title, statement, "
            "conditions, risks, open_questions, created_at"
            ") VALUES ("
            ":id, :workspace_id, :session_id, :consensus_id, 1, 'R1', 'Recommended action', "
            "'[]'::jsonb, CAST(:risks AS uuid[]), '[]'::jsonb, :created_at)"
        ),
        {
            "id": recommendation_id,
            "workspace_id": fixture.workspace_id,
            "session_id": fixture.session_id,
            "consensus_id": consensus_id,
            "risks": [],
            "created_at": created_at,
        },
    )


@req("FR-807", "NFR-006")
async def test_access_log_round_trip_orders_and_paginates_by_cursor() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "audit-access-cursor")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        resource_id = uuid4()
        entries = [
            _log_entry(fixture, resource_id=resource_id, recorded_at=DAY1 + timedelta(hours=h))
            for h in range(3)
        ]
        async with sessions.begin() as session:
            store = SqlAlchemyAccessLogRepository(session)
            for entry in entries:
                await store.record(entry)

        async with sessions.begin() as session:
            store = SqlAlchemyAccessLogRepository(session)
            all_entries, _ = await store.list_for_resource(
                fixture.workspace_id,
                resource_kind=AuditResourceKind.RECOMMENDATION,
                resource_id=resource_id,
            )
            assert [entry.id for entry in all_entries] == [
                entry.id for entry in sorted(entries, key=lambda item: (item.recorded_at, item.id))
            ]
            assert await store.recommendation_created_at(fixture.workspace_id, resource_id) is None

            pages: list[tuple[AccessLogEntry, ...]] = []
            cursor: str | None = None
            while True:
                page, next_cursor = await store.list_for_resource(
                    fixture.workspace_id,
                    resource_kind=AuditResourceKind.RECOMMENDATION,
                    resource_id=resource_id,
                    limit=1,
                    cursor=cursor,
                )
                pages.append(page)
                cursor = next_cursor
                if cursor is None:
                    break
            assert [entry.id for entry in pages[0] + pages[1] + pages[2]] == [
                entry.id for entry in sorted(entries, key=lambda item: (item.recorded_at, item.id))
            ]


@req("FR-807", "NFR-006")
async def test_recommendation_access_reports_complete_timeline_before_acceptance() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "audit-q7")
            recommendation_id = uuid4()
            created_at = DAY2
            await _insert_recommendation(
                connection,
                fixture,
                recommendation_id=recommendation_id,
                created_at=created_at,
            )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            store = SqlAlchemyAccessLogRepository(session)
            for offset in (-3, -2, -1, 1):
                await store.record(
                    _log_entry(
                        fixture,
                        resource_id=recommendation_id,
                        recorded_at=created_at + timedelta(hours=offset),
                    )
                )

        async with sessions.begin() as session:
            report = await AccessAuditService(
                SqlAlchemyAccessLogRepository(session)
            ).recommendation_access(fixture.workspace_id, recommendation_id)

        assert report.recommendation_known is True
        assert report.recommendation_created_at == created_at
        assert report.complete_timeline is True
        assert report.truncated is False
        assert report.next_cursor is None
        assert len(report.entries) == 3
        assert all(entry.recorded_at < created_at for entry in report.entries)


@req("FR-807", "NFR-006")
async def test_audit_tables_foreign_keys_reject_unknown_sessions() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "audit-fk")
        with pytest.raises(DBAPIError) as access_fk:
            async with engine.begin() as connection:
                await _insert_access_log_row(
                    connection,
                    workspace_id=fixture.workspace_id,
                    session_id=uuid4(),
                    resource_id=fixture.objective_id,
                )
        assert getattr(access_fk.value.orig, "sqlstate", None) == "23503"

        with pytest.raises(DBAPIError) as anchor_fk:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO audit_anchors ("
                        "id, workspace_id, session_id, anchor_day, head_seq, head_hash, "
                        "prev_head_hash, anchor_hash, anchored_at"
                        ") VALUES ("
                        ":id, :workspace_id, :session_id, :anchor_day, 1, :head_hash, "
                        ":prev_head_hash, :anchor_hash, :anchored_at)"
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": fixture.workspace_id,
                        "session_id": uuid4(),
                        "anchor_day": DAY1.date(),
                        "head_hash": "sha256:" + "a" * 64,
                        "prev_head_hash": "sha256:" + "0" * 64,
                        "anchor_hash": "sha256:" + "b" * 64,
                        "anchored_at": DAY1,
                    },
                )
        assert getattr(anchor_fk.value.orig, "sqlstate", None) == "23503"


@req("FR-807", "NFR-006")
async def test_audit_tables_are_append_only_at_the_database() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "audit-append-only")
            row_id = await _insert_access_log_row(
                connection,
                workspace_id=fixture.workspace_id,
                session_id=fixture.session_id,
                resource_id=fixture.objective_id,
            )
            anchor_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO audit_anchors ("
                    "id, workspace_id, session_id, anchor_day, head_seq, head_hash, "
                    "prev_head_hash, anchor_hash, anchored_at"
                    ") VALUES ("
                    ":id, :workspace_id, :session_id, :anchor_day, 1, :head_hash, "
                    ":prev_head_hash, :anchor_hash, :anchored_at)"
                ),
                {
                    "id": anchor_id,
                    "workspace_id": fixture.workspace_id,
                    "session_id": fixture.session_id,
                    "anchor_day": DAY1.date(),
                    "head_hash": "sha256:" + "a" * 64,
                    "prev_head_hash": "sha256:" + "0" * 64,
                    "anchor_hash": "sha256:" + "b" * 64,
                    "anchored_at": DAY1,
                },
            )

        with pytest.raises(DBAPIError, match="append-only") as access_mutation:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE access_log SET trace_id = 'tampered' WHERE id = :id"),
                    {"id": row_id},
                )
        assert getattr(access_mutation.value.orig, "sqlstate", None) == "27000"

        with pytest.raises(DBAPIError, match="append-only") as access_deletion:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM access_log WHERE id = :id"), {"id": row_id}
                )
        assert getattr(access_deletion.value.orig, "sqlstate", None) == "27000"

        with pytest.raises(DBAPIError, match="append-only") as anchor_mutation:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE audit_anchors SET head_hash = :head_hash WHERE id = :id"),
                    {"id": anchor_id, "head_hash": "sha256:" + "c" * 64},
                )
        assert getattr(anchor_mutation.value.orig, "sqlstate", None) == "27000"


@req("FR-807", "NFR-006")
async def test_two_day_anchor_chain_verifies_and_same_day_conflicts() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "audit-chain")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            await ledger.append(_ledger_append(fixture, uuid4(), "day-one"))
            await ledger.append(
                _ledger_append(fixture, uuid4(), "day-two").model_copy(update={"recorded_at": DAY2})
            )
        async with sessions.begin() as session:
            service = ChainVerificationService(
                SqlAlchemyAuditAnchorRepository(session),
                SqlAlchemyReasoningLedger(session),
            )
            day1 = await service.publish_daily_anchor(
                fixture.workspace_id, fixture.session_id, anchor_day=DAY1.date()
            )
            day2 = await service.publish_daily_anchor(
                fixture.workspace_id, fixture.session_id, anchor_day=DAY2.date()
            )
            assert day1.head_seq == 1
            assert day1.prev_head_hash == "sha256:" + "0" * 64
            assert day2.head_seq == 2
            assert day2.prev_head_hash == day1.head_hash

        async with sessions.begin() as session:
            service = ChainVerificationService(
                SqlAlchemyAuditAnchorRepository(session),
                SqlAlchemyReasoningLedger(session),
            )
            with pytest.raises(AuditConflictError, match="already exists"):
                await service.publish_daily_anchor(
                    fixture.workspace_id, fixture.session_id, anchor_day=DAY2.date()
                )

        async with sessions.begin() as session:
            report = await ChainVerificationService(
                SqlAlchemyAuditAnchorRepository(session),
                SqlAlchemyReasoningLedger(session),
            ).chain_integrity(fixture.workspace_id, fixture.session_id)
            assert report.chain_valid is True
            assert report.event_count == 2
            assert report.first_invalid_day is None
            assert len(report.anchors) == 2
            assert all(item.valid for item in report.anchors)

        await asyncio.to_thread(command.check, _alembic_config())


@req("FR-807", "NFR-006")
async def test_chain_integrity_detects_an_altered_day_head() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "audit-tamper")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            await ledger.append(_ledger_append(fixture, uuid4(), "day-one"))
        async with sessions.begin() as session:
            service = ChainVerificationService(
                SqlAlchemyAuditAnchorRepository(session),
                SqlAlchemyReasoningLedger(session),
            )
            await service.publish_daily_anchor(
                fixture.workspace_id, fixture.session_id, anchor_day=DAY1.date()
            )

        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE reasoning_events DISABLE TRIGGER USER"))
            await connection.execute(
                text(
                    "UPDATE reasoning_events SET event_hash = :event_hash "
                    "WHERE session_id = :session_id"
                ),
                {"event_hash": "sha256:" + "d" * 64, "session_id": fixture.session_id},
            )
            await connection.execute(text("ALTER TABLE reasoning_events ENABLE TRIGGER USER"))

        async with sessions.begin() as session:
            report = await ChainVerificationService(
                SqlAlchemyAuditAnchorRepository(session),
                SqlAlchemyReasoningLedger(session),
            ).chain_integrity(fixture.workspace_id, fixture.session_id)

        assert report.chain_valid is False
        assert report.ledger_verification.valid is False
        assert report.first_invalid_day == DAY1.date()
        invalid = next(item for item in report.anchors if not item.valid)
        assert invalid.anchor.anchor_day == DAY1.date()
        assert invalid.reason is not None


async def _insert_access_log_as_role(
    engine: AsyncEngine,
    *,
    role: str,
    current_workspace_id: UUID,
    fixture: TenantFixture,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"SET ROLE {role}"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(current_workspace_id)},
        )
        await connection.execute(
            text(
                "INSERT INTO access_log ("
                "id, workspace_id, session_id, principal_class, principal_id, "
                "resource_kind, resource_id, action, result, scope_ids, trace_id, "
                "recorded_at"
                ") VALUES ("
                ":id, :workspace_id, :session_id, 'HUMAN', :principal_id, "
                "'RECOMMENDATION', :resource_id, 'READ', 'ALLOWED', "
                "CAST(:scope_ids AS jsonb), :trace_id, :recorded_at)"
            ),
            {
                "id": uuid4(),
                "workspace_id": fixture.workspace_id,
                "session_id": fixture.session_id,
                "principal_id": fixture.user_id,
                "resource_id": fixture.objective_id,
                "scope_ids": json.dumps([]),
                "trace_id": "trace-cross-tenant",
                "recorded_at": DAY1,
            },
        )


@req("FR-807", "NFR-006")
async def test_forced_rls_isolates_audit_tables_across_tenants() -> None:
    role = "agora_t306_app"
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "audit-rls-a")
            second = await _insert_session_graph(connection, "audit-rls-b")
            await _insert_access_log_row(
                connection,
                workspace_id=first.workspace_id,
                session_id=first.session_id,
                resource_id=first.objective_id,
            )
            await _insert_access_log_row(
                connection,
                workspace_id=second.workspace_id,
                session_id=second.session_id,
                resource_id=second.objective_id,
            )
            rows = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = ANY(:tables) ORDER BY relname"
                ),
                {"tables": ["access_log", "audit_anchors"]},
            )
            assert [tuple(row) for row in rows] == [
                ("access_log", True, True),
                ("audit_anchors", True, True),
            ]
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(
                text(f"GRANT SELECT, INSERT ON access_log, audit_anchors TO {role}")
            )

        async with engine.begin() as connection:
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first.workspace_id)},
            )
            assert await connection.scalar(text("SELECT count(*) FROM access_log")) == 1

        with pytest.raises(DBAPIError, match="row-level security policy") as cross_tenant:
            await _insert_access_log_as_role(
                engine,
                role=role,
                current_workspace_id=first.workspace_id,
                fixture=second,
            )
        assert getattr(cross_tenant.value.orig, "sqlstate", None) == "42501"
