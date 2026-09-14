"""Live PostgreSQL proof for resolvable citations and durable source retraction."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.retrieval.postgres import PostgresCandidateSearch
from app.application.provenance import ProvenanceService
from app.application.source_impact import SourceImpactService
from app.db.citations import SqlAlchemyCitationRepository
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.reasoning_graph import SqlAlchemyReasoningGraphStore
from app.db.session import Database
from app.db.source_impact import SqlAlchemySourceImpactRepository
from app.domain.citations import CitationError, ManualEvidenceCitation, SourceRetractionCommand
from app.domain.knowledge import JsonObject, NamespaceSubjectKind, SourceStatus
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    EvidencePayload,
    EvidenceProvenance,
    EvidenceRelation,
    GraphEdgeType,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    ReviewStatus,
    SourceReference,
    Strength,
    TrustLevel,
    Verification,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode
from app.domain.retrieval import PrincipalClass, RetrievalRequest, RetrievalSubject
from app.domain.source_impact import ImpactAnalysisResult, ImpactAnalysisStatus
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]
_NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
_SOURCE_HASH = "sha256:" + "a" * 64
_CHUNK_HASH = "sha256:" + "b" * 64
_SECOND_CHUNK_HASH = "sha256:" + "c" * 64


@req("FR-408")
async def test_source_impact_migration_is_forced_rls_append_only_and_atomic() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace, user = uuid4(), uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'Impact')"),
            {"id": workspace, "slug": f"impact-{workspace.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'fixture', :subject, 'Researcher')"
            ),
            {"id": user, "subject": str(user)},
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace, :user, 'RESEARCHER')"
            ),
            {"workspace": workspace, "user": user},
        )
        tables = {
            "consensus_results",
            "recommendations",
            "impact_reports",
            "impact_report_dependencies",
            "workspace_event_outbox",
        }
        forced = set(
            (
                await connection.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relname = ANY(CAST(:tables AS text[])) "
                        "AND relrowsecurity AND relforcerowsecurity"
                    ),
                    {"tables": list(tables)},
                )
            ).scalars()
        )
        assert forced == tables

    database = Database(engine)
    command_value = SourceRetractionCommand(
        retraction_id=uuid4(),
        workspace_id=workspace,
        source_id=uuid4(),
        actor_id=user,
        reason="must roll back",
        retracted_at=_NOW,
    )
    with pytest.raises(CitationError):
        async with database.session(workspace) as session:
            await SqlAlchemySourceImpactRepository(
                session, SqlAlchemyReasoningGraphStore(session)
            ).retract_and_report(
                command_value,
                report_id=uuid4(),
                event_id=uuid4(),
                correlation_id=uuid4(),
                analysis=ImpactAnalysisResult(
                    status=ImpactAnalysisStatus.COMPLETE,
                    complete=True,
                    truncated=False,
                    dependencies=(),
                ),
            )
    async with engine.connect() as connection:
        counts: list[int | None] = []
        for table in ("source_retractions", "impact_reports", "workspace_event_outbox"):
            counts.append(await connection.scalar(text(f"SELECT count(*) FROM {table}")))
    assert counts == [0, 0, 0]
    await asyncio.to_thread(command.check, config)
    await database.close()


def _artifact_values(
    *,
    workspace: UUID,
    session: UUID,
    user: UUID,
    kind: ArtifactKind,
    payload: object,
    source_references: tuple[SourceReference, ...] = (),
) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": workspace,
        "session_id": session,
        "logical_id": uuid4(),
        "kind": kind,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": user,
        "round": 0,
        "payload": payload,
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="manual evidence"),
        "source_references": source_references,
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values["content_hash"] = artifact_content_hash(values)
    return values


@req("FR-403", "FR-407", "FR-408")
async def test_manual_citation_survives_retraction_and_keeps_impact_dependencies() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace, user, session, namespace, agent, objective = (uuid4() for _ in range(6))
    source, document, chunk, second_chunk = (uuid4() for _ in range(4))
    locator: JsonObject = {"page": 3, "char_start": 40, "char_end": 72}
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'T5-07')"),
            {"id": workspace, "slug": f"t507-{workspace.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'fixture', :subject, 'Curator')"
            ),
            {"id": user, "subject": str(user)},
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace, :user, 'RESEARCHER')"
            ),
            {"workspace": workspace, "user": user},
        )
        await connection.execute(
            text(
                "INSERT INTO agent_definitions (id, workspace_id, logical_id, version, name, "
                "domain, role_kind, knowledge_ns, strategy_ref, strategy_ver, prompt_ref, "
                "prompt_hash, status) VALUES (:id, :workspace, :logical, 1, 'Citation Agent', "
                "'testing', 'domain_expert', '{}'::uuid[], 'strategy/test', '1', "
                "'prompt/test', 'sha256:test', 'ACTIVE')"
            ),
            {"id": agent, "workspace": workspace, "logical": uuid4()},
        )
        await connection.execute(
            text(
                "INSERT INTO sessions (id, workspace_id, problem_statement, max_rounds, "
                "budget_tokens, budget_usd, created_by) "
                "VALUES (:id, :workspace, 'Citation test', 2, 1000, 10, :user)"
            ),
            {"id": session, "workspace": workspace, "user": user},
        )
        await connection.execute(
            text(
                "INSERT INTO session_agents (workspace_id, session_id, agent_def_id) "
                "VALUES (:workspace, :session, :agent)"
            ),
            {"workspace": workspace, "session": session, "agent": agent},
        )
        await connection.execute(
            text(
                "INSERT INTO reasoning_artifacts (id, workspace_id, session_id, logical_id, "
                "kind, schema_version, version, status, owner_actor_class, owner_actor_id, "
                "round, payload, provenance, source_references, parent_relationships, "
                "metadata, content_hash, created_at, updated_at) VALUES (:id, :workspace, "
                ":session, :logical, 'OBJECTIVE', 1, 1, 'ACTIVE', 'HUMAN', :user, 0, "
                "CAST(:payload AS jsonb), CAST(:provenance AS jsonb), '[]'::jsonb, "
                "'[]'::jsonb, '{}'::jsonb, :hash, :now, :now)"
            ),
            {
                "id": objective,
                "workspace": workspace,
                "session": session,
                "logical": uuid4(),
                "user": user,
                "payload": (
                    '{"name":"Citation integrity","objective_type":"UTILITY",'
                    '"direction":"MAXIMIZE","weight":"1",'
                    '"weight_rationale":"T5-07 fixture","time_horizon":"test",'
                    '"conflicts_with_ids":[]}'
                ),
                "provenance": '{"origin":"HUMAN","reference":"integration-test"}',
                "hash": "sha256:" + "f" * 64,
                "now": _NOW,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO session_objectives (workspace_id, session_id, artifact_id) "
                "VALUES (:workspace, :session, :objective)"
            ),
            {"workspace": workspace, "session": session, "objective": objective},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespaces (id, workspace_id, tier, name) "
                "VALUES (:id, :workspace, 'WORKSPACE', 'citations')"
            ),
            {"id": namespace, "workspace": workspace},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespace_grants "
                "(id, workspace_id, namespace_id, subject_kind, subject_id, "
                "capability, valid_from) VALUES "
                "(:id, :workspace, :namespace, 'WORKSPACE', :workspace, 'READ', :now)"
            ),
            {"id": uuid4(), "workspace": workspace, "namespace": namespace, "now": _NOW},
        )
        await connection.execute(
            text(
                "INSERT INTO sources (id, workspace_id, namespace_id, title, citation, "
                "object_ref, content_hash, media_type, size_bytes, published_at, "
                "trust_level, uploaded_by) VALUES (:id, :workspace, :namespace, "
                "'Fixture', 'Fixture source, 2026', 'sources/a', :hash, "
                "'text/plain', 32, :now, 'PRIMARY', :user)"
            ),
            {
                "id": source,
                "workspace": workspace,
                "namespace": namespace,
                "hash": _SOURCE_HASH,
                "now": _NOW,
                "user": user,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO documents (id, workspace_id, source_id, parser, "
                "parser_version, status, created_at, updated_at) VALUES "
                "(:id, :workspace, :source, 'txt', '1', 'READY', :now, :now)"
            ),
            {"id": document, "workspace": workspace, "source": source, "now": _NOW},
        )
        await connection.execute(
            text(
                "INSERT INTO chunks (id, workspace_id, document_id, ordinal, text, "
                "token_count, locator, content_hash, chunker_version) VALUES "
                "(:id, :workspace, :document, 0, 'citation target phrase', 3, "
                "CAST(:locator AS jsonb), :hash, 'chunker-v1')"
            ),
            {
                "id": chunk,
                "workspace": workspace,
                "document": document,
                "locator": '{"page":3,"char_start":40,"char_end":72}',
                "hash": _CHUNK_HASH,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO chunks (id, workspace_id, document_id, ordinal, text, "
                "token_count, locator, content_hash, chunker_version) VALUES "
                "(:id, :workspace, :document, 1, 'citation target phrase', 3, "
                "CAST(:locator AS jsonb), :hash, 'chunker-v1')"
            ),
            {
                "id": second_chunk,
                "workspace": workspace,
                "document": document,
                "locator": '{"page":3,"char_start":40,"char_end":72}',
                "hash": _SECOND_CHUNK_HASH,
            },
        )

    claim = validate_artifact(
        _artifact_values(
            workspace=workspace,
            session=session,
            user=user,
            kind=ArtifactKind.CLAIM,
            payload=ClaimPayload(
                statement="Target claim",
                claim_type=ClaimType.FACTUAL,
                direction=Bearing.SUPPORTS,
                strength=Strength.MODERATE,
                supporting_evidence_ids=(),
                opposing_evidence_ids=(),
                review_status=ReviewStatus.PROPOSED,
            ),
        )
    )
    evidence_values = _artifact_values(
        workspace=workspace,
        session=session,
        user=user,
        kind=ArtifactKind.EVIDENCE,
        payload=EvidencePayload(
            claim_id=claim.id,
            relation=EvidenceRelation.SUPPORTS,
            quote="citation target phrase",
            verification=Verification.UNVERIFIED,
            trust_level=TrustLevel.PRIMARY,
            weight="0.7",
            provenance_kind=EvidenceProvenance.HUMAN,
        ),
        source_references=(
            SourceReference(
                reference="Fixture source, 2026",
                locator=locator,
                content_hash=_CHUNK_HASH,
                retrieved_at=_NOW,
                source_timestamp=_NOW,
            ),
            SourceReference(
                reference="Fixture source, 2026",
                locator=locator,
                content_hash=_SECOND_CHUNK_HASH,
                retrieved_at=_NOW,
                source_timestamp=_NOW,
            ),
        ),
    )
    evidence = validate_artifact(evidence_values)
    database = Database(engine)
    citation_id = uuid4()
    async with database.session(workspace) as db_session:
        artifacts = SqlAlchemyReasoningArtifactStore(db_session)
        await artifacts.add(claim)
        await artifacts.add(evidence)
        repository = SqlAlchemyCitationRepository(db_session)
        graph = SqlAlchemyReasoningGraphStore(db_session)
        evidence_node, claim_node = uuid4(), uuid4()
        await graph.add_node(
            GraphNode(
                id=evidence_node,
                workspace_id=workspace,
                session_id=session,
                kind=ArtifactKind.EVIDENCE,
                ref_id=evidence.id,
                label="Evidence",
            )
        )
        await graph.add_node(
            GraphNode(
                id=claim_node,
                workspace_id=workspace,
                session_id=session,
                kind=ArtifactKind.CLAIM,
                ref_id=claim.id,
                label="Claim",
            )
        )
        await graph.add_edge(
            GraphEdge(
                id=uuid4(),
                workspace_id=workspace,
                session_id=session,
                from_node=evidence_node,
                to_node=claim_node,
                edge_type=GraphEdgeType.SUPPORTS,
                actor_class=ActorClass.HUMAN,
                actor_id=user,
            )
        )
        request = ManualEvidenceCitation(
            citation_id=citation_id,
            workspace_id=workspace,
            session_id=session,
            evidence_artifact_id=evidence.id,
            actor_id=user,
            namespace_id=namespace,
            source_id=source,
            document_id=document,
            chunk_id=chunk,
            source_content_hash=_SOURCE_HASH,
            chunk_content_hash=_CHUNK_HASH,
            locator=locator,
            retrieved_at=_NOW,
        )
        attached = await repository.attach_manual(request)
        assert attached.claim_artifact_id == claim.id
        second_attached = await repository.attach_manual(
            request.model_copy(
                update={
                    "citation_id": uuid4(),
                    "chunk_id": second_chunk,
                    "chunk_content_hash": _SECOND_CHUNK_HASH,
                }
            )
        )
        with pytest.raises(CitationError):
            await repository.attach_manual(
                request.model_copy(
                    update={"citation_id": uuid4(), "chunk_content_hash": _SOURCE_HASH}
                )
            )
        impact_repository = SqlAlchemySourceImpactRepository(db_session, graph)
        impact_report = await SourceImpactService(impact_repository).retract_source(
            SourceRetractionCommand(
                retraction_id=uuid4(),
                workspace_id=workspace,
                source_id=source,
                actor_id=user,
                reason="publisher correction",
                retracted_at=_NOW,
            ),
            report_id=uuid4(),
            event_id=uuid4(),
            correlation_id=uuid4(),
        )
        assert impact_report.affected_claim_ids == (claim.id,)
        assert {item.dependent_id for item in impact_report.dependencies} == {
            evidence.id,
            claim.id,
        }
        assert (
            await db_session.scalar(
                text("SELECT event_type FROM workspace_event_outbox WHERE id = :id"),
                {"id": impact_report.event_id},
            )
            == "SOURCE_RETRACTED"
        )
        assert (
            await impact_repository.get_report(workspace, impact_report.report_id) == impact_report
        )
        resolved = await repository.resolve(workspace, citation_id)
        assert resolved is not None
        assert resolved.citation.snapshot.source_status is SourceStatus.READY
        assert resolved.current_source_status is SourceStatus.RETRACTED
        by_evidence = await repository.citations_for_evidence(workspace, evidence.id)
        assert {item.citation.citation_id for item in by_evidence} == {
            resolved.citation.citation_id,
            second_attached.citation_id,
        }
        assert list(by_evidence) == sorted(
            by_evidence, key=lambda item: (item.citation.attached_at, item.citation.citation_id)
        )
        assert await repository.citations_for_evidence(workspace, uuid4()) == ()
        assert await repository.citations_for_evidence(uuid4(), evidence.id) == ()
        provenance = await ProvenanceService(artifacts, graph, repository).provenance_of(
            workspace, claim.id
        )
        assert provenance is not None
        evidence_provenance = next(
            node for node in provenance.nodes if node.graph_node.ref_id == evidence.id
        )
        assert evidence_provenance.verification is Verification.UNVERIFIED
        assert evidence_provenance.citations == by_evidence
        assert provenance.edges[0].edge_type is GraphEdgeType.SUPPORTS

    retrieval = RetrievalRequest(
        attempt_id=uuid4(),
        trace_id=uuid4(),
        workspace_id=workspace,
        principal_class=PrincipalClass.HUMAN,
        principal_id=user,
        namespace_ids=(namespace,),
        subjects=(
            RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=workspace),
            RetrievalSubject(kind=NamespaceSubjectKind.USER, id=user),
        ),
        query="citation target phrase",
        query_vector=[0.0] * 1536,
        embedding_model="fixture",
        embedding_version="1",
        index_version="1",
        requested_at=_NOW,
    )
    assert await PostgresCandidateSearch(engine, workspace).lexical(retrieval, k=5) == ()
    with pytest.raises(DBAPIError, match="irreversible"):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE sources SET status = 'READY', retracted_at = NULL, "
                    "retraction_reason = NULL WHERE id = :id"
                ),
                {"id": source},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM evidence_citations WHERE id = :id"), {"id": citation_id}
            )
    async with engine.begin() as connection:
        forced = set(
            (
                await connection.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relname IN "
                        "('evidence_citations','source_retractions') "
                        "AND relrowsecurity AND relforcerowsecurity"
                    )
                )
            ).scalars()
        )
    assert forced == {"evidence_citations", "source_retractions"}
    await asyncio.to_thread(command.check, config)
    await database.close()
