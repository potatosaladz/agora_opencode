"""T6-04 adapter contract for serialized atomic agent-proposal commits."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.domain.artifact_commit import AgentProposalStore
from app.domain.reasoning_ledger import AgentProposalLedger
from tests.traceability import req

pytestmark = pytest.mark.contract


@req("FR-210")
def test_sqlalchemy_adapters_expose_agent_proposal_atomicity_contract() -> None:
    session = AsyncMock()

    assert isinstance(SqlAlchemyReasoningArtifactStore(session), AgentProposalStore)
    assert isinstance(SqlAlchemyReasoningLedger(session), AgentProposalLedger)
