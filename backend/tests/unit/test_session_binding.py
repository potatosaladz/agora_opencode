"""T3-02 immutable draft-session binding tests."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.session_binding import (
    AgentDefinitionBinding,
    ConstraintBinding,
    DraftSessionBinding,
    ObjectiveBinding,
    SessionBudget,
)
from tests.traceability import req

SESSION_ID = UUID("018f0000-0000-7000-8000-000000000001")
WORKSPACE_ID = UUID("018f0000-0000-7000-8000-000000000002")
OTHER_ID = UUID("018f0000-0000-7000-8000-000000000003")
AGENT_ID = UUID("018f0000-0000-7000-8000-000000000004")
LOGICAL_AGENT_ID = UUID("018f0000-0000-7000-8000-000000000005")
OBJECTIVE_ID = UUID("018f0000-0000-7000-8000-000000000006")
CONSTRAINT_ID = UUID("018f0000-0000-7000-8000-000000000007")
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


def agent(**changes: object) -> AgentDefinitionBinding:
    data: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "session_id": SESSION_ID,
        "agent_definition_id": AGENT_ID,
        "logical_id": LOGICAL_AGENT_ID,
        "version": 3,
    }
    data.update(changes)
    return AgentDefinitionBinding.model_validate(data)


def objective(**changes: object) -> ObjectiveBinding:
    data: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "session_id": SESSION_ID,
        "artifact_id": OBJECTIVE_ID,
    }
    data.update(changes)
    return ObjectiveBinding.model_validate(data)


def constraint(**changes: object) -> ConstraintBinding:
    data: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "session_id": SESSION_ID,
        "artifact_id": CONSTRAINT_ID,
    }
    data.update(changes)
    return ConstraintBinding.model_validate(data)


def session_data(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": SESSION_ID,
        "workspace_id": WORKSPACE_ID,
        "problem_statement": "How should the city reduce transport emissions?",
        "agents": (agent(),),
        "objectives": (objective(),),
        "constraints": (constraint(),),
        "budget": SessionBudget(
            max_rounds=6,
            max_tokens=400_000,
            max_usd="100.00",
            deadline_at=NOW + timedelta(days=1),
        ),
        "created_by": OTHER_ID,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(changes)
    return data


@req("FR-102")
def test_constructs_complete_immutable_draft_binding() -> None:
    session = DraftSessionBinding.model_validate(session_data())

    assert session.status == "DRAFT"
    assert session.round == 0
    assert session.budget.max_usd == "100"
    assert session.agents[0].version == 3
    assert session.objectives[0].kind == "OBJECTIVE"
    assert session.constraints[0].kind == "CONSTRAINT"
    with pytest.raises(ValidationError):
        session.problem_statement = "changed"  # type: ignore[misc]


@req("FR-102")
def test_timestamps_are_aware_and_normalized_to_utc() -> None:
    offset_now = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
    session = DraftSessionBinding.model_validate(
        session_data(
            created_at=offset_now,
            updated_at=offset_now,
            budget=SessionBudget(
                max_rounds=1,
                max_tokens=1,
                max_usd="0.01",
                deadline_at=offset_now + timedelta(minutes=1),
            ),
        )
    )

    assert session.created_at == NOW
    assert session.created_at.tzinfo is UTC
    assert session.budget.deadline_at == NOW + timedelta(minutes=1)


@req("FR-102")
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"agents": ()}, "at least one agent"),
        ({"objectives": ()}, "at least one objective"),
        ({"agents": (agent(), agent())}, "agent definition bindings must be unique"),
        (
            {
                "agents": (
                    agent(),
                    agent(agent_definition_id=OTHER_ID),
                )
            },
            "multiple versions of one logical agent",
        ),
        ({"objectives": (objective(), objective())}, "objective bindings must be unique"),
        ({"constraints": (constraint(), constraint())}, "constraint bindings must be unique"),
        (
            {"constraints": (constraint(artifact_id=OBJECTIVE_ID),)},
            "both an objective and a constraint",
        ),
        ({"agents": (agent(workspace_id=OTHER_ID),)}, "session workspace"),
        ({"objectives": (objective(session_id=OTHER_ID),)}, "belong to the session"),
        ({"updated_at": NOW - timedelta(seconds=1)}, "must not precede"),
        (
            {
                "budget": SessionBudget(
                    max_rounds=1,
                    max_tokens=1,
                    max_usd="1",
                    deadline_at=NOW,
                )
            },
            "deadline_at must be later",
        ),
    ],
)
def test_rejects_incomplete_duplicate_or_cross_tenant_bindings(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        DraftSessionBinding.model_validate(session_data(**changes))


@req("FR-102")
@pytest.mark.parametrize(
    "changes",
    [
        {"problem_statement": "  "},
        {"status": "RUNNING"},
        {"round": 1},
        {"created_at": NOW.replace(tzinfo=None)},
        {"unexpected": True},
    ],
)
def test_rejects_non_draft_or_malformed_session_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DraftSessionBinding.model_validate(session_data(**changes))


@req("FR-102")
@pytest.mark.parametrize(
    "budget",
    [
        {"max_rounds": 0, "max_tokens": 1, "max_usd": "1"},
        {"max_rounds": 51, "max_tokens": 1, "max_usd": "1"},
        {"max_rounds": 1, "max_tokens": 0, "max_usd": "1"},
        {"max_rounds": 1, "max_tokens": 1, "max_usd": "0"},
        {"max_rounds": 1, "max_tokens": 1, "max_usd": "1.001"},
        {"max_rounds": 1, "max_tokens": 1, "max_usd": "1e2"},
        {"max_rounds": 1, "max_tokens": 1, "max_usd": 1},
        {
            "max_rounds": 1,
            "max_tokens": 1,
            "max_usd": "1",
            "deadline_at": NOW.replace(tzinfo=None),
        },
    ],
)
def test_rejects_invalid_budget_bounds(budget: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SessionBudget.model_validate(budget)


@req("FR-102")
def test_typed_bindings_reject_wrong_artifact_kind() -> None:
    with pytest.raises(ValidationError):
        ObjectiveBinding.model_validate(
            {
                "workspace_id": WORKSPACE_ID,
                "session_id": SESSION_ID,
                "artifact_id": OBJECTIVE_ID,
                "kind": "CONSTRAINT",
            }
        )
