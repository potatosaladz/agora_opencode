"""Tenant-scoped authored Phase 3 session and artifact routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from app.api.errors import not_found
from app.api.phase3_contracts import (
    ArtifactCreate,
    ArtifactRevisionCreate,
    ArtifactWithdrawalCreate,
    HumanInputCreate,
    SessionControlCreate,
    SessionCreate,
    SourceRetractionCreate,
    artifact_response,
    decode_artifact_payload,
    session_response,
)
from app.application.artifact_commit import ArtifactCommitService, ArtifactEventContext
from app.application.provenance import ProvenanceService
from app.application.session_commit import SessionArtifactCommit, SessionCommitService
from app.application.session_control import SessionControlService, validate_control_request
from app.application.session_start import SessionStartService
from app.application.source_impact import SourceImpactService
from app.common.errors import Internal, ValidationFailed, VersionConflict
from app.common.ids import parse_id, public_id, uuid7
from app.domain.artifact_commit import ArtifactCommitError
from app.domain.citations import CitationError, SourceRetractionCommand
from app.domain.phase3_api import IdempotencyRecord
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    LifecycleStatus,
    ReasoningArtifact,
    artifact_content_hash,
    content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_PAGE_SIZE,
    MAX_ALLOWED_DEPTH,
    MAX_PAGE_SIZE,
)
from app.domain.session_bootstrap import SessionBootstrapInput
from app.domain.session_control import (
    HumanDirective,
    SessionControlCommand,
    SessionControlKind,
    session_control_ids,
)
from app.domain.session_lifecycle import InvalidSessionTransition
from app.domain.source_impact import ImpactDependencyType, SourceImpactReport
from app.ports.auth import WorkspaceRole
from app.security import current_principal, require_roles

router = APIRouter(prefix="/api/v1", tags=["reasoning"])
_READ = (
    WorkspaceRole.ADMIN,
    WorkspaceRole.RESEARCHER,
    WorkspaceRole.OPERATOR,
    WorkspaceRole.VIEWER,
)
_WRITE = (WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER)


# trace: FR-101, FR-102
def _request_id(request: Request) -> str:
    return str(request.state.correlation_id)


def _context(request: Request, actor_id: Any) -> ArtifactEventContext:
    correlation_id = _correlation_id(request)
    return ArtifactEventContext(
        event_id=uuid7(),
        correlation_id=correlation_id,
        actor_class=ActorClass.HUMAN,
        actor_id=actor_id,
        recorded_at=datetime.now(UTC),
    )


def _correlation_id(request: Request) -> UUID:
    correlation = str(request.state.correlation_id)
    try:
        return UUID(hex=correlation.removeprefix("req_"))
    except ValueError:
        return uuid7()


def _public_provenance(value: Any, key: str = "") -> Any:
    """Translate internal provenance identifiers at the HTTP boundary."""
    if isinstance(value, UUID):
        if key in {
            "workspace_id",
            "session_id",
            "artifact_id",
            "root_artifact_id",
            "ref_id",
            "claim_artifact_id",
        }:
            resource = {
                "workspace_id": "workspace",
                "session_id": "session",
            }.get(key, "artifact")
            return public_id(resource, value)
        resources = {
            "source_id": "source",
            "namespace_id": "namespace",
            "citation_id": "citation",
            "document_id": "document",
            "chunk_id": "chunk",
            "from_node": "graph_node",
            "to_node": "graph_node",
        }
        if key in resources:
            return public_id(resources[key], value)
        return value.hex
    if isinstance(value, dict):
        result = {item_key: _public_provenance(item, item_key) for item_key, item in value.items()}
        if "ref_id" in value and "id" in value:
            result["id"] = public_id("graph_node", value["id"])
        elif "from_node" in value and "id" in value:
            result["id"] = public_id("graph_edge", value["id"])
        return result
    if isinstance(value, list | tuple):
        return [_public_provenance(item) for item in value]
    return value


def _impact_response(report: SourceImpactReport, request: Request) -> dict[str, Any]:
    def dependency_id(dependency_type: ImpactDependencyType, value: UUID) -> str:
        resource = {
            ImpactDependencyType.ARTIFACT: "artifact",
            ImpactDependencyType.CONSENSUS_RESULT: "consensus_result",
            ImpactDependencyType.RECOMMENDATION: "recommendation",
        }[dependency_type]
        return public_id(resource, value)

    dependencies = [
        {
            **item.model_dump(
                mode="json",
                exclude={"dependent_id", "session_id", "root_evidence_id", "logical_id"},
            ),
            "dependent_id": dependency_id(item.dependency_type, item.dependent_id),
            "session_id": public_id("session", item.session_id),
            "root_evidence_id": (
                public_id("artifact", item.root_evidence_id)
                if item.root_evidence_id is not None
                else None
            ),
            "logical_id": (
                public_id("artifact", item.logical_id) if item.logical_id is not None else None
            ),
        }
        for item in report.dependencies
    ]
    return {
        "data": {
            "id": public_id("impact_report", report.report_id),
            "retraction_id": public_id("source_retraction", report.retraction_id),
            "event_id": public_id("event", report.event_id),
            "source_id": public_id("source", report.source_id),
            "actor_id": public_id("user", report.actor_id),
            "reason": report.reason,
            "generated_at": report.generated_at.isoformat().replace("+00:00", "Z"),
            "analysis_status": report.analysis_status.value,
            "complete": report.complete,
            "truncated": report.truncated,
            "error": report.error,
            "dependencies": dependencies,
            "affected_claim_ids": [
                public_id("artifact", value) for value in report.affected_claim_ids
            ],
            "affected_alternative_ids": [
                public_id("artifact", value) for value in report.affected_alternative_ids
            ],
            "affected_consensus_result_ids": [
                public_id("consensus_result", value)
                for value in report.affected_consensus_result_ids
            ],
            "affected_recommendation_ids": [
                public_id("recommendation", value) for value in report.affected_recommendation_ids
            ],
        },
        "meta": {
            "request_id": _request_id(request),
            "workspace_id": public_id("workspace", report.workspace_id),
        },
    }


def _artifact(
    body: ArtifactCreate | ArtifactRevisionCreate,
    *,
    workspace_id: Any,
    session_id: Any,
    owner_id: Any,
    now: datetime,
    artifact_id: Any,
    logical_id: Any,
    kind: ArtifactKind,
    version: int = 1,
    supersedes_id: Any = None,
) -> ReasoningArtifact:
    supplied = body.model_dump(mode="python", exclude={"reason", "payload"})
    supplied["payload"] = decode_artifact_payload(kind, body.payload)
    supplied["parent_relationships"] = tuple(
        {
            "edge_type": item.edge_type,
            "target_artifact_id": parse_id("artifact", item.target_artifact_id),
        }
        for item in body.parent_relationships
    )
    if body.confidence is not None:
        supplied["confidence"] = {
            **body.confidence.model_dump(mode="python", exclude={"basis_artifact_ids"}),
            "basis_artifact_ids": tuple(
                parse_id("artifact", value) for value in body.confidence.basis_artifact_ids
            ),
        }
    data = {
        **supplied,
        "id": artifact_id,
        "workspace_id": workspace_id,
        "session_id": session_id,
        "logical_id": logical_id,
        "kind": kind,
        "schema_version": 1,
        "version": version,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": supersedes_id,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": owner_id,
        "round": 0,
        "created_at": now,
        "updated_at": now,
    }
    data["content_hash"] = artifact_content_hash(data)
    return validate_artifact(data)


async def _idempotent(
    tx: Any,
    workspace_id: Any,
    operation: str,
    key: str,
    request_hash: str,
    action: Callable[[], Awaitable[tuple[int, dict[str, Any]]]],
) -> JSONResponse:
    if not key.strip() or len(key) > 255:
        raise ValidationFailed("Idempotency-Key must contain 1 to 255 characters")
    existing = await tx.idempotency.load_after_lock(workspace_id, operation, key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise VersionConflict(
                "Idempotency-Key was already used for a different request", current_version=1
            )
        replay_headers = {"Idempotency-Replayed": "true"}
        version = existing.response_body.get("meta", {}).get("version")
        if isinstance(version, int):
            replay_headers["ETag"] = str(version)
        return JSONResponse(
            existing.response_body,
            status_code=existing.status_code,
            headers=replay_headers,
        )
    status, response = await action()
    await tx.idempotency.save(
        workspace_id, operation, key, IdempotencyRecord(request_hash, status, response)
    )
    response_headers: dict[str, str] = {}
    version = response.get("meta", {}).get("version")
    if isinstance(version, int):
        response_headers["ETag"] = str(version)
    return JSONResponse(response, status_code=status, headers=response_headers)


@router.post("/sessions", status_code=201)
@require_roles(*_WRITE)
async def create_session(
    request: Request,
    body: SessionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    principal = current_principal(request)
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def action() -> tuple[int, dict[str, Any]]:
            session_id = uuid7()
            session_context = _context(request, principal.user_id)

            def commits(inputs: tuple[ArtifactCreate, ...]) -> tuple[SessionArtifactCommit, ...]:
                result: list[SessionArtifactCommit] = []
                for item in inputs:
                    now, artifact_id = datetime.now(UTC), uuid7()
                    artifact = _artifact(
                        item,
                        workspace_id=principal.workspace_id,
                        session_id=session_id,
                        owner_id=principal.user_id,
                        now=now,
                        artifact_id=artifact_id,
                        logical_id=artifact_id,
                        kind=item.kind,
                    )
                    result.append(
                        SessionArtifactCommit(
                            artifact=artifact,
                            node_id=uuid7(),
                            relationship_edge_ids=tuple(
                                uuid7() for _ in artifact.parent_relationships
                            ),
                            label=item.kind.value.title(),
                            context=_context(request, principal.user_id),
                        )
                    )
                return tuple(result)

            try:
                binding = await SessionCommitService(
                    tx.sessions,
                    tx.lifecycle,
                    ArtifactCommitService(tx.artifacts, tx.graph, tx.ledger),
                    tx.ledger,
                ).create(
                    session_id=session_id,
                    workspace_id=principal.workspace_id,
                    created_by=principal.user_id,
                    problem_statement=body.problem_statement,
                    agent_definition_ids=tuple(
                        parse_id("agent", value) for value in body.agent_definition_ids
                    ),
                    objective_commits=commits(body.objectives),
                    constraint_commits=commits(body.constraints),
                    budget=body.budget,
                    context=session_context,
                )
            except (ArtifactCommitError, ValidationError) as exc:
                raise ValidationFailed(str(exc)) from exc
            if len(binding.agents) != len(body.agent_definition_ids):
                raise ValidationFailed("one or more agent definitions do not exist")
            lifecycle = await tx.lifecycle.get(principal.workspace_id, session_id)
            if lifecycle is None:
                raise Internal("session lifecycle projection is missing")
            return 201, session_response(
                binding,
                principal,
                request_id=_request_id(request),
                lifecycle=lifecycle,
            )

        return await _idempotent(
            tx,
            principal.workspace_id,
            "session:create",
            idempotency_key,
            content_hash(body.model_dump(mode="json")),
            action,
        )


@router.get("/sessions/{session_id}")
@require_roles(*_READ)
async def get_session(request: Request, session_id: str) -> JSONResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("session", session_id)
    except ValueError as exc:
        raise not_found("session") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        binding = await tx.sessions.get(principal.workspace_id, internal_id)
        if binding is None:
            raise not_found("session")
        lifecycle = await tx.lifecycle.get(principal.workspace_id, internal_id)
        if lifecycle is None:
            raise Internal("session lifecycle projection is missing")
        body = session_response(
            binding, principal, request_id=_request_id(request), lifecycle=lifecycle
        )
        return JSONResponse(body, headers={"ETag": "1"})


@router.post("/sessions/{session_id}/start", status_code=202)
@require_roles(*_WRITE)
async def start_session(
    request: Request,
    session_id: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("session", session_id)
    except ValueError as exc:
        raise not_found("session") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        binding = await tx.sessions.get(principal.workspace_id, internal_id)
        if binding is None:
            raise not_found("session")

        async def action() -> tuple[int, dict[str, Any]]:
            try:
                correlation_id = UUID(hex=_request_id(request).removeprefix("req_"))
            except ValueError:
                correlation_id = uuid7()
            lifecycle = await SessionStartService(
                tx.lifecycle,
                request.app.state.container.workflow_engine,
                task_queue=request.app.state.settings.temporal_task_queue,
                timeout_s=request.app.state.settings.temporal_start_timeout_s,
            ).start(
                SessionBootstrapInput(
                    workspace_id=principal.workspace_id,
                    session_id=internal_id,
                    initialized_event_id=uuid7(),
                    round_started_event_id=uuid7(),
                    failed_event_id=uuid7(),
                    correlation_id=correlation_id,
                )
            )
            return 202, session_response(
                binding,
                principal,
                request_id=_request_id(request),
                lifecycle=lifecycle,
            )

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"session:start:{internal_id}",
            idempotency_key,
            content_hash({"session_id": str(internal_id)}),
            action,
        )


async def _control_session(
    request: Request,
    session_id: str,
    body: SessionControlCreate | HumanInputCreate,
    idempotency_key: str,
    kind: SessionControlKind,
) -> JSONResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("session", session_id)
    except ValueError as exc:
        raise not_found("session") from exc
    request_payload = body.model_dump(mode="json")
    request_hash = content_hash({"command": kind.value, "body": request_payload})
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        binding = await tx.sessions.get(principal.workspace_id, internal_id)
        if binding is None:
            raise not_found("session")

        async def action() -> tuple[int, dict[str, Any]]:
            lifecycle = await tx.lifecycle.get(principal.workspace_id, internal_id)
            if lifecycle is None:
                raise Internal("session lifecycle projection is missing")
            try:
                validate_control_request(kind, lifecycle)
            except InvalidSessionTransition as exc:
                raise VersionConflict(str(exc), current_version=1) from exc
            command_id, event_id, failure_event_id = session_control_ids(
                principal.workspace_id,
                internal_id,
                kind,
                idempotency_key,
                request_hash,
            )
            directive = None
            if isinstance(body, HumanInputCreate):
                for artifact_id in body.artifact_ids:
                    if (
                        await tx.artifacts.get(
                            principal.workspace_id,
                            parse_id("artifact", artifact_id),
                            session_id=internal_id,
                        )
                        is None
                    ):
                        raise not_found("artifact")
                directive = HumanDirective(
                    kind=body.kind,
                    instruction=body.instruction,
                    artifact_ids=tuple(parse_id("artifact", value) for value in body.artifact_ids),
                )
            await SessionControlService(
                request.app.state.container.workflow_engine,
                timeout_s=request.app.state.settings.temporal_signal_timeout_s,
            ).enqueue(
                SessionControlCommand(
                    command_id=command_id,
                    event_id=event_id,
                    failure_event_id=failure_event_id,
                    workspace_id=principal.workspace_id,
                    session_id=internal_id,
                    kind=kind,
                    observed_state=lifecycle.state,
                    correlation_id=_correlation_id(request),
                    actor_id=principal.user_id,
                    requested_at=datetime.now(UTC),
                    reason=body.reason,
                    directive=directive,
                )
            )
            return 202, session_response(
                binding,
                principal,
                request_id=_request_id(request),
                lifecycle=lifecycle,
            )

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"session:{kind.value.lower()}:{internal_id}",
            idempotency_key,
            request_hash,
            action,
        )


@router.post("/sessions/{session_id}/pause", status_code=202)
@require_roles(*_WRITE)
async def pause_session(
    request: Request,
    session_id: str,
    body: SessionControlCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    return await _control_session(
        request, session_id, body, idempotency_key, SessionControlKind.PAUSE
    )


@router.post("/sessions/{session_id}/resume", status_code=202)
@require_roles(*_WRITE)
async def resume_session(
    request: Request,
    session_id: str,
    body: SessionControlCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    return await _control_session(
        request, session_id, body, idempotency_key, SessionControlKind.RESUME
    )


@router.post("/sessions/{session_id}/cancel", status_code=202)
@require_roles(*_WRITE)
async def cancel_session(
    request: Request,
    session_id: str,
    body: SessionControlCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    return await _control_session(
        request, session_id, body, idempotency_key, SessionControlKind.CANCEL
    )


@router.post("/sessions/{session_id}/terminate", status_code=202, deprecated=True)
@require_roles(*_WRITE)
async def terminate_session(
    request: Request,
    session_id: str,
    body: SessionControlCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    return await _control_session(
        request, session_id, body, idempotency_key, SessionControlKind.CANCEL
    )


@router.post("/sessions/{session_id}/human-input", status_code=202)
@require_roles(*_WRITE)
async def submit_human_input(
    request: Request,
    session_id: str,
    body: HumanInputCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    return await _control_session(
        request, session_id, body, idempotency_key, SessionControlKind.HUMAN_INPUT
    )


@router.get("/artifacts/{artifact_id}")
@require_roles(*_READ)
async def get_artifact(request: Request, artifact_id: str) -> JSONResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("artifact", artifact_id)
    except ValueError as exc:
        raise not_found("artifact") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        artifact = await tx.artifacts.get(principal.workspace_id, internal_id)
        if artifact is None:
            raise not_found("artifact")
        body = artifact_response(artifact, principal, request_id=_request_id(request))
        return JSONResponse(body, headers={"ETag": str(artifact.version)})


@router.get("/artifacts/{artifact_id}/provenance")
@require_roles(*_READ)
async def get_artifact_provenance(
    request: Request,
    artifact_id: str,
    max_depth: Annotated[int, Query(ge=0, le=MAX_ALLOWED_DEPTH)] = DEFAULT_MAX_DEPTH,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> JSONResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("artifact", artifact_id)
    except ValueError as exc:
        raise not_found("artifact") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        result = await ProvenanceService(tx.artifacts, tx.graph, tx.citations).provenance_of(
            principal.workspace_id,
            internal_id,
            max_depth=max_depth,
            page_size=limit,
            cursor=cursor,
        )
        if result is None:
            raise not_found("artifact")
        body = _public_provenance(result.model_dump(mode="python"))
        return JSONResponse(
            {
                "data": body,
                "meta": {
                    "request_id": _request_id(request),
                    "workspace_id": public_id("workspace", principal.workspace_id),
                },
            }
        )


@router.post("/sources/{source_id}/retractions", status_code=201)
@require_roles(*_WRITE)
async def retract_source(
    request: Request,
    source_id: str,
    body: SourceRetractionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        sid = parse_id("source", source_id)
    except ValueError as exc:
        raise not_found("source") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def action() -> tuple[int, dict[str, Any]]:
            now = datetime.now(UTC)
            try:
                report = await SourceImpactService(tx.source_impacts).retract_source(
                    SourceRetractionCommand(
                        retraction_id=uuid7(),
                        workspace_id=principal.workspace_id,
                        source_id=sid,
                        actor_id=principal.user_id,
                        reason=body.reason,
                        retracted_at=now,
                    ),
                    report_id=uuid7(),
                    event_id=uuid7(),
                    correlation_id=_correlation_id(request),
                )
            except CitationError as exc:
                raise not_found("source") from exc
            return 201, _impact_response(report, request)

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"source:retract:{sid}",
            idempotency_key,
            content_hash(body.model_dump(mode="json")),
            action,
        )


@router.get("/impact-reports/{report_id}")
@require_roles(*_READ)
async def get_impact_report(request: Request, report_id: str) -> JSONResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("impact_report", report_id)
    except ValueError as exc:
        raise not_found("impact report") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        report = await SourceImpactService(tx.source_impacts).get_report(
            principal.workspace_id, internal_id
        )
        if report is None:
            raise not_found("impact report")
        return JSONResponse(_impact_response(report, request))


@router.post("/sessions/{session_id}/artifacts", status_code=201)
@require_roles(*_WRITE)
async def create_artifact(
    request: Request,
    session_id: str,
    body: ArtifactCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        sid = parse_id("session", session_id)
    except ValueError as exc:
        raise not_found("session") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        if await tx.sessions.get(principal.workspace_id, sid) is None:
            raise not_found("session")

        async def action() -> tuple[int, dict[str, Any]]:
            now, aid = datetime.now(UTC), uuid7()
            try:
                artifact = _artifact(
                    body,
                    workspace_id=principal.workspace_id,
                    session_id=sid,
                    owner_id=principal.user_id,
                    now=now,
                    artifact_id=aid,
                    logical_id=aid,
                    kind=body.kind,
                )
                result = await ArtifactCommitService(tx.artifacts, tx.graph, tx.ledger).commit(
                    artifact,
                    node_id=uuid7(),
                    relationship_edge_ids=tuple(uuid7() for _ in artifact.parent_relationships),
                    label=body.kind.value.title(),
                    context=_context(request, principal.user_id),
                )
            except (ArtifactCommitError, ValidationError) as exc:
                raise ValidationFailed(str(exc)) from exc
            return 201, artifact_response(
                result.artifact, principal, request_id=_request_id(request)
            )

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"artifact:create:{sid}",
            idempotency_key,
            content_hash(body.model_dump(mode="json")),
            action,
        )


@router.post("/artifacts/{artifact_id}/revisions", status_code=201)
@require_roles(*_WRITE)
async def revise_artifact(
    request: Request,
    artifact_id: str,
    body: ArtifactRevisionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    if_match: Annotated[int, Header(alias="If-Match", ge=1)],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        aid = parse_id("artifact", artifact_id)
    except ValueError as exc:
        raise not_found("artifact") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def action() -> tuple[int, dict[str, Any]]:
            current = await tx.artifacts.get(principal.workspace_id, aid)
            if current is None:
                raise not_found("artifact")
            previous = await tx.artifacts.get_for_update(
                principal.workspace_id, current.session_id, aid
            )
            if previous is None:
                raise not_found("artifact")
            if previous.version != if_match:
                raise VersionConflict(
                    "artifact version does not match If-Match", current_version=previous.version
                )
            now, next_id = datetime.now(UTC), uuid7()
            try:
                revision = _artifact(
                    body,
                    workspace_id=principal.workspace_id,
                    session_id=previous.session_id,
                    owner_id=principal.user_id,
                    now=now,
                    artifact_id=next_id,
                    logical_id=previous.logical_id,
                    kind=previous.kind,
                    version=previous.version + 1,
                    supersedes_id=previous.id,
                )
                result = await ArtifactCommitService(tx.artifacts, tx.graph, tx.ledger).revise(
                    revision,
                    node_id=uuid7(),
                    edge_id=uuid7(),
                    relationship_edge_ids=tuple(uuid7() for _ in revision.parent_relationships),
                    label=previous.kind.value.title(),
                    reason=body.reason,
                    context=_context(request, principal.user_id),
                )
            except ValidationError as exc:
                raise ValidationFailed(str(exc)) from exc
            except ArtifactCommitError as exc:
                raise VersionConflict(str(exc), current_version=previous.version) from exc
            return 201, artifact_response(
                result.artifact, principal, request_id=_request_id(request)
            )

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"artifact:revise:{aid}",
            idempotency_key,
            content_hash({"if_match": if_match, "body": body.model_dump(mode="json")}),
            action,
        )


@router.post("/artifacts/{artifact_id}/withdrawals")
@require_roles(*_WRITE)
async def withdraw_artifact(
    request: Request,
    artifact_id: str,
    body: ArtifactWithdrawalCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    if_match: Annotated[int, Header(alias="If-Match", ge=1)],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        aid = parse_id("artifact", artifact_id)
    except ValueError as exc:
        raise not_found("artifact") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def action() -> tuple[int, dict[str, Any]]:
            current = await tx.artifacts.get(principal.workspace_id, aid)
            if current is None:
                raise not_found("artifact")
            locked = await tx.artifacts.get_for_update(
                principal.workspace_id, current.session_id, aid
            )
            if locked is None:
                raise not_found("artifact")
            if locked.version != if_match:
                raise VersionConflict(
                    "artifact version does not match If-Match", current_version=locked.version
                )
            try:
                result = await ArtifactCommitService(tx.artifacts, tx.graph, tx.ledger).withdraw(
                    principal.workspace_id,
                    locked.session_id,
                    aid,
                    reason=body.reason,
                    warrant_artifact_ids=tuple(
                        parse_id("artifact", value) for value in body.warrant_artifact_ids
                    ),
                    context=_context(request, principal.user_id),
                )
            except ArtifactCommitError as exc:
                raise VersionConflict(str(exc), current_version=locked.version) from exc
            return 200, artifact_response(
                result.artifact, principal, request_id=_request_id(request)
            )

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"artifact:withdraw:{aid}",
            idempotency_key,
            content_hash({"if_match": if_match, "body": body.model_dump(mode="json")}),
            action,
        )
