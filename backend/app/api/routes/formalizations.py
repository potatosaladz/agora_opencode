"""Authenticated, idempotent T11-01 formalization lifecycle API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from starlette.responses import JSONResponse

from app.api.errors import not_found
from app.api.formalization_contracts import (
    FormalizationCreate,
    FormalizationDecisionCreate,
    FormalizationRevisionCreate,
    FormalizationValidationCreate,
    formalization_response,
)
from app.application.formalization import FormalizationContext, FormalizationLifecycleService
from app.common.errors import ValidationFailed, VersionConflict
from app.common.ids import parse_id, uuid7
from app.domain.formalization import (
    FormalizationDecisionKind,
    FormalizationError,
    FormalizationRevision,
    ast_hash,
)
from app.domain.phase3_api import IdempotencyRecord
from app.domain.reasoning import ActorClass, content_hash
from app.ports.auth import WorkspaceRole
from app.security import current_principal, require_roles

router = APIRouter(prefix="/api/v1/formalizations", tags=["formalizations"])
_READ = tuple(WorkspaceRole)
_WRITE = (WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER)


def _request_id(request: Request) -> str:
    return str(request.state.correlation_id)


def _context(request: Request, actor_id: UUID) -> FormalizationContext:
    try:
        correlation = UUID(hex=str(request.state.correlation_id).removeprefix("req_"))
    except ValueError:
        correlation = uuid7()
    return FormalizationContext(actor_id, correlation, datetime.now(UTC), uuid7())


async def _idempotent(
    tx: Any,
    workspace_id: UUID,
    operation: str,
    key: str,
    request_hash: str,
    action: Callable[[], Awaitable[tuple[int, dict[str, Any]]]],
) -> JSONResponse:
    existing = await tx.idempotency.load_after_lock(workspace_id, operation, key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise VersionConflict(
                "Idempotency-Key was already used for a different request", current_version=1
            )
        return JSONResponse(
            existing.response_body,
            status_code=existing.status_code,
            headers={
                "Idempotency-Replayed": "true",
                "ETag": str(existing.response_body["meta"]["version"]),
            },
        )
    status, response = await action()
    await tx.idempotency.save(
        workspace_id,
        operation,
        key,
        IdempotencyRecord(request_hash, status, response),
    )
    return JSONResponse(
        response, status_code=status, headers={"ETag": str(response["meta"]["version"])}
    )


async def _artifacts(tx: Any, workspace_id: UUID, body: FormalizationCreate) -> Any:
    source = await tx.artifacts.get(workspace_id, parse_id("artifact", body.source_artifact_id))
    if source is None:
        raise not_found("source artifact")
    for value in body.premise_artifact_ids:
        premise = await tx.artifacts.get(workspace_id, parse_id("artifact", value))
        if premise is None or premise.session_id != source.session_id:
            raise not_found("premise artifact")
    return source


def _revision(
    body: FormalizationCreate,
    *,
    identity: UUID,
    logical_id: UUID,
    number: int,
    supersedes_id: UUID | None,
    source: Any,
    actor_id: UUID,
    correlation_id: UUID,
    occurred_at: datetime,
) -> FormalizationRevision:
    return FormalizationRevision(
        id=identity,
        logical_id=logical_id,
        revision=number,
        supersedes_id=supersedes_id,
        workspace_id=source.workspace_id,
        session_id=source.session_id,
        source_artifact_id=source.id,
        source_artifact_logical_id=source.logical_id,
        source_artifact_version=source.version,
        ast=body.ast,
        ast_hash=ast_hash(body.ast),
        symbols=body.symbols,
        canonical_rendering=body.canonical_rendering,
        premise_artifact_ids=tuple(
            parse_id("artifact", value) for value in body.premise_artifact_ids
        ),
        limitations=body.limitations,
        fidelity_notes=body.fidelity_notes,
        created_at=occurred_at,
        actor_class=ActorClass.HUMAN,
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def _conflict(exc: FormalizationError, expected: int) -> VersionConflict:
    detail = str(exc)
    current = expected
    if "current revision is " in detail:
        current = int(detail.rsplit(" ", maxsplit=1)[-1])
    return VersionConflict(detail, current_version=current)


@router.post("", status_code=201)
@require_roles(*_WRITE)
# trace: FR-707
async def create_formalization(
    request: Request,
    body: FormalizationCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> JSONResponse:
    principal = current_principal(request)
    request_hash = content_hash(body.model_dump(mode="json"))
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def action() -> tuple[int, dict[str, Any]]:
            source = await _artifacts(tx, principal.workspace_id, body)
            context = _context(request, principal.user_id)
            identity = uuid7()
            revision = _revision(
                body,
                identity=identity,
                logical_id=identity,
                number=1,
                supersedes_id=None,
                source=source,
                actor_id=principal.user_id,
                correlation_id=context.correlation_id,
                occurred_at=context.occurred_at,
            )
            try:
                result = await FormalizationLifecycleService(tx.formalizations).create(
                    revision, context=context
                )
            except FormalizationError as exc:
                raise ValidationFailed(str(exc)) from exc
            return 201, formalization_response(result, request_id=_request_id(request))

        return await _idempotent(
            tx,
            principal.workspace_id,
            "formalization:create",
            idempotency_key,
            request_hash,
            action,
        )


@router.get("/{formalization_id}")
@require_roles(*_READ)
async def get_formalization(
    request: Request,
    formalization_id: str,
    revision: Annotated[int | None, Query(ge=1)] = None,
) -> JSONResponse:
    principal = current_principal(request)
    try:
        logical_id = parse_id("formalization", formalization_id)
    except ValueError as exc:
        raise not_found("formalization") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        result = await FormalizationLifecycleService(tx.formalizations).get(
            principal.workspace_id, logical_id, revision=revision
        )
        if result is None:
            raise not_found("formalization")
        response = formalization_response(result, request_id=_request_id(request))
        return JSONResponse(response, headers={"ETag": str(result.revision.revision)})


@router.post("/{formalization_id}/revisions", status_code=201)
@require_roles(*_WRITE)
async def revise_formalization(
    request: Request,
    formalization_id: str,
    body: FormalizationRevisionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    if_match: Annotated[int, Header(alias="If-Match", ge=1)],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        logical_id = parse_id("formalization", formalization_id)
    except ValueError as exc:
        raise not_found("formalization") from exc
    request_hash = content_hash({"if_match": if_match, "body": body.model_dump(mode="json")})
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def action() -> tuple[int, dict[str, Any]]:
            head = await tx.formalizations.head(principal.workspace_id, logical_id)
            if head is None:
                raise not_found("formalization")
            source = await _artifacts(tx, principal.workspace_id, body)
            context = _context(request, principal.user_id)
            revision = _revision(
                body,
                identity=uuid7(),
                logical_id=logical_id,
                number=head.revision + 1,
                supersedes_id=head.id,
                source=source,
                actor_id=principal.user_id,
                correlation_id=context.correlation_id,
                occurred_at=context.occurred_at,
            )
            try:
                result = await FormalizationLifecycleService(tx.formalizations).revise(
                    revision, expected_revision=if_match, context=context
                )
            except FormalizationError as exc:
                raise _conflict(exc, if_match) from exc
            return 201, formalization_response(result, request_id=_request_id(request))

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"formalization:revise:{logical_id}",
            idempotency_key,
            request_hash,
            action,
        )


async def _lifecycle(
    request: Request,
    formalization_id: str,
    idempotency_key: str,
    if_match: int,
    operation: str,
    request_payload: dict[str, Any],
    action: Callable[[Any, Any, UUID, FormalizationContext], Awaitable[Any]],
) -> JSONResponse:
    principal = current_principal(request)
    try:
        logical_id = parse_id("formalization", formalization_id)
    except ValueError as exc:
        raise not_found("formalization") from exc
    request_hash = content_hash(
        {"if_match": if_match, "operation": operation, "body": request_payload}
    )
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:

        async def invoke() -> tuple[int, dict[str, Any]]:
            context = _context(request, principal.user_id)
            try:
                result = await action(tx, principal, logical_id, context)
            except FormalizationError as exc:
                raise _conflict(exc, if_match) from exc
            return 201, formalization_response(result, request_id=_request_id(request))

        return await _idempotent(
            tx,
            principal.workspace_id,
            f"formalization:{operation}:{logical_id}",
            idempotency_key,
            request_hash,
            invoke,
        )


@router.post("/{formalization_id}/validations", status_code=201)
@require_roles(*_WRITE)
async def validate_formalization(
    request: Request,
    formalization_id: str,
    body: FormalizationValidationCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    if_match: Annotated[int, Header(alias="If-Match", ge=1)],
) -> JSONResponse:
    del body

    async def action(
        tx: Any, principal: Any, logical_id: UUID, context: FormalizationContext
    ) -> Any:
        return await FormalizationLifecycleService(tx.formalizations).validate(
            principal.workspace_id,
            logical_id,
            expected_revision=if_match,
            validation_id=uuid7(),
            context=context,
        )

    return await _lifecycle(
        request, formalization_id, idempotency_key, if_match, "validate", {}, action
    )


async def _decide(
    request: Request,
    formalization_id: str,
    body: FormalizationDecisionCreate,
    idempotency_key: str,
    if_match: int,
    kind: FormalizationDecisionKind,
) -> JSONResponse:
    async def action(
        tx: Any, principal: Any, logical_id: UUID, context: FormalizationContext
    ) -> Any:
        return await FormalizationLifecycleService(tx.formalizations).decide(
            principal.workspace_id,
            logical_id,
            expected_revision=if_match,
            decision_id=uuid7(),
            kind=kind,
            reason=body.reason,
            context=context,
        )

    return await _lifecycle(
        request,
        formalization_id,
        idempotency_key,
        if_match,
        kind.value.lower(),
        body.model_dump(mode="json"),
        action,
    )


@router.post("/{formalization_id}/confirmations", status_code=201)
@require_roles(*_WRITE)
async def confirm_formalization(
    request: Request,
    formalization_id: str,
    body: FormalizationDecisionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    if_match: Annotated[int, Header(alias="If-Match", ge=1)],
) -> JSONResponse:
    return await _decide(
        request,
        formalization_id,
        body,
        idempotency_key,
        if_match,
        FormalizationDecisionKind.CONFIRMED,
    )


@router.post("/{formalization_id}/rejections", status_code=201)
@require_roles(*_WRITE)
async def reject_formalization(
    request: Request,
    formalization_id: str,
    body: FormalizationDecisionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    if_match: Annotated[int, Header(alias="If-Match", ge=1)],
) -> JSONResponse:
    return await _decide(
        request,
        formalization_id,
        body,
        idempotency_key,
        if_match,
        FormalizationDecisionKind.REJECTED,
    )
