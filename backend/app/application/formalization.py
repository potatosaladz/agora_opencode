"""Caller-transaction-owned T11-01 formalization lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.formalization import (
    FormalizationDecision,
    FormalizationDecisionKind,
    FormalizationError,
    FormalizationRepository,
    FormalizationRevision,
    FormalizationStatus,
    FormalizationValidation,
    derive_status,
    validate_revision,
)

__all__ = ["FormalizationContext", "FormalizationLifecycleService", "FormalizationResult"]


@dataclass(frozen=True, slots=True)
class FormalizationContext:
    actor_id: UUID
    correlation_id: UUID
    occurred_at: datetime
    event_id: UUID


@dataclass(frozen=True, slots=True)
class FormalizationResult:
    revision: FormalizationRevision
    validation: FormalizationValidation | None
    decision: FormalizationDecision | None
    status: FormalizationStatus

    @property
    def enforceable(self) -> bool:
        return self.status is FormalizationStatus.VALIDATED


# trace: FR-707
class FormalizationLifecycleService:
    def __init__(self, repository: FormalizationRepository) -> None:
        self._repository = repository

    async def get(
        self, workspace_id: UUID, logical_id: UUID, *, revision: int | None = None
    ) -> FormalizationResult | None:
        value = await self._repository.revision(workspace_id, logical_id, revision)
        return await self._result(value) if value is not None else None

    async def create(
        self, revision: FormalizationRevision, *, context: FormalizationContext
    ) -> FormalizationResult:
        if revision.revision != 1 or revision.logical_id != revision.id:
            raise FormalizationError(
                "a new formalization must begin at revision 1 with logical id equal to id"
            )
        await self._repository.verify_artifacts(revision)
        await self._repository.add_revision(revision)
        await self._repository.add_event(
            event_id=context.event_id,
            event_type="FORMALIZATION_CREATED",
            revision=revision,
            status=FormalizationStatus.CANDIDATE,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            recorded_at=context.occurred_at,
        )
        return FormalizationResult(revision, None, None, FormalizationStatus.CANDIDATE)

    async def revise(
        self,
        revision: FormalizationRevision,
        *,
        expected_revision: int,
        context: FormalizationContext,
    ) -> FormalizationResult:
        head = await self._repository.head(
            revision.workspace_id, revision.logical_id, for_update=True
        )
        if head is None:
            raise FormalizationError("formalization does not exist")
        if head.revision != expected_revision:
            raise FormalizationError(
                f"stale formalization revision; current revision is {head.revision}"
            )
        if revision.revision != head.revision + 1 or revision.supersedes_id != head.id:
            raise FormalizationError("revision must directly supersede the current head")
        if revision.source_artifact_logical_id != head.source_artifact_logical_id:
            raise FormalizationError("source artifact lineage cannot change")
        await self._repository.verify_artifacts(revision)
        await self._repository.add_revision(revision)
        await self._repository.add_event(
            event_id=context.event_id,
            event_type="FORMALIZATION_REVISED",
            revision=revision,
            status=FormalizationStatus.CANDIDATE,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            recorded_at=context.occurred_at,
        )
        return FormalizationResult(revision, None, None, FormalizationStatus.CANDIDATE)

    async def validate(
        self,
        workspace_id: UUID,
        logical_id: UUID,
        *,
        expected_revision: int,
        validation_id: UUID,
        context: FormalizationContext,
    ) -> FormalizationResult:
        revision = await self._current(workspace_id, logical_id, expected_revision)
        existing = await self._repository.validation(workspace_id, revision.id)
        if existing is not None:
            return await self._result(revision)
        validation = validate_revision(revision).model_copy(
            update={
                "id": validation_id,
                "validated_at": context.occurred_at,
                "actor_id": context.actor_id,
                "correlation_id": context.correlation_id,
            }
        )
        await self._repository.add_validation(validation)
        status = derive_status(validation, None)
        await self._repository.add_event(
            event_id=context.event_id,
            event_type="FORMALIZATION_VALIDATION_RECORDED",
            revision=revision,
            status=status,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            recorded_at=context.occurred_at,
        )
        return FormalizationResult(revision, validation, None, status)

    async def decide(
        self,
        workspace_id: UUID,
        logical_id: UUID,
        *,
        expected_revision: int,
        decision_id: UUID,
        kind: FormalizationDecisionKind,
        reason: str,
        context: FormalizationContext,
    ) -> FormalizationResult:
        revision = await self._current(workspace_id, logical_id, expected_revision)
        validation = await self._repository.validation(workspace_id, revision.id)
        previous = await self._repository.decision(workspace_id, revision.id)
        if previous is not None:
            raise FormalizationError("a human decision already exists for this revision")
        if kind is FormalizationDecisionKind.CONFIRMED and (
            validation is None or not validation.success
        ):
            raise FormalizationError("confirmation requires successful deterministic validation")
        decision = FormalizationDecision(
            id=decision_id,
            workspace_id=workspace_id,
            formalization_revision_id=revision.id,
            ast_hash=revision.ast_hash,
            kind=kind,
            reason=reason,
            decided_at=context.occurred_at,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
        )
        await self._repository.add_decision(decision)
        status = derive_status(validation, decision)
        await self._repository.add_event(
            event_id=context.event_id,
            event_type=(
                "FORMALIZATION_CONFIRMED"
                if kind is FormalizationDecisionKind.CONFIRMED
                else "FORMALIZATION_REJECTED"
            ),
            revision=revision,
            status=status,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            recorded_at=context.occurred_at,
        )
        return FormalizationResult(revision, validation, decision, status)

    async def _current(
        self, workspace_id: UUID, logical_id: UUID, expected: int
    ) -> FormalizationRevision:
        head = await self._repository.head(workspace_id, logical_id, for_update=True)
        if head is None:
            raise FormalizationError("formalization does not exist")
        if head.revision != expected:
            raise FormalizationError(
                f"stale formalization revision; current revision is {head.revision}"
            )
        return head

    async def _result(self, revision: FormalizationRevision) -> FormalizationResult:
        validation = await self._repository.validation(revision.workspace_id, revision.id)
        decision = await self._repository.decision(revision.workspace_id, revision.id)
        return FormalizationResult(
            revision, validation, decision, derive_status(validation, decision)
        )
