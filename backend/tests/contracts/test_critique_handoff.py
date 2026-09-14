"""T7-07 contract for complete Critique handoff reads without omission controls."""

from __future__ import annotations

from inspect import signature
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.db.critique_handoff import SqlAlchemyCritiqueExplanationHandoffReader
from app.domain.critique_handoff import (
    CritiqueExplanationHandoff,
    CritiqueExplanationHandoffReader,
    CritiqueHandoffEmptyReason,
)
from tests.traceability import req

pytestmark = pytest.mark.contract

U = tuple(UUID(f"018fb000-0000-7000-8000-{value:012d}") for value in range(1, 3))


@req("FR-504")
def test_fr504_no_omit_parameter_exists_on_handoff_read_port() -> None:
    assert tuple(signature(CritiqueExplanationHandoffReader.read).parameters) == (
        "self",
        "workspace_id",
        "session_id",
    )
    assert isinstance(
        SqlAlchemyCritiqueExplanationHandoffReader(AsyncMock()),
        CritiqueExplanationHandoffReader,
    )


@req("FR-504")
def test_empty_handoff_serializes_an_explicit_reason() -> None:
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[0],
        session_id=U[1],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN,
    )

    assert handoff.model_dump(mode="json") == {
        "workspace_id": str(U[0]),
        "session_id": str(U[1]),
        "entries": [],
        "empty_reason": "NO_COMPLETED_CRITIC_RUN",
        "schema_version": 1,
    }
