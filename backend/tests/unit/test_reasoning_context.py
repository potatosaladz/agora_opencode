"""T6-03 fail-closed authorized reasoning-context assembly tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.application.reasoning_context import (
    ReasoningContextAssembler,
    ReasoningContextRequest,
)
from app.domain.agent_registry import (
    AgentDefinition,
    AgentRegistry,
    AgentRoleKind,
    AgentStatus,
)
from app.domain.coordinator_policy import EffectiveMembershipStore, MembershipSnapshot
from app.domain.knowledge import NamespaceSubjectKind
from app.domain.phase3_api import Phase3ArtifactStore, Phase3SessionStore
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    ArtifactPayload,
    Bearing,
    ClaimPayload,
    ClaimType,
    ConstraintPayload,
    ConstraintType,
    FormalExpression,
    LifecycleStatus,
    ObjectivePayload,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReviewStatus,
    Strength,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.retrieval import (
    PrincipalClass,
    RetrievalDegradation,
    RetrievalRequest,
    RetrievalResult,
    RetrievalSubject,
    Retriever,
)
from app.domain.session_binding import (
    AgentDefinitionBinding,
    ConstraintBinding,
    DraftSessionBinding,
    ObjectiveBinding,
    SessionBudget,
)
from app.ports.agent_runtime import ReasoningPhase
from app.ports.errors import PermanentPortError, TransientPortError
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{value:012d}") for value in range(1, 31))
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)

WORKSPACE_ID = U[0]
SESSION_ID = U[1]
DEFINITION_ID = U[2]
LOGICAL_ID = U[3]
OBJECTIVE_ID = U[4]
CONSTRAINT_ID = U[5]
NAMESPACE_ID = U[6]
VISIBLE_ID = U[7]
TURN_ID = U[8]
CORRELATION_ID = U[9]
CAUSATION_ID = U[10]


class Sessions:
    def __init__(self, value: DraftSessionBinding | None) -> None:
        self.value = value

    async def get(self, workspace_id: UUID, session_id: UUID) -> DraftSessionBinding | None:
        del workspace_id, session_id
        return self.value


class Artifacts:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.values = {value.id: value for value in values}
        self.reads: list[tuple[UUID, UUID, UUID | None]] = []

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        session_id: UUID | None = None,
    ) -> ReasoningArtifact | None:
        self.reads.append((workspace_id, artifact_id, session_id))
        return self.values.get(artifact_id)


class Registry:
    def __init__(self, value: AgentDefinition | None) -> None:
        self.value = value

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
        del definition_id
        return self.value


class Memberships:
    def __init__(self, definitions_by_round: dict[int, tuple[AgentDefinition, ...]]) -> None:
        self.definitions_by_round = definitions_by_round

    async def membership(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> MembershipSnapshot:
        eligible_round = max(value for value in self.definitions_by_round if value <= round)
        return MembershipSnapshot(
            workspace_id=workspace_id,
            session_id=session_id,
            round=round,
            definitions=self.definitions_by_round[eligible_round],
        )


class RecordingRetriever:
    def __init__(
        self,
        result: RetrievalResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[RetrievalRequest] = []

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("unexpected retrieval")
        return self.result


def artifact(
    kind: ArtifactKind,
    artifact_id: UUID,
    *,
    workspace_id: UUID = WORKSPACE_ID,
    session_id: UUID = SESSION_ID,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    round_: int = 0,
) -> ReasoningArtifact:
    payload: ArtifactPayload
    if kind is ArtifactKind.OBJECTIVE:
        payload = ObjectivePayload(
            name="Protect households",
            objective_type="EQUITY",
            direction="MAXIMIZE",
            weight="0.8",
            weight_rationale="Session priority",
            time_horizon="5y",
            conflicts_with_ids=(),
        )
    elif kind is ArtifactKind.CONSTRAINT:
        payload = ConstraintPayload(
            name="Legal ceiling",
            statement="Debt must remain within the legal ceiling.",
            constraint_type=ConstraintType.HARD,
            category="BUDGET",
            evaluation_expression=FormalExpression(
                language="json-logic",
                ast={"<=": [{"var": "debt"}, "100.00"]},
            ),
            formal_status="VALIDATED",
        )
    else:
        payload = ClaimPayload(
            statement="A prior eligible finding.",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        )
    data: dict[str, object] = {
        "id": artifact_id,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "logical_id": U[20],
        "kind": kind,
        "schema_version": 1,
        "version": 1,
        "status": status,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": U[21],
        "round": round_,
        "payload": payload,
        "provenance": Provenance(
            origin=ProvenanceOrigin.HUMAN,
            reference="t6-03-test",
        ),
        "source_references": (),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    data["content_hash"] = artifact_content_hash(data)
    return validate_artifact(data)


def definition(**changes: object) -> AgentDefinition:
    values: dict[str, object] = {
        "id": DEFINITION_ID,
        "workspace_id": WORKSPACE_ID,
        "logical_id": LOGICAL_ID,
        "version": 3,
        "name": "fiscal-analyst",
        "domain": "fiscal",
        "role_kind": AgentRoleKind.DOMAIN_EXPERT,
        "objectives": ("Assess fiscal sustainability",),
        "constraints": ("Never claim coordinator authority",),
        "knowledge_ns": (NAMESPACE_ID,),
        "strategy_ref": "evidence-first",
        "strategy_ver": "1.0.0",
        "prompt_ref": "prompts/fiscal-analyst/v3.txt",
        "prompt_hash": "sha256:" + "a" * 64,
        "status": AgentStatus.ACTIVE,
    }
    values.update(changes)
    return AgentDefinition(
        id=cast(UUID, values["id"]),
        workspace_id=cast(UUID, values["workspace_id"]),
        logical_id=cast(UUID, values["logical_id"]),
        version=cast(int, values["version"]),
        name=cast(str, values["name"]),
        domain=cast(str, values["domain"]),
        role_kind=cast(AgentRoleKind, values["role_kind"]),
        objectives=cast(tuple[str, ...], values["objectives"]),
        constraints=cast(tuple[str, ...], values["constraints"]),
        knowledge_ns=cast(tuple[UUID, ...], values["knowledge_ns"]),
        strategy_ref=cast(str, values["strategy_ref"]),
        strategy_ver=cast(str, values["strategy_ver"]),
        prompt_ref=cast(str, values["prompt_ref"]),
        prompt_hash=cast(str, values["prompt_hash"]),
        status=cast(AgentStatus, values["status"]),
    )


def session(**changes: object) -> DraftSessionBinding:
    values: dict[str, object] = {
        "id": SESSION_ID,
        "workspace_id": WORKSPACE_ID,
        "problem_statement": "Choose a defensible intervention.",
        "agents": (
            AgentDefinitionBinding(
                workspace_id=WORKSPACE_ID,
                session_id=SESSION_ID,
                agent_definition_id=DEFINITION_ID,
                logical_id=LOGICAL_ID,
                version=3,
            ),
        ),
        "objectives": (
            ObjectiveBinding(
                workspace_id=WORKSPACE_ID,
                session_id=SESSION_ID,
                artifact_id=OBJECTIVE_ID,
            ),
        ),
        "constraints": (
            ConstraintBinding(
                workspace_id=WORKSPACE_ID,
                session_id=SESSION_ID,
                artifact_id=CONSTRAINT_ID,
            ),
        ),
        "budget": SessionBudget(
            max_rounds=5,
            max_tokens=10_000,
            max_usd="20",
        ),
        "created_by": U[22],
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return DraftSessionBinding.model_validate(values)


def retrieval_request(**changes: object) -> RetrievalRequest:
    values: dict[str, object] = {
        "attempt_id": U[11],
        "trace_id": CORRELATION_ID,
        "workspace_id": WORKSPACE_ID,
        "principal_class": PrincipalClass.AGENT,
        "principal_id": DEFINITION_ID,
        "namespace_ids": (NAMESPACE_ID,),
        "subjects": (
            RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=WORKSPACE_ID),
            RetrievalSubject(
                kind=NamespaceSubjectKind.AGENT_DEFINITION,
                id=DEFINITION_ID,
            ),
            RetrievalSubject(kind=NamespaceSubjectKind.SESSION, id=SESSION_ID),
        ),
        "query": "fiscal evidence",
        "query_vector": (0.1, 0.2),
        "embedding_model": "embed-small",
        "embedding_version": "1",
        "index_version": "index@1",
        "requested_at": NOW,
    }
    values.update(changes)
    return RetrievalRequest.model_validate(values)


def retrieval_result(
    request: RetrievalRequest,
    **changes: object,
) -> RetrievalResult:
    values: dict[str, object] = {
        "query_hash": "sha256:" + hashlib.sha256(request.query.encode()).hexdigest(),
        "requested_namespace_ids": request.namespace_ids,
        "searched_namespace_ids": request.namespace_ids,
        "index_version": request.index_version,
        "embedding_model": request.embedding_model,
        "embedding_version": request.embedding_version,
        "reranker_version": "rrf@1",
        "lexical_count": 0,
        "vector_count": 0,
        "degradation": RetrievalDegradation.NONE,
        "warnings": (),
        "chunks": (),
    }
    values.update(changes)
    return RetrievalResult.model_validate(values)


def request(**changes: object) -> ReasoningContextRequest:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE_ID,
        "session_id": SESSION_ID,
        "agent_definition_id": DEFINITION_ID,
        "turn_id": TURN_ID,
        "correlation_id": CORRELATION_ID,
        "causation_id": CAUSATION_ID,
        "round": 2,
        "phase": ReasoningPhase.ARGUE,
        "canonicalizer_version": "canonicalizer@1",
        "visible_artifact_ids": (VISIBLE_ID,),
        "retrieval_request": retrieval_request(),
        "budget_remaining_tokens": 900,
        "budget_remaining_usd": Decimal("1.25"),
        "timeout_s": 12.0,
    }
    values.update(changes)
    return ReasoningContextRequest.model_validate(values)


def assembler(
    *,
    session_value: DraftSessionBinding | None = None,
    artifacts: Artifacts | None = None,
    definition_value: AgentDefinition | None = None,
    retriever: RecordingRetriever | None = None,
    memberships: Memberships | None = None,
) -> tuple[ReasoningContextAssembler, Artifacts, RecordingRetriever]:
    durable_definition = definition_value or definition()
    original_definition = definition()
    effective_definition = (
        durable_definition
        if (
            durable_definition.id,
            durable_definition.logical_id,
            durable_definition.version,
        )
        == (original_definition.id, original_definition.logical_id, original_definition.version)
        else original_definition
    )
    artifact_store = artifacts or Artifacts(
        artifact(ArtifactKind.OBJECTIVE, OBJECTIVE_ID),
        artifact(ArtifactKind.CONSTRAINT, CONSTRAINT_ID),
        artifact(ArtifactKind.CLAIM, VISIBLE_ID, round_=1),
    )
    retrieval = retriever or RecordingRetriever(retrieval_result(retrieval_request()))
    service = ReasoningContextAssembler(
        cast(Phase3SessionStore, Sessions(session_value or session())),
        cast(Phase3ArtifactStore, artifact_store),
        cast(AgentRegistry, Registry(durable_definition)),
        cast(Retriever, retrieval),
        cast(
            EffectiveMembershipStore,
            memberships or Memberships({1: (effective_definition,)}),
        ),
    )
    return service, artifact_store, retrieval


@req("FR-209")
async def test_assembles_pins_artifacts_and_explicit_zero_match_retrieval() -> None:
    service, _, retriever = assembler()

    context = await service.assemble(request())

    assert context.problem_statement == "Choose a defensible intervention."
    assert json.loads(context.objective_summaries[0])["name"] == "Protect households"
    assert json.loads(context.constraint_summaries[0])["formal_status"] == "VALIDATED"
    assert context.agent_definition.version == 3
    assert context.agent_definition.strategy_name == "evidence-first"
    assert context.visible_artifact_ids == (VISIBLE_ID,)
    assert json.loads(context.visible_artifacts[0].artifact_json)["content_hash"] == (
        context.visible_artifacts[0].content_hash
    )
    assert context.retrieval is not None
    assert context.retrieval.chunks == ()
    assert context.retrieval.searched_namespace_ids == (NAMESPACE_ID,)
    assert context.retrieval.degradation == "NONE"
    assert retriever.requests == [retrieval_request()]


@req("FR-209")
async def test_retrieval_failure_propagates_instead_of_becoming_empty_context() -> None:
    error = TransientPortError("vector service unavailable", port="retrieval")
    service, _, retriever = assembler(retriever=RecordingRetriever(error=error))

    with pytest.raises(TransientPortError) as captured:
        await service.assemble(request())

    assert captured.value is error
    assert retriever.requests == [retrieval_request()]


@req("FR-209")
async def test_injected_definition_is_visible_only_from_its_effective_round() -> None:
    injected = definition(id=U[23], logical_id=U[24], knowledge_ns=())
    memberships = Memberships({1: (definition(),), 3: (definition(), injected)})
    service, _, _ = assembler(definition_value=injected, memberships=memberships)

    with pytest.raises(PermanentPortError, match="not pinned"):
        await service.assemble(
            request(
                agent_definition_id=injected.id,
                round=2,
                visible_artifact_ids=(),
                retrieval_request=None,
            )
        )

    context = await service.assemble(
        request(
            agent_definition_id=injected.id,
            round=3,
            visible_artifact_ids=(),
            retrieval_request=None,
        )
    )
    assert context.agent_definition_id == injected.id


@req("FR-209")
@pytest.mark.parametrize(
    ("wrong_session_scope", "definition_value", "message"),
    [
        (True, definition(), "session does not exist"),
        (False, definition(id=U[23]), "identity or version"),
        (False, definition(version=4), "identity or version"),
        (False, definition(status=AgentStatus.WITHDRAWN), "not runnable"),
    ],
)
async def test_rejects_cross_tenant_unpinned_version_and_unrunnable_definition(
    wrong_session_scope: bool,
    definition_value: AgentDefinition,
    message: str,
) -> None:
    session_value = session()
    if wrong_session_scope:
        object.__setattr__(session_value, "workspace_id", U[23])
    service, _, retriever = assembler(
        session_value=session_value,
        definition_value=definition_value,
    )

    with pytest.raises(PermanentPortError, match=message):
        await service.assemble(request())

    assert retriever.requests == []


@req("FR-209")
@pytest.mark.parametrize(
    "retrieval",
    [
        retrieval_request(
            principal_id=U[23],
            subjects=(
                RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=WORKSPACE_ID),
                RetrievalSubject(kind=NamespaceSubjectKind.AGENT_DEFINITION, id=U[23]),
                RetrievalSubject(kind=NamespaceSubjectKind.SESSION, id=SESSION_ID),
            ),
        ),
        retrieval_request(
            subjects=(
                RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=WORKSPACE_ID),
                RetrievalSubject(
                    kind=NamespaceSubjectKind.AGENT_DEFINITION,
                    id=DEFINITION_ID,
                ),
            ),
        ),
        retrieval_request(trace_id=U[23]),
        retrieval_request(namespace_ids=(U[23],)),
    ],
)
async def test_rejects_wrong_retrieval_principal_subject_trace_or_namespace(
    retrieval: RetrievalRequest,
) -> None:
    service, _, retriever = assembler()

    with pytest.raises(PermanentPortError, match="not scoped"):
        await service.assemble(request(retrieval_request=retrieval))

    assert retriever.requests == []


@req("FR-209")
@pytest.mark.parametrize(
    "changes",
    [
        {"query_hash": "sha256:" + "0" * 64},
        {"searched_namespace_ids": (U[23],)},
        {"index_version": "index@2"},
    ],
)
async def test_rejects_retrieval_results_inconsistent_with_authorized_request(
    changes: dict[str, object],
) -> None:
    retrieval = retrieval_request()
    service, _, _ = assembler(retriever=RecordingRetriever(retrieval_result(retrieval, **changes)))

    with pytest.raises(PermanentPortError, match="does not match"):
        await service.assemble(request(retrieval_request=retrieval))


@req("FR-209")
@pytest.mark.parametrize(
    "objective",
    [
        None,
        artifact(
            ArtifactKind.OBJECTIVE,
            OBJECTIVE_ID,
            status=LifecycleStatus.WITHDRAWN,
        ),
        artifact(ArtifactKind.CLAIM, OBJECTIVE_ID),
        artifact(
            ArtifactKind.OBJECTIVE,
            OBJECTIVE_ID,
            session_id=U[23],
        ),
    ],
)
async def test_rejects_missing_inactive_wrong_type_or_cross_session_objective(
    objective: ReasoningArtifact | None,
) -> None:
    values = [
        artifact(ArtifactKind.CONSTRAINT, CONSTRAINT_ID),
        artifact(ArtifactKind.CLAIM, VISIBLE_ID, round_=1),
    ]
    if objective is not None:
        values.append(objective)
    service, _, retriever = assembler(artifacts=Artifacts(*values))

    with pytest.raises(PermanentPortError, match="objective"):
        await service.assemble(request())

    assert retriever.requests == []


@req("FR-209")
@pytest.mark.parametrize(
    "visible",
    [
        None,
        artifact(
            ArtifactKind.CLAIM,
            VISIBLE_ID,
            status=LifecycleStatus.WITHDRAWN,
            round_=1,
        ),
        artifact(ArtifactKind.CLAIM, VISIBLE_ID, round_=3),
        artifact(ArtifactKind.CLAIM, VISIBLE_ID, session_id=U[23], round_=1),
    ],
)
async def test_rejects_missing_inactive_future_or_cross_session_visible_artifact(
    visible: ReasoningArtifact | None,
) -> None:
    values = [
        artifact(ArtifactKind.OBJECTIVE, OBJECTIVE_ID),
        artifact(ArtifactKind.CONSTRAINT, CONSTRAINT_ID),
    ]
    if visible is not None:
        values.append(visible)
    service, _, retriever = assembler(artifacts=Artifacts(*values))

    with pytest.raises(PermanentPortError, match="visible artifact"):
        await service.assemble(request())

    assert retriever.requests == []


@req("FR-209")
async def test_rejects_duplicate_visible_artifacts_before_any_artifact_read() -> None:
    service, artifact_store, retriever = assembler()

    with pytest.raises(PermanentPortError, match="must be unique"):
        await service.assemble(request(visible_artifact_ids=(VISIBLE_ID, VISIBLE_ID)))

    assert artifact_store.reads == []
    assert retriever.requests == []


@req("FR-209")
async def test_rejects_round_one_visible_artifact_before_any_artifact_read() -> None:
    service, artifact_store, retriever = assembler()

    with pytest.raises(PermanentPortError, match="round 1 ASSESS"):
        await service.assemble(request(round=1, phase=ReasoningPhase.ASSESS))

    assert artifact_store.reads == []
    assert retriever.requests == []


@req("FR-209")
async def test_rejects_missing_retrieval_when_definition_pins_namespaces() -> None:
    service, _, retriever = assembler()

    with pytest.raises(PermanentPortError, match="requires an explicit retrieval"):
        await service.assemble(request(visible_artifact_ids=(), retrieval_request=None))

    assert retriever.requests == []


@req("FR-209")
async def test_allows_absent_retrieval_when_definition_has_no_namespaces() -> None:
    service, _, retriever = assembler(definition_value=replace(definition(), knowledge_ns=()))

    context = await service.assemble(request(visible_artifact_ids=(), retrieval_request=None))

    assert context.retrieval is None
    assert retriever.requests == []
