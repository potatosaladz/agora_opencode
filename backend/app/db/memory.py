"""PostgreSQL-backed validated semantic memory promotions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.memory import (
    ArtifactRef,
    MemoryEntry,
    MemoryError,
    MemoryLifecycleCommand,
    MemoryProvider,
    MemoryQuery,
    MemoryResult,
    MemoryScope,
    MemoryState,
    MemoryTier,
    PromotionCommand,
    RetentionPolicy,
    ValidationRecord,
)

__all__ = ["SqlAlchemyMemoryProvider"]


# trace: FR-406
class SqlAlchemyMemoryProvider(MemoryProvider):
    """Keep semantic truth behind promotion; reconstruct lifecycle without mutation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(self, scope: MemoryScope, entry: MemoryEntry) -> MemoryEntry:
        del entry
        if scope.tier is MemoryTier.SEMANTIC:
            raise MemoryError("direct semantic writes are forbidden; use promote")
        raise MemoryError(f"{scope.tier.value} memory is owned by its authoritative subsystem")

    async def promote(
        self, source: ArtifactRef, target: MemoryScope, validation: ValidationRecord
    ) -> MemoryEntry:
        if target.tier is not MemoryTier.SEMANTIC or target.namespace_id is None:
            raise MemoryError("promotion target must be explicit SEMANTIC memory")
        if source.workspace_id != target.workspace_id:
            raise MemoryError("promotion source and target workspace must match")
        command = PromotionCommand(
            entry_id=source.entry_id,
            promotion_id=source.promotion_id,
            workspace_id=source.workspace_id,
            source_session_id=source.session_id,
            source_artifact_id=source.artifact_id,
            target_namespace_id=target.namespace_id,
            validator_class=validation.validator_class,
            validator_id=validation.validator_id,
            second_validator_id=validation.second_validator_id,
            evidence_artifact_ids=validation.evidence_artifact_ids,
            justification=validation.justification,
            caveats=validation.caveats,
            promoted_at=validation.validated_at,
            review_by=validation.review_by,
            supersedes_entry_id=source.supersedes_entry_id,
        )
        return await self._promote(command)

    async def _promote(self, command: PromotionCommand) -> MemoryEntry:
        values = dict(command.model_dump())
        row = (
            (
                await self._session.execute(
                    text("""
                SELECT a.kind, a.content_hash, a.status, n.tier,
                       EXISTS (
                           SELECT 1 FROM workspace_members m
                           JOIN users u ON u.id = m.user_id
                           WHERE m.workspace_id = :workspace_id
                             AND m.user_id = :validator_id AND u.is_active
                       ) AS validator_active,
                       CASE WHEN CAST(:second_validator_id AS uuid) IS NULL THEN false ELSE EXISTS (
                           SELECT 1 FROM workspace_members m
                           JOIN users u ON u.id = m.user_id
                           WHERE m.workspace_id = :workspace_id
                             AND m.user_id = :second_validator_id AND u.is_active
                       ) END AS second_validator_active
                FROM reasoning_artifacts a
                JOIN knowledge_namespaces n
                  ON n.workspace_id = a.workspace_id AND n.id = :target_namespace_id
                WHERE a.workspace_id = :workspace_id AND a.session_id = :source_session_id
                  AND a.id = :source_artifact_id
            """),
                    values,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise MemoryError("source artifact or target namespace does not exist in workspace")
        if row["tier"] not in {"HISTORICAL", "GLOBAL"}:
            raise MemoryError("semantic promotions require a HISTORICAL or GLOBAL namespace")
        if row["status"] != "ACTIVE":
            raise MemoryError("source artifact must be ACTIVE")
        if not row["validator_active"]:
            raise MemoryError("validator must be an active workspace member")
        if row["tier"] == "GLOBAL" and command.second_validator_id is None:
            raise MemoryError("GLOBAL promotion requires an independent second validator")
        if command.second_validator_id is not None and not row["second_validator_active"]:
            raise MemoryError("second validator must be an active workspace member")

        evidence_rows = (
            (
                await self._session.execute(
                    text("""
                SELECT id, kind, status FROM reasoning_artifacts
                WHERE workspace_id = :workspace_id AND session_id = :source_session_id
                  AND id = ANY(CAST(:evidence_ids AS uuid[]))
                ORDER BY id
            """),
                    {**values, "evidence_ids": list(command.evidence_artifact_ids)},
                )
            )
            .mappings()
            .all()
        )
        if len(evidence_rows) != len(command.evidence_artifact_ids):
            raise MemoryError("every promotion evidence artifact must exist in the source session")
        if any(item["kind"] != "EVIDENCE" or item["status"] != "ACTIVE" for item in evidence_rows):
            raise MemoryError("promotion evidence must contain only ACTIVE EVIDENCE artifacts")

        version = 1
        if command.supersedes_entry_id is not None:
            predecessor = (
                (
                    await self._session.execute(
                        text("""
                    SELECT version, namespace_id FROM semantic_memory_entries
                    WHERE workspace_id = :workspace_id AND id = :supersedes_entry_id
                    FOR SHARE
                """),
                        values,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if predecessor is None or predecessor["namespace_id"] != command.target_namespace_id:
                raise MemoryError("superseded entry must exist in target namespace")
            version = int(predecessor["version"]) + 1

        try:
            await self._session.execute(
                text("""
                INSERT INTO semantic_memory_entries
                    (id, workspace_id, namespace_id, source_session_id, source_artifact_id,
                     source_artifact_kind, source_content_hash, version,
                     supersedes_entry_id, promoted_at)
                VALUES
                    (:entry_id, :workspace_id, :target_namespace_id, :source_session_id,
                     :source_artifact_id, :kind, :content_hash, :version, :supersedes_entry_id,
                     :promoted_at)
            """),
                {
                    **values,
                    "kind": row["kind"],
                    "content_hash": row["content_hash"],
                    "version": version,
                },
            )
            await self._session.execute(
                text("""
                INSERT INTO memory_promotions
                    (id, workspace_id, entry_id, validator_id, second_validator_id,
                     justification, caveats, promoted_at, review_by)
                VALUES
                    (:promotion_id, :workspace_id, :entry_id, :validator_id, :second_validator_id,
                     :justification, :caveats, :promoted_at, :review_by)
            """),
                values,
            )
            for evidence_id in command.evidence_artifact_ids:
                await self._session.execute(
                    text("""
                    INSERT INTO memory_promotion_evidence
                        (workspace_id, promotion_id, session_id, evidence_artifact_id)
                    VALUES (:workspace_id, :promotion_id, :source_session_id, :evidence_id)
                """),
                    {
                        **values,
                        "evidence_id": evidence_id,
                    },
                )
            await self._session.flush()
        except IntegrityError as exc:
            raise MemoryError("promotion conflicts with durable memory history") from exc

        return MemoryEntry(
            id=command.entry_id,
            workspace_id=command.workspace_id,
            namespace_id=command.target_namespace_id,
            source_session_id=command.source_session_id,
            source_artifact_id=command.source_artifact_id,
            source_artifact_kind=row["kind"],
            source_content_hash=row["content_hash"],
            version=version,
            supersedes_entry_id=command.supersedes_entry_id,
            promotion_id=command.promotion_id,
            validator_id=command.validator_id,
            second_validator_id=command.second_validator_id,
            evidence_artifact_ids=command.evidence_artifact_ids,
            justification=command.justification,
            caveats=command.caveats,
            promoted_at=command.promoted_at,
            review_by=command.review_by,
            state=MemoryState.ACTIVE,
        )

    async def read(self, scope: MemoryScope, query: MemoryQuery) -> MemoryResult:
        if scope.tier is not MemoryTier.SEMANTIC or scope.namespace_id is None:
            raise MemoryError("provider reads require explicit SEMANTIC memory")
        entry = await self._read(scope.workspace_id, query.entry_id, as_of=query.as_of)
        if entry is None or entry.namespace_id != scope.namespace_id:
            return MemoryResult(entries=())
        return MemoryResult(entries=(entry,))

    async def _read(
        self, workspace_id: UUID, entry_id: UUID, *, as_of: datetime
    ) -> MemoryEntry | None:
        row = (
            (
                await self._session.execute(
                    text("""
            SELECT e.*, p.id AS promotion_id, p.validator_id, p.second_validator_id,
                   p.justification, p.caveats, p.review_by,
                   COALESCE((
                       SELECT l.state FROM memory_lifecycle_events l
                       WHERE l.workspace_id = e.workspace_id AND l.entry_id = e.id
                         AND l.recorded_at <= :as_of
                       ORDER BY l.recorded_at DESC, l.id DESC LIMIT 1
                   ), CASE WHEN p.review_by IS NOT NULL AND p.review_by <= :as_of
                           THEN 'STALE' ELSE 'ACTIVE' END) AS state
            FROM semantic_memory_entries e
            JOIN memory_promotions p ON p.workspace_id = e.workspace_id AND p.entry_id = e.id
            WHERE e.workspace_id = :workspace_id AND e.id = :entry_id AND e.promoted_at <= :as_of
        """),
                    {"workspace_id": workspace_id, "entry_id": entry_id, "as_of": as_of},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        evidence = (
            (
                await self._session.execute(
                    text("""
            SELECT evidence_artifact_id FROM memory_promotion_evidence
            WHERE workspace_id = :workspace_id AND promotion_id = :promotion_id
            ORDER BY evidence_artifact_id
        """),
                    {"workspace_id": workspace_id, "promotion_id": row["promotion_id"]},
                )
            )
            .scalars()
            .all()
        )
        return MemoryEntry(
            id=row["id"],
            workspace_id=row["workspace_id"],
            namespace_id=row["namespace_id"],
            source_session_id=row["source_session_id"],
            source_artifact_id=row["source_artifact_id"],
            source_artifact_kind=row["source_artifact_kind"],
            source_content_hash=row["source_content_hash"],
            version=row["version"],
            supersedes_entry_id=row["supersedes_entry_id"],
            promotion_id=row["promotion_id"],
            validator_id=row["validator_id"],
            second_validator_id=row["second_validator_id"],
            evidence_artifact_ids=tuple(evidence),
            justification=row["justification"],
            caveats=tuple(row["caveats"]),
            promoted_at=row["promoted_at"],
            review_by=row["review_by"],
            state=MemoryState(row["state"]),
        )

    async def expire(self, scope: MemoryScope, policy: RetentionPolicy) -> int:
        if scope.tier is not MemoryTier.SEMANTIC or scope.namespace_id is None:
            raise MemoryError("retention requires explicit SEMANTIC memory")
        command = MemoryLifecycleCommand(
            event_id=policy.event_id,
            workspace_id=scope.workspace_id,
            entry_id=policy.entry_id,
            state=policy.state,
            actor_class=policy.actor_class,
            actor_id=policy.actor_id,
            reason=policy.reason,
            recorded_at=policy.recorded_at,
        )
        current = await self._read(
            command.workspace_id, command.entry_id, as_of=command.recorded_at
        )
        if current is None:
            raise MemoryError("memory entry does not exist at lifecycle event time")
        if current.state is MemoryState.ARCHIVED:
            raise MemoryError("archived memory cannot transition")
        if current.state is command.state:
            raise MemoryError(f"memory already {command.state.value}")
        if current.namespace_id != scope.namespace_id:
            raise MemoryError("memory entry does not belong to retention scope")
        try:
            await self._session.execute(
                text("""
                INSERT INTO memory_lifecycle_events
                    (id, workspace_id, entry_id, state, actor_id, reason, recorded_at)
                VALUES (:event_id, :workspace_id, :entry_id, :state, :actor_id,
                        :reason, :recorded_at)
            """),
                {**command.model_dump(), "state": command.state.value},
            )
            await self._session.flush()
        except IntegrityError as exc:
            raise MemoryError("lifecycle event conflicts with durable memory history") from exc
        return 1
