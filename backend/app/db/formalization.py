"""PostgreSQL adapter for immutable formalization revisions and lifecycle facts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.formalization import (
    FormalizationDecisionRow,
    FormalizationRow,
    FormalizationValidationRow,
)
from app.db.models.reasoning import ReasoningArtifactRow
from app.db.models.source_impact import WorkspaceEventOutboxRow
from app.domain.formalization import (
    FormalizationDecision,
    FormalizationDecisionKind,
    FormalizationError,
    FormalizationRepository,
    FormalizationRevision,
    FormalizationStatus,
    FormalizationValidation,
    SymbolDeclaration,
    ValidationIssue,
    parse_ast,
)
from app.domain.reasoning import ActorClass, canonical_json

__all__ = ["SqlAlchemyFormalizationRepository"]


def _revision(row: FormalizationRow) -> FormalizationRevision:
    return FormalizationRevision(
        id=row.id,
        logical_id=row.logical_id,
        revision=row.revision,
        supersedes_id=row.supersedes_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        source_artifact_id=row.source_artifact_id,
        source_artifact_logical_id=row.source_artifact_logical_id,
        source_artifact_version=row.source_artifact_version,
        ast=parse_ast(row.ast),
        ast_hash=row.ast_hash,
        symbols=tuple(
            SymbolDeclaration.model_validate_json(json.dumps(item)) for item in row.symbols
        ),
        canonical_rendering=row.canonical_rendering,
        premise_artifact_ids=tuple(row.premise_artifact_ids),
        limitations=tuple(row.limitations),
        fidelity_notes=row.fidelity_notes,
        created_at=row.created_at,
        actor_class=ActorClass(row.actor_class),
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
    )


def _validation(row: FormalizationValidationRow) -> FormalizationValidation:
    return FormalizationValidation(
        id=row.id,
        workspace_id=row.workspace_id,
        formalization_revision_id=row.formalization_revision_id,
        ast_hash=row.ast_hash,
        validator_ruleset=row.validator_ruleset,
        success=row.success,
        issues=tuple(ValidationIssue.model_validate(item) for item in row.issues),
        validated_at=row.validated_at,
        actor_class=ActorClass(row.actor_class),
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
    )


def _decision(row: FormalizationDecisionRow) -> FormalizationDecision:
    return FormalizationDecision(
        id=row.id,
        workspace_id=row.workspace_id,
        formalization_revision_id=row.formalization_revision_id,
        ast_hash=row.ast_hash,
        kind=FormalizationDecisionKind(row.kind),
        reason=row.reason,
        decided_at=row.decided_at,
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
    )


# trace: FR-707
class SqlAlchemyFormalizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_revision(self, revision: FormalizationRevision) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"formalization:{revision.workspace_id}:{revision.logical_id}"},
        )
        data = revision.model_dump(mode="json")
        self._session.add(
            FormalizationRow(
                id=revision.id,
                workspace_id=revision.workspace_id,
                session_id=revision.session_id,
                logical_id=revision.logical_id,
                revision=revision.revision,
                supersedes_id=revision.supersedes_id,
                source_artifact_id=revision.source_artifact_id,
                source_artifact_logical_id=revision.source_artifact_logical_id,
                source_artifact_version=revision.source_artifact_version,
                ast=data["ast"],
                ast_canonical=canonical_json(data["ast"]).decode("utf-8"),
                ast_hash=revision.ast_hash,
                symbols=data["symbols"],
                canonical_rendering=revision.canonical_rendering,
                premise_artifact_ids=list(revision.premise_artifact_ids),
                limitations=list(revision.limitations),
                fidelity_notes=revision.fidelity_notes,
                created_at=revision.created_at,
                actor_class=revision.actor_class.value,
                actor_id=revision.actor_id,
                correlation_id=revision.correlation_id,
            )
        )
        await self._session.flush()

    async def head(
        self, workspace_id: UUID, logical_id: UUID, *, for_update: bool = False
    ) -> FormalizationRevision | None:
        query = (
            select(FormalizationRow)
            .where(
                FormalizationRow.workspace_id == workspace_id,
                FormalizationRow.logical_id == logical_id,
            )
            .order_by(FormalizationRow.revision.desc())
            .limit(1)
        )
        if for_update:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": f"formalization:{workspace_id}:{logical_id}"},
            )
            query = query.with_for_update()
        row = await self._session.scalar(query)
        return _revision(row) if row is not None else None

    async def revision(
        self, workspace_id: UUID, logical_id: UUID, revision: int | None = None
    ) -> FormalizationRevision | None:
        query = select(FormalizationRow).where(
            FormalizationRow.workspace_id == workspace_id, FormalizationRow.logical_id == logical_id
        )
        query = (
            query.where(FormalizationRow.revision == revision)
            if revision is not None
            else query.order_by(FormalizationRow.revision.desc()).limit(1)
        )
        row = await self._session.scalar(query)
        return _revision(row) if row is not None else None

    async def validation(
        self, workspace_id: UUID, revision_id: UUID
    ) -> FormalizationValidation | None:
        row = await self._session.scalar(
            select(FormalizationValidationRow).where(
                FormalizationValidationRow.workspace_id == workspace_id,
                FormalizationValidationRow.formalization_revision_id == revision_id,
            )
        )
        return _validation(row) if row is not None else None

    async def decision(self, workspace_id: UUID, revision_id: UUID) -> FormalizationDecision | None:
        row = await self._session.scalar(
            select(FormalizationDecisionRow).where(
                FormalizationDecisionRow.workspace_id == workspace_id,
                FormalizationDecisionRow.formalization_revision_id == revision_id,
            )
        )
        return _decision(row) if row is not None else None

    async def add_validation(self, validation: FormalizationValidation) -> None:
        self._session.add(
            FormalizationValidationRow(
                id=validation.id,
                workspace_id=validation.workspace_id,
                formalization_revision_id=validation.formalization_revision_id,
                ast_hash=validation.ast_hash,
                validator_ruleset=validation.validator_ruleset,
                success=validation.success,
                issues=[item.model_dump(mode="json") for item in validation.issues],
                validated_at=validation.validated_at,
                actor_class=validation.actor_class.value,
                actor_id=validation.actor_id,
                correlation_id=validation.correlation_id,
            )
        )
        await self._session.flush()

    async def add_decision(self, decision: FormalizationDecision) -> None:
        self._session.add(
            FormalizationDecisionRow(
                id=decision.id,
                workspace_id=decision.workspace_id,
                formalization_revision_id=decision.formalization_revision_id,
                ast_hash=decision.ast_hash,
                kind=decision.kind.value,
                reason=decision.reason,
                decided_at=decision.decided_at,
                actor_id=decision.actor_id,
                correlation_id=decision.correlation_id,
            )
        )
        await self._session.flush()

    async def verify_artifacts(self, revision: FormalizationRevision) -> None:
        ids = (revision.source_artifact_id, *revision.premise_artifact_ids)
        rows = list(
            (
                await self._session.scalars(
                    select(ReasoningArtifactRow).where(
                        ReasoningArtifactRow.workspace_id == revision.workspace_id,
                        ReasoningArtifactRow.session_id == revision.session_id,
                        ReasoningArtifactRow.id.in_(ids),
                    )
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        source = by_id.get(revision.source_artifact_id)
        if source is None or source.kind not in {"CLAIM", "CONSTRAINT", "PROPOSITION"}:
            raise FormalizationError(
                "source must be an existing CLAIM, CONSTRAINT, or PROPOSITION revision"
            )
        if (
            source.logical_id != revision.source_artifact_logical_id
            or source.version != revision.source_artifact_version
        ):
            raise FormalizationError(
                "source artifact lineage/version does not match the pinned revision"
            )
        if set(by_id) != set(ids):
            raise FormalizationError(
                "every premise must pin an existing artifact revision in the same session"
            )

    async def add_event(
        self,
        *,
        event_id: UUID,
        event_type: str,
        revision: FormalizationRevision,
        status: FormalizationStatus,
        actor_id: UUID,
        correlation_id: UUID,
        recorded_at: datetime,
    ) -> None:
        payload: dict[str, Any] = {
            "formalization_id": str(revision.logical_id),
            "formalization_revision_id": str(revision.id),
            "formalization_revision": revision.revision,
            "source_artifact_id": str(revision.source_artifact_id),
            "source_artifact_version": revision.source_artifact_version,
            "ast_hash": revision.ast_hash,
            "validation_status": status.value,
            "actor_class": revision.actor_class.value,
            "actor_id": str(actor_id),
            "correlation_id": str(correlation_id),
        }
        self._session.add(
            WorkspaceEventOutboxRow(
                id=event_id,
                workspace_id=revision.workspace_id,
                event_type=event_type,
                payload_schema_version=1,
                correlation_id=correlation_id,
                actor_id=actor_id,
                payload=payload,
                recorded_at=recorded_at,
                published_at=None,
            )
        )
        await self._session.flush()


_PORT: type[FormalizationRepository] = SqlAlchemyFormalizationRepository
