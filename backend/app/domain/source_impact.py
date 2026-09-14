"""Workspace-wide source-impact analysis and immutable report contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.citations import EvidenceCitation, SourceRetractionCommand
from app.domain.reasoning import ArtifactKind
from app.domain.reasoning_graph import GraphNode, ReasoningGraphStore

__all__ = [
    "ImpactAnalysisResult",
    "ImpactAnalysisStatus",
    "ImpactDependency",
    "ImpactDependencyType",
    "SourceImpactReport",
    "SourceImpactRepository",
]


# trace: FR-408
class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class ImpactDependencyType(StrEnum):
    ARTIFACT = "ARTIFACT"
    CONSENSUS_RESULT = "CONSENSUS_RESULT"
    RECOMMENDATION = "RECOMMENDATION"


class ImpactAnalysisStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ImpactDependency(_FrozenModel):
    """One immutable report-time dependency snapshot."""

    dependency_type: ImpactDependencyType
    dependent_id: UUID
    session_id: UUID
    root_evidence_id: UUID
    artifact_kind: ArtifactKind | None = None
    logical_id: UUID | None = None
    artifact_version: int | None = Field(default=None, ge=1)
    min_depth: int = Field(ge=0)
    path_count: int = Field(ge=1)
    evidence_weight: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def exact_artifact_snapshot(self) -> ImpactDependency:
        snapshot = (self.artifact_kind, self.logical_id, self.artifact_version)
        if self.dependency_type is ImpactDependencyType.ARTIFACT and any(
            value is None for value in snapshot
        ):
            raise ValueError("artifact dependencies require kind, logical id, and version")
        if self.dependency_type is not ImpactDependencyType.ARTIFACT and any(
            value is not None for value in snapshot
        ):
            raise ValueError("non-artifact dependencies cannot include an artifact snapshot")
        return self


class ImpactAnalysisResult(_FrozenModel):
    status: ImpactAnalysisStatus
    complete: bool
    truncated: bool
    dependencies: tuple[ImpactDependency, ...]
    error: str | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> ImpactAnalysisResult:
        if self.complete is not (self.status is ImpactAnalysisStatus.COMPLETE):
            raise ValueError("complete must match analysis status")
        if self.truncated is self.complete:
            raise ValueError("truncated must be the inverse of complete")
        if self.complete and self.error is not None:
            raise ValueError("complete analysis cannot include an error")
        return self


class SourceImpactReport(_FrozenModel):
    report_id: UUID
    retraction_id: UUID
    event_id: UUID
    workspace_id: UUID
    source_id: UUID
    actor_id: UUID
    reason: str = Field(min_length=1)
    generated_at: datetime
    analysis_status: ImpactAnalysisStatus
    complete: bool
    truncated: bool
    error: str | None = None
    dependencies: tuple[ImpactDependency, ...]

    _generated_at = field_validator("generated_at")(_aware)

    @model_validator(mode="after")
    def consistent_status(self) -> SourceImpactReport:
        if self.complete is not (self.analysis_status is ImpactAnalysisStatus.COMPLETE):
            raise ValueError("complete must match analysis status")
        if self.truncated is self.complete:
            raise ValueError("truncated must be the inverse of complete")
        if self.complete and self.error is not None:
            raise ValueError("complete report cannot include an error")
        return self

    @property
    def affected_claim_ids(self) -> tuple[UUID, ...]:
        return tuple(
            dict.fromkeys(
                item.dependent_id
                for item in self.dependencies
                if item.dependency_type is ImpactDependencyType.ARTIFACT
                and item.artifact_kind is ArtifactKind.CLAIM
            )
        )

    @property
    def affected_alternative_ids(self) -> tuple[UUID, ...]:
        return tuple(
            dict.fromkeys(
                item.dependent_id
                for item in self.dependencies
                if item.dependency_type is ImpactDependencyType.ARTIFACT
                and item.artifact_kind is ArtifactKind.ALTERNATIVE
            )
        )

    @property
    def affected_consensus_result_ids(self) -> tuple[UUID, ...]:
        return tuple(
            dict.fromkeys(
                item.dependent_id
                for item in self.dependencies
                if item.dependency_type is ImpactDependencyType.CONSENSUS_RESULT
            )
        )

    @property
    def affected_recommendation_ids(self) -> tuple[UUID, ...]:
        return tuple(
            dict.fromkeys(
                item.dependent_id
                for item in self.dependencies
                if item.dependency_type is ImpactDependencyType.RECOMMENDATION
            )
        )


@runtime_checkable
class SourceImpactRepository(Protocol):
    """Caller-transaction-scoped source-impact persistence."""

    graph: ReasoningGraphStore

    async def lock_source_for_analysis(self, workspace_id: UUID, source_id: UUID) -> None: ...

    async def retract_and_report(
        self,
        command: SourceRetractionCommand,
        *,
        report_id: UUID,
        event_id: UUID,
        correlation_id: UUID,
        analysis: ImpactAnalysisResult,
    ) -> SourceImpactReport: ...

    async def get_report(
        self, workspace_id: UUID, report_id: UUID
    ) -> SourceImpactReport | None: ...

    async def citation_roots(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]: ...

    async def downstream_records(
        self,
        workspace_id: UUID,
        artifacts: tuple[ImpactDependency, ...],
    ) -> tuple[ImpactDependency, ...]: ...

    async def artifact_dependencies(
        self,
        workspace_id: UUID,
        reached: tuple[tuple[GraphNode, UUID, int, int], ...],
    ) -> tuple[ImpactDependency, ...]: ...


@runtime_checkable
class SourceImpactAnalyzer(Protocol):
    """Workspace-wide orchestration over the bounded T10-01 graph traversal."""

    graph: ReasoningGraphStore

    async def impact_of(self, workspace_id: UUID, source_id: UUID) -> ImpactAnalysisResult: ...
