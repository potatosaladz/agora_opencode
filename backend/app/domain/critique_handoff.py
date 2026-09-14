"""Deterministic internal explanation handoff for Phase 7 Critique chains."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.critique import CritiqueResponseDisposition
from app.domain.reasoning import CritiqueType, FrozenModel, Resolution, Severity

__all__ = [
    "CritiqueExplanationEntry",
    "CritiqueExplanationHandoff",
    "CritiqueExplanationHandoffReader",
    "CritiqueHandoffEmptyReason",
]


# trace: FR-504
class CritiqueHandoffEmptyReason(StrEnum):
    """Why a handoff has no Critique chains to expose."""

    NO_COMPLETED_CRITIC_RUN = "NO_COMPLETED_CRITIC_RUN"
    COMPLETED_CRITIC_RUN_WITHOUT_CRITIQUES = "COMPLETED_CRITIC_RUN_WITHOUT_CRITIQUES"


class CritiqueExplanationEntry(FrozenModel):
    """Latest immutable head of one Critique logical chain."""

    critique_id: UUID
    logical_id: UUID
    version: int = Field(gt=0)
    target_artifact_id: UUID
    critique_type: CritiqueType
    severity: Severity
    resolution: Resolution
    response_disposition: CritiqueResponseDisposition | None = None
    warrant_artifact_ids: tuple[UUID, ...] = ()
    replacement_target_artifact_id: UUID | None = None
    creation_ledger_seq: int = Field(gt=0)

    @model_validator(mode="after")
    def response_matches_resolution(self) -> CritiqueExplanationEntry:
        expected_resolution = {
            CritiqueResponseDisposition.ACCEPT: Resolution.RESOLVED,
            CritiqueResponseDisposition.PARTIALLY_ACCEPT: Resolution.UNRESOLVED,
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: Resolution.DISPUTED,
            CritiqueResponseDisposition.REVISE: Resolution.RESOLVED,
            CritiqueResponseDisposition.REQUEST_EVIDENCE: Resolution.UNRESOLVED,
            CritiqueResponseDisposition.REQUEST_SIMULATION: Resolution.UNRESOLVED,
            CritiqueResponseDisposition.ABSTAIN: Resolution.UNRESOLVED,
        }
        if self.response_disposition is None:
            if self.resolution is not Resolution.OPEN:
                raise ValueError("non-OPEN Critique handoff head requires a response disposition")
        elif expected_resolution[self.response_disposition] is not self.resolution:
            raise ValueError("Critique handoff response disposition does not match resolution")
        if (
            self.response_disposition is CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION
            and not self.warrant_artifact_ids
        ):
            raise ValueError("justified rejection requires response warrants")
        if (self.response_disposition is CritiqueResponseDisposition.REVISE) != (
            self.replacement_target_artifact_id is not None
        ):
            raise ValueError("only REVISE carries a replacement target artifact")
        return self


class CritiqueExplanationHandoff(FrozenModel):
    """Complete ordered Critique-chain census or one explicit empty-state reason."""

    workspace_id: UUID
    session_id: UUID
    entries: tuple[CritiqueExplanationEntry, ...]
    empty_reason: CritiqueHandoffEmptyReason | None = None
    schema_version: int = 1

    @model_validator(mode="after")
    def complete_shape(self) -> CritiqueExplanationHandoff:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueExplanationHandoff schema_version")
        if bool(self.entries) == (self.empty_reason is not None):
            raise ValueError("handoff requires entries or exactly one empty reason")
        ordering = tuple(
            (entry.creation_ledger_seq, entry.critique_id.int) for entry in self.entries
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("Critique handoff entries are not in stable ledger/id order")
        if len({entry.logical_id for entry in self.entries}) != len(self.entries):
            raise ValueError("Critique handoff contains more than one head for a logical chain")
        return self


@runtime_checkable
class CritiqueExplanationHandoffReader(Protocol):
    """Read every latest Critique head for one tenant session without omission controls."""

    async def read(self, workspace_id: UUID, session_id: UUID) -> CritiqueExplanationHandoff: ...
