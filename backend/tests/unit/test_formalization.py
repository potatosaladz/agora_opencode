"""T11-01 deterministic domain and immutable lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.formalization import FormalizationContext, FormalizationLifecycleService
from app.domain.formalization import (
    BooleanLiteral,
    FormalizationDecision,
    FormalizationDecisionKind,
    FormalizationError,
    FormalizationRevision,
    FormalizationStatus,
    FormalizationValidation,
    IntegerLiteral,
    Operation,
    Operator,
    RealLiteral,
    Sort,
    SymbolDeclaration,
    SymbolReference,
    ast_hash,
    derive_status,
    parse_ast,
    render_ast,
    validate_revision,
)
from app.domain.reasoning import ActorClass, canonical_json
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{index:012d}") for index in range(1, 18))
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def valid_ast() -> Operation:
    return Operation(
        operator=Operator.LE,
        arguments=(SymbolReference(name="cost"), IntegerLiteral(value="100")),
    )


def revision(
    *,
    identity: UUID = U[0],
    logical: UUID = U[0],
    number: int = 1,
    predecessor: UUID | None = None,
    ast: Operation | BooleanLiteral | None = None,
    rendering: str | None = None,
) -> FormalizationRevision:
    node = ast or valid_ast()
    return FormalizationRevision(
        id=identity,
        logical_id=logical,
        revision=number,
        supersedes_id=predecessor,
        workspace_id=U[1],
        session_id=U[2],
        source_artifact_id=U[3],
        source_artifact_logical_id=U[4],
        source_artifact_version=2,
        ast=node,
        ast_hash=ast_hash(node),
        symbols=(
            SymbolDeclaration(name="cost", sort=Sort.INTEGER, meaning="programme cost", unit="USD"),
        ),
        canonical_rendering=rendering or render_ast(node),
        premise_artifact_ids=(U[5],),
        limitations=("Nominal currency only",),
        fidelity_notes="Calendar timing omitted",
        created_at=NOW,
        actor_class=ActorClass.HUMAN,
        actor_id=U[6],
        correlation_id=U[7],
    )


@req("FR-707")
def test_closed_ast_canonical_rendering_jcs_and_hash_vectors() -> None:
    value = revision()
    assert value.canonical_rendering == "(cost <= 100)"
    assert canonical_json(value.ast.model_dump(mode="json")) == (
        b'{"arguments":[{"kind":"symbol","name":"cost"},{"kind":"integer","value":"100"}],'
        b'"kind":"operation","operator":"LE"}'
    )
    assert (
        value.ast_hash == "sha256:4b67eef5a00f1d30ceda5e18c77dcf123d69474a385394f564cf0c7e2be9717d"
    )
    assert validate_revision(value).success
    with pytest.raises(ValidationError):
        parse_ast({"kind": "python", "expression": "__import__('os')"})
    with pytest.raises(ValidationError):
        IntegerLiteral(value="01")
    assert RealLiteral(value="1.5").value == "1.5"
    with pytest.raises(ValidationError):
        RealLiteral(value="1.0")
    with pytest.raises(ValidationError):
        parse_ast({"kind": "operation", "operator": "EXEC", "arguments": []})


@req("FR-707")
def test_validation_orders_arity_symbol_sort_unit_and_rendering_issues() -> None:
    node = Operation(
        operator=Operator.AND,
        arguments=(
            Operation(operator=Operator.ADD, arguments=(SymbolReference(name="missing"),)),
            Operation(
                operator=Operator.LT,
                arguments=(SymbolReference(name="cost"), SymbolReference(name="distance")),
            ),
        ),
    )
    value = revision(ast=node, rendering="not canonical").model_copy(
        update={
            "symbols": (
                SymbolDeclaration(name="cost", sort=Sort.INTEGER, meaning="cost", unit="USD"),
                SymbolDeclaration(name="cost", sort=Sort.INTEGER, meaning="duplicate", unit="USD"),
                SymbolDeclaration(name="distance", sort=Sort.REAL, meaning="distance", unit="km"),
            )
        }
    )
    first = validate_revision(value)
    second = validate_revision(value)
    assert first.issues == second.issues
    assert [issue.code for issue in first.issues] == [
        "WRONG_ARITY",
        "UNDECLARED_SYMBOL",
        "UNIT_MISMATCH",
        "NONCANONICAL_RENDERING",
        "DUPLICATE_SYMBOL",
    ]


class Store:
    def __init__(self) -> None:
        self.revisions: list[FormalizationRevision] = []
        self.validations: dict[UUID, FormalizationValidation] = {}
        self.decisions: dict[UUID, FormalizationDecision] = {}
        self.events: list[str] = []

    async def add_revision(self, value: FormalizationRevision) -> None:
        self.revisions.append(value)

    async def head(
        self, workspace_id: UUID, logical_id: UUID, *, for_update: bool = False
    ) -> FormalizationRevision | None:
        del workspace_id, for_update
        values = [item for item in self.revisions if item.logical_id == logical_id]
        return max(values, key=lambda item: item.revision) if values else None

    async def revision(
        self, workspace_id: UUID, logical_id: UUID, revision: int | None = None
    ) -> FormalizationRevision | None:
        del workspace_id
        values = [
            item
            for item in self.revisions
            if item.logical_id == logical_id and (revision is None or item.revision == revision)
        ]
        return max(values, key=lambda item: item.revision) if values else None

    async def validation(
        self, workspace_id: UUID, revision_id: UUID
    ) -> FormalizationValidation | None:
        del workspace_id
        return self.validations.get(revision_id)

    async def decision(self, workspace_id: UUID, revision_id: UUID) -> FormalizationDecision | None:
        del workspace_id
        return self.decisions.get(revision_id)

    async def add_validation(self, value: FormalizationValidation) -> None:
        self.validations[value.formalization_revision_id] = value

    async def add_decision(self, value: FormalizationDecision) -> None:
        self.decisions[value.formalization_revision_id] = value

    async def verify_artifacts(self, value: FormalizationRevision) -> None:
        del value

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
        del event_id, revision, status, actor_id, correlation_id, recorded_at
        self.events.append(event_type)


def context() -> FormalizationContext:
    return FormalizationContext(U[6], U[7], NOW, U[8])


@req("FR-707")
async def test_lifecycle_requires_pass_and_human_confirmation_and_revision_resets() -> None:
    store = Store()
    service = FormalizationLifecycleService(store)
    created = await service.create(revision(), context=context())
    assert created.status is FormalizationStatus.CANDIDATE
    checked = await service.validate(
        U[1], U[0], expected_revision=1, validation_id=U[9], context=context()
    )
    assert checked.status is FormalizationStatus.CANDIDATE
    confirmed = await service.decide(
        U[1],
        U[0],
        expected_revision=1,
        decision_id=U[10],
        kind=FormalizationDecisionKind.CONFIRMED,
        reason="Reviewed against source",
        context=context(),
    )
    assert confirmed.status is FormalizationStatus.VALIDATED
    assert confirmed.enforceable
    successor = revision(identity=U[11], logical=U[0], number=2, predecessor=U[0])
    revised = await service.revise(successor, expected_revision=1, context=context())
    assert revised.status is FormalizationStatus.CANDIDATE
    assert await store.validation(U[1], successor.id) is None
    assert await store.decision(U[1], successor.id) is None
    historical = await service.get(U[1], U[0], revision=1)
    assert historical is not None
    assert historical.status is FormalizationStatus.VALIDATED


@req("FR-707")
async def test_failed_validation_and_explicit_rejection_are_not_enforceable() -> None:
    store = Store()
    service = FormalizationLifecycleService(store)
    bad = revision(ast=Operation(operator=Operator.NOT, arguments=(IntegerLiteral(value="1"),)))
    await service.create(bad, context=context())
    checked = await service.validate(
        U[1], U[0], expected_revision=1, validation_id=U[9], context=context()
    )
    assert checked.status is FormalizationStatus.REJECTED
    with pytest.raises(FormalizationError, match="successful deterministic validation"):
        await service.decide(
            U[1],
            U[0],
            expected_revision=1,
            decision_id=U[10],
            kind=FormalizationDecisionKind.CONFIRMED,
            reason="override",
            context=context(),
        )
    assert derive_status(checked.validation, None) is FormalizationStatus.REJECTED


@req("FR-707")
async def test_stale_revision_and_conflicting_decision_fail_closed() -> None:
    store = Store()
    service = FormalizationLifecycleService(store)
    await service.create(revision(), context=context())
    with pytest.raises(FormalizationError, match="current revision is 1"):
        await service.validate(
            U[1], U[0], expected_revision=2, validation_id=U[9], context=context()
        )
    rejected = await service.decide(
        U[1],
        U[0],
        expected_revision=1,
        decision_id=U[10],
        kind=FormalizationDecisionKind.REJECTED,
        reason="unfaithful encoding",
        context=context(),
    )
    assert rejected.status is FormalizationStatus.REJECTED
    with pytest.raises(FormalizationError, match="already exists"):
        await service.decide(
            U[1],
            U[0],
            expected_revision=1,
            decision_id=U[12],
            kind=FormalizationDecisionKind.REJECTED,
            reason="again",
            context=context(),
        )
