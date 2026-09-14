"""T5-08 explicit memory-tier and validated-promotion invariants (FR-405, FR-406)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.memory import SqlAlchemyMemoryProvider
from app.domain.memory import (
    MemoryError,
    MemoryLifecycleCommand,
    MemoryProvider,
    MemoryScope,
    MemoryState,
    MemoryTier,
    PromotionCommand,
    ValidationRecord,
)
from app.domain.reasoning import ActorClass
from tests.traceability import req

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


@req("FR-405", "FR-406")
def test_memory_tiers_require_explicit_distinct_scopes() -> None:
    workspace, session, namespace, agent = (uuid4() for _ in range(4))
    assert MemoryScope(workspace_id=workspace, tier=MemoryTier.WORKING, session_id=session)
    assert MemoryScope(workspace_id=workspace, tier=MemoryTier.EPISODIC, session_id=session)
    assert MemoryScope(workspace_id=workspace, tier=MemoryTier.SEMANTIC, namespace_id=namespace)
    assert MemoryScope(workspace_id=workspace, tier=MemoryTier.PROCEDURAL, agent_def_id=agent)
    with pytest.raises(ValidationError):
        MemoryScope(workspace_id=workspace, tier=MemoryTier.SEMANTIC, session_id=session)


@req("FR-405", "FR-406")
def test_promotion_requires_human_unique_evidence_and_future_review() -> None:
    evidence = uuid4()
    validator = uuid4()
    values = {
        "entry_id": uuid4(),
        "promotion_id": uuid4(),
        "workspace_id": uuid4(),
        "source_session_id": uuid4(),
        "source_artifact_id": uuid4(),
        "target_namespace_id": uuid4(),
        "validator_id": validator,
        "evidence_artifact_ids": (evidence,),
        "justification": "human review against attached evidence",
        "caveats": ("valid for current policy version",),
        "promoted_at": NOW,
        "review_by": NOW + timedelta(days=30),
    }
    assert PromotionCommand.model_validate(values).validator_class is ActorClass.HUMAN
    with pytest.raises(ValidationError):
        PromotionCommand.model_validate({**values, "validator_class": ActorClass.AGENT})
    with pytest.raises(ValidationError):
        PromotionCommand.model_validate({**values, "evidence_artifact_ids": (evidence, evidence)})
    with pytest.raises(ValidationError):
        PromotionCommand.model_validate({**values, "review_by": NOW})
    with pytest.raises(ValidationError):
        PromotionCommand.model_validate({**values, "caveats": ()})
    validation = ValidationRecord(
        validator_id=validator,
        evidence_artifact_ids=(evidence,),
        justification="human review against attached evidence",
        caveats=("valid for current policy version",),
        validated_at=NOW,
    )
    assert validation.validator_class is ActorClass.HUMAN


@req("FR-405", "FR-406")
def test_lifecycle_is_one_way_human_stale_or_archive() -> None:
    values = {
        "event_id": uuid4(),
        "workspace_id": uuid4(),
        "entry_id": uuid4(),
        "state": MemoryState.STALE,
        "actor_id": uuid4(),
        "reason": "scheduled review elapsed",
        "recorded_at": NOW,
    }
    assert MemoryLifecycleCommand.model_validate(values).state is MemoryState.STALE
    with pytest.raises(ValidationError):
        MemoryLifecycleCommand.model_validate({**values, "state": MemoryState.ACTIVE})
    with pytest.raises(ValidationError):
        MemoryLifecycleCommand.model_validate({**values, "actor_class": ActorClass.AGENT})


@req("FR-405", "FR-406")
@pytest.mark.asyncio
async def test_direct_semantic_writes_fail_before_database_access() -> None:
    provider = SqlAlchemyMemoryProvider(object())  # type: ignore[arg-type]
    assert isinstance(provider, MemoryProvider)
    scope = MemoryScope(workspace_id=uuid4(), tier=MemoryTier.SEMANTIC, namespace_id=uuid4())
    with pytest.raises(MemoryError, match="direct semantic writes are forbidden"):
        await provider.write(scope, object())  # type: ignore[arg-type]
