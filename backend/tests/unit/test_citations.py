"""Resolvable citation, human attribution, and retraction contract tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.citations import CitationService
from app.domain.citations import (
    CitationRepository,
    CitationResolution,
    CitationSnapshot,
    EvidenceCitation,
    ManualEvidenceCitation,
    SourceRetraction,
    SourceRetractionCommand,
)
from app.domain.knowledge import SourceStatus
from app.domain.reasoning import ActorClass
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 12))
NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _snapshot() -> CitationSnapshot:
    return CitationSnapshot(
        namespace_id=U[3],
        source_id=U[4],
        document_id=U[5],
        chunk_id=U[6],
        citation="Fixture source, 2026",
        locator={"page": 2, "char_start": 10, "char_end": 30},
        source_content_hash=HASH_A,
        chunk_content_hash=HASH_B,
        chunker_version="agora-whitespace-v1",
        source_timestamp=NOW,
        document_timestamp=NOW,
        retrieved_at=NOW,
        trust_level="PRIMARY",
        source_status=SourceStatus.READY,
    )


def _citation() -> EvidenceCitation:
    return EvidenceCitation(
        citation_id=U[0],
        workspace_id=U[1],
        session_id=U[2],
        evidence_artifact_id=U[7],
        claim_artifact_id=U[8],
        actor_id=U[9],
        attached_at=NOW,
        snapshot=_snapshot(),
    )


@req("FR-402", "FR-406", "FR-407")
def test_citation_snapshot_requires_complete_exact_provenance() -> None:
    assert _snapshot().locator["page"] == 2
    with pytest.raises(ValidationError, match="char_start"):
        CitationSnapshot.model_validate({**_snapshot().model_dump(), "locator": {}})
    with pytest.raises(ValidationError):
        CitationSnapshot.model_validate(
            {**_snapshot().model_dump(), "source_content_hash": "sha256:bad"}
        )


@req("FR-402", "FR-406", "FR-407")
def test_manual_evidence_and_retraction_require_human_attribution() -> None:
    values = {
        "citation_id": U[0],
        "workspace_id": U[1],
        "session_id": U[2],
        "evidence_artifact_id": U[7],
        "actor_id": U[9],
        "namespace_id": U[3],
        "source_id": U[4],
        "document_id": U[5],
        "chunk_id": U[6],
        "source_content_hash": HASH_A,
        "chunk_content_hash": HASH_B,
        "locator": {"page": 2, "char_start": 10, "char_end": 30},
        "retrieved_at": NOW,
    }
    assert ManualEvidenceCitation.model_validate(values).actor_class is ActorClass.HUMAN
    with pytest.raises(ValidationError):
        ManualEvidenceCitation.model_validate({**values, "actor_class": "AGENT"})
    with pytest.raises(ValidationError, match="blank"):
        SourceRetractionCommand(
            retraction_id=U[10],
            workspace_id=U[1],
            source_id=U[4],
            actor_id=U[9],
            reason=" ",
            retracted_at=NOW,
        )


class StubRepository:
    def __init__(self) -> None:
        self.citation = _citation()

    async def attach_manual(self, command: ManualEvidenceCitation) -> EvidenceCitation:
        del command
        return self.citation

    async def resolve(self, workspace_id: UUID, citation_id: UUID) -> CitationResolution | None:
        del workspace_id, citation_id
        return CitationResolution(
            citation=self.citation,
            current_source_status=SourceStatus.RETRACTED,
            retracted_at=NOW,
            retraction_reason="superseded publication",
        )

    async def citations_for_evidence(
        self, workspace_id: UUID, evidence_artifact_id: UUID
    ) -> tuple[CitationResolution, ...]:
        if (
            workspace_id == self.citation.workspace_id
            and evidence_artifact_id == self.citation.evidence_artifact_id
        ):
            resolved = await self.resolve(workspace_id, self.citation.citation_id)
            assert resolved is not None
            return (resolved,)
        return ()

    async def retract_source(self, command: SourceRetractionCommand) -> SourceRetraction:
        return SourceRetraction(
            retraction_id=command.retraction_id,
            workspace_id=command.workspace_id,
            source_id=command.source_id,
            actor_id=command.actor_id,
            reason=command.reason,
            retracted_at=command.retracted_at,
            dependent_evidence_ids=(self.citation.evidence_artifact_id,),
            dependent_claim_ids=(self.citation.claim_artifact_id,),
        )

    async def dependencies(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]:
        del workspace_id, source_id
        return (self.citation,)


@req("FR-402", "FR-406", "FR-407")
async def test_service_preserves_old_snapshot_while_showing_current_retraction() -> None:
    repository = StubRepository()
    assert isinstance(repository, CitationRepository)
    resolved = await CitationService(repository).resolve(U[1], U[0])
    assert resolved is not None
    assert resolved.citation.snapshot.source_status is SourceStatus.READY
    assert resolved.current_source_status is SourceStatus.RETRACTED
    assert resolved.citation.snapshot.chunk_content_hash == HASH_B


@req("FR-402", "FR-406", "FR-407")
async def test_lookup_by_evidence_is_tenant_scoped_and_returns_no_match() -> None:
    repository = StubRepository()
    found = await repository.citations_for_evidence(U[1], U[7])
    assert found[0].citation == repository.citation
    assert await repository.citations_for_evidence(U[2], U[7]) == ()
    assert await repository.citations_for_evidence(U[1], U[8]) == ()


@req("FR-402", "FR-406", "FR-407")
def test_migration_and_repository_enforce_authoritative_append_only_dependencies() -> None:
    backend = Path(__file__).parents[2]
    migration = (
        backend / "alembic" / "versions" / "20260906_0015_resolvable_citations.py"
    ).read_text(encoding="utf-8")
    repository = (backend / "app" / "db" / "citations.py").read_text(encoding="utf-8")
    assert "evidence_citations" in migration
    assert "source_retractions" in migration
    assert 'for table in ("evidence_citations", "source_retractions")' in migration
    assert "ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in migration
    assert "citation and retraction facts are append-only" in migration
    assert "source retraction is irreversible" in migration
    assert "JOIN reasoning_artifacts claim" in repository
    assert "JOIN workspace_members member" in repository
    assert "s.status = 'READY' AND d.status = 'READY'" in repository
    assert "c.locator = CAST(:locator AS jsonb)" in repository
    assert "jsonb_array_elements(e.source_references)" in repository
    assert "ck_sources_retraction_reason_required" in migration
