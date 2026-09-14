"""Application services for human evidence attachment and source retraction."""

from __future__ import annotations

from uuid import UUID

from app.domain.citations import (
    CitationRepository,
    CitationResolution,
    EvidenceCitation,
    ManualEvidenceCitation,
    SourceRetraction,
    SourceRetractionCommand,
)

__all__ = ["CitationService"]


class CitationService:
    """Coordinate strict citation operations inside a caller-owned transaction."""

    def __init__(self, repository: CitationRepository) -> None:
        self._repository = repository

    async def attach_manual(self, command: ManualEvidenceCitation) -> EvidenceCitation:
        return await self._repository.attach_manual(command)

    async def resolve(self, workspace_id: UUID, citation_id: UUID) -> CitationResolution | None:
        return await self._repository.resolve(workspace_id, citation_id)

    async def retract_source(self, command: SourceRetractionCommand) -> SourceRetraction:
        return await self._repository.retract_source(command)

    async def dependencies(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]:
        return await self._repository.dependencies(workspace_id, source_id)
