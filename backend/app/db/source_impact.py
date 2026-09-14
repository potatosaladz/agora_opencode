"""PostgreSQL source-impact traversal and atomic retraction publication."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.citations import SqlAlchemyCitationRepository
from app.db.models.source_impact import (
    ImpactReportDependencyRow,
    ImpactReportRow,
    WorkspaceEventOutboxRow,
)
from app.domain.citations import CitationError, EvidenceCitation, SourceRetractionCommand
from app.domain.reasoning import ArtifactKind
from app.domain.reasoning_graph import GraphNode, ReasoningGraphStore
from app.domain.source_impact import (
    ImpactAnalysisResult,
    ImpactAnalysisStatus,
    ImpactDependency,
    ImpactDependencyType,
    SourceImpactReport,
    SourceImpactRepository,
)

__all__ = ["SqlAlchemySourceImpactRepository"]


# trace: FR-408
class SqlAlchemySourceImpactRepository:
    def __init__(self, session: AsyncSession, graph: ReasoningGraphStore) -> None:
        self._session = session
        self.graph = graph

    async def lock_source_for_analysis(self, workspace_id: UUID, source_id: UUID) -> None:
        locked = await self._session.scalar(
            text(
                "SELECT id FROM sources WHERE workspace_id = :workspace_id AND id = :source_id "
                "AND status <> 'RETRACTED' FOR UPDATE"
            ),
            {"workspace_id": workspace_id, "source_id": source_id},
        )
        if locked is None:
            raise CitationError("source does not exist or is already retracted")

    async def citation_roots(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]:
        return await SqlAlchemyCitationRepository(self._session).dependencies(
            workspace_id, source_id
        )

    async def downstream_records(
        self, workspace_id: UUID, artifacts: tuple[ImpactDependency, ...]
    ) -> tuple[ImpactDependency, ...]:
        if not artifacts:
            return ()
        metrics: dict[tuple[UUID, UUID], tuple[int, int, Decimal]] = {}
        for artifact in artifacts:
            key = (artifact.dependent_id, artifact.root_evidence_id)
            current = metrics.get(key)
            metrics[key] = (
                artifact.min_depth if current is None else min(current[0], artifact.min_depth),
                artifact.path_count if current is None else current[1] + artifact.path_count,
                artifact.evidence_weight
                if current is None
                else current[2] + artifact.evidence_weight,
            )
        rows = (
            await self._session.execute(
                text(
                    "SELECT 'CONSENSUS_RESULT' AS dependency_type, c.id AS dependent_id, "
                    "c.session_id, array_remove(array_append(c.pareto_set, "
                    "c.selected_alternative_id), NULL) AS artifact_ids FROM consensus_results c "
                    "WHERE c.workspace_id = :workspace_id AND "
                    "(c.selected_alternative_id = ANY(CAST(:ids AS uuid[])) "
                    "OR c.pareto_set && CAST(:ids AS uuid[])) "
                    "UNION ALL SELECT 'RECOMMENDATION', r.id, r.session_id, "
                    "array_remove(array_append(c.pareto_set, c.selected_alternative_id), NULL) "
                    "FROM recommendations r JOIN consensus_results c "
                    "ON c.workspace_id = r.workspace_id AND c.id = r.consensus_id "
                    "WHERE r.workspace_id = :workspace_id AND "
                    "(c.selected_alternative_id = ANY(CAST(:ids AS uuid[])) "
                    "OR c.pareto_set && CAST(:ids AS uuid[])) "
                    "ORDER BY dependency_type, dependent_id"
                ),
                {
                    "workspace_id": workspace_id,
                    "ids": list({artifact_id for artifact_id, _ in metrics}),
                },
            )
        ).mappings()
        aggregate: dict[
            tuple[ImpactDependencyType, UUID, UUID], tuple[UUID, int, int, Decimal]
        ] = {}
        for row in rows:
            dependency_type = ImpactDependencyType(row["dependency_type"])
            increment = 1 if dependency_type is ImpactDependencyType.CONSENSUS_RESULT else 2
            for (artifact_id, root_evidence_id), (depth, paths, weight) in metrics.items():
                if artifact_id not in row["artifact_ids"]:
                    continue
                dependency_key = (dependency_type, row["dependent_id"], root_evidence_id)
                dependency = aggregate.get(dependency_key)
                aggregate[dependency_key] = (
                    row["session_id"],
                    depth + increment
                    if dependency is None
                    else min(dependency[1], depth + increment),
                    paths if dependency is None else dependency[2] + paths,
                    weight if dependency is None else dependency[3] + weight,
                )
        return tuple(
            ImpactDependency(
                dependency_type=dependency_type,
                dependent_id=dependent_id,
                session_id=session_id,
                root_evidence_id=root_evidence_id,
                min_depth=depth,
                path_count=paths,
                evidence_weight=weight,
            )
            for (
                dependency_type,
                dependent_id,
                root_evidence_id,
            ), (session_id, depth, paths, weight) in sorted(
                aggregate.items(),
                key=lambda item: (item[0][0].value, item[1][1], str(item[0][1]), str(item[0][2])),
            )
        )

    async def artifact_dependencies(
        self,
        workspace_id: UUID,
        reached: tuple[tuple[GraphNode, UUID, int, int], ...],
    ) -> tuple[ImpactDependency, ...]:
        if not reached:
            return ()
        metrics = {
            (node.ref_id, root_evidence_id): (node, depth, paths)
            for node, root_evidence_id, depth, paths in reached
        }
        rows = (
            await self._session.execute(
                text(
                    "SELECT id, session_id, kind, logical_id, version "
                    "FROM reasoning_artifacts WHERE workspace_id = :workspace_id "
                    "AND id = ANY(CAST(:ids AS uuid[])) ORDER BY id"
                ),
                {
                    "workspace_id": workspace_id,
                    "ids": list({artifact_id for artifact_id, _ in metrics}),
                },
            )
        ).mappings()
        artifacts = {row["id"]: row for row in rows}
        return tuple(
            ImpactDependency(
                dependency_type=ImpactDependencyType.ARTIFACT,
                dependent_id=artifact_id,
                session_id=artifacts[artifact_id]["session_id"],
                root_evidence_id=root_evidence_id,
                artifact_kind=ArtifactKind(artifacts[artifact_id]["kind"]),
                logical_id=artifacts[artifact_id]["logical_id"],
                artifact_version=artifacts[artifact_id]["version"],
                min_depth=depth,
                path_count=paths,
                evidence_weight=Decimal(1),
            )
            for (artifact_id, root_evidence_id), (_, depth, paths) in sorted(
                metrics.items(), key=lambda item: (item[1][1], str(item[0][0]), str(item[0][1]))
            )
            if artifact_id in artifacts
        )

    async def retract_and_report(
        self,
        command: SourceRetractionCommand,
        *,
        report_id: UUID,
        event_id: UUID,
        correlation_id: UUID,
        analysis: ImpactAnalysisResult,
    ) -> SourceImpactReport:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"source-retraction:{command.workspace_id}:{command.source_id}"},
        )
        existing = await self._session.scalar(
            select(ImpactReportRow).where(
                ImpactReportRow.workspace_id == command.workspace_id,
                ImpactReportRow.source_id == command.source_id,
            )
        )
        if existing is not None:
            if existing.actor_id != command.actor_id or existing.reason != command.reason:
                raise CitationError("source was already retracted with different command content")
            report = await self.get_report(command.workspace_id, existing.id)
            assert report is not None
            return report

        retraction = await SqlAlchemyCitationRepository(self._session).retract_source(command)
        self._session.add(
            ImpactReportRow(
                id=report_id,
                workspace_id=command.workspace_id,
                source_id=command.source_id,
                retraction_id=retraction.retraction_id,
                event_id=event_id,
                actor_id=command.actor_id,
                reason=command.reason,
                generated_at=command.retracted_at,
                analysis_status=analysis.status.value,
                complete=analysis.complete,
                truncated=analysis.truncated,
                error=analysis.error,
            )
        )
        await self._session.flush()
        for dependency in analysis.dependencies:
            self._session.add(
                ImpactReportDependencyRow(
                    workspace_id=command.workspace_id,
                    report_id=report_id,
                    **dependency.model_dump(mode="python"),
                )
            )
        report = SourceImpactReport(
            report_id=report_id,
            retraction_id=retraction.retraction_id,
            event_id=event_id,
            workspace_id=command.workspace_id,
            source_id=command.source_id,
            actor_id=command.actor_id,
            reason=command.reason,
            generated_at=command.retracted_at,
            analysis_status=analysis.status,
            complete=analysis.complete,
            truncated=analysis.truncated,
            error=analysis.error,
            dependencies=analysis.dependencies,
        )
        self._session.add(
            WorkspaceEventOutboxRow(
                id=event_id,
                workspace_id=command.workspace_id,
                event_type="SOURCE_RETRACTED",
                payload_schema_version=1,
                correlation_id=correlation_id,
                actor_id=command.actor_id,
                payload=report.model_dump(mode="json"),
                recorded_at=command.retracted_at,
            )
        )
        await self._session.flush()
        return report

    async def get_report(self, workspace_id: UUID, report_id: UUID) -> SourceImpactReport | None:
        row = await self._session.scalar(
            select(ImpactReportRow).where(
                ImpactReportRow.workspace_id == workspace_id,
                ImpactReportRow.id == report_id,
            )
        )
        if row is None:
            return None
        dependency_rows = (
            await self._session.scalars(
                select(ImpactReportDependencyRow)
                .where(
                    ImpactReportDependencyRow.workspace_id == workspace_id,
                    ImpactReportDependencyRow.report_id == report_id,
                )
                .order_by(
                    ImpactReportDependencyRow.dependency_type,
                    ImpactReportDependencyRow.min_depth,
                    ImpactReportDependencyRow.dependent_id,
                )
            )
        ).all()
        return SourceImpactReport(
            report_id=row.id,
            retraction_id=row.retraction_id,
            event_id=row.event_id,
            workspace_id=row.workspace_id,
            source_id=row.source_id,
            actor_id=row.actor_id,
            reason=row.reason,
            generated_at=row.generated_at,
            analysis_status=ImpactAnalysisStatus(row.analysis_status),
            complete=row.complete,
            truncated=row.truncated,
            error=row.error,
            dependencies=tuple(
                ImpactDependency(
                    dependency_type=ImpactDependencyType(item.dependency_type),
                    dependent_id=item.dependent_id,
                    session_id=item.session_id,
                    root_evidence_id=item.root_evidence_id,
                    artifact_kind=ArtifactKind(item.artifact_kind) if item.artifact_kind else None,
                    logical_id=item.logical_id,
                    artifact_version=item.artifact_version,
                    min_depth=item.min_depth,
                    path_count=item.path_count,
                    evidence_weight=item.evidence_weight,
                )
                for item in dependency_rows
            ),
        )


_SOURCE_IMPACT_PORT: type[SourceImpactRepository] = SqlAlchemySourceImpactRepository
