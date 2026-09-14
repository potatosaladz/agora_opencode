"""Add UUID-backed knowledge provenance to vector_items.

Revision ID: 20260906_0012
Revises: 20260906_0011
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0012"
down_revision: str | None = "20260906_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "vector_items"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("namespace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(_TABLE, sa.Column("chunk_uuid", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(_TABLE, sa.Column("document_uuid", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(_TABLE, sa.Column("source_uuid", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(_TABLE, sa.Column("embedding_model", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("embedding_version", sa.Text(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
    )
    op.create_check_constraint(
        op.f("ck_vector_items_knowledge_identity_complete"),
        _TABLE,
        "(namespace_id IS NULL AND chunk_uuid IS NULL AND document_uuid IS NULL "
        "AND source_uuid IS NULL AND embedding_model IS NULL AND embedding_version IS NULL) OR "
        "(namespace_id IS NOT NULL AND chunk_uuid IS NOT NULL AND document_uuid IS NOT NULL "
        "AND source_uuid IS NOT NULL AND length(btrim(embedding_model)) > 0 "
        "AND embedding_version IS NOT NULL AND length(btrim(embedding_version)) > 0)",
    )
    op.create_foreign_key(
        "fk_vector_items_namespace_workspace",
        _TABLE,
        "knowledge_namespaces",
        ["workspace_id", "namespace_id"],
        ["workspace_id", "id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_chunks_workspace_id_document", "chunks", ["workspace_id", "id", "document_id"]
    )
    op.create_unique_constraint(
        "uq_documents_workspace_id_source", "documents", ["workspace_id", "id", "source_id"]
    )
    op.create_unique_constraint(
        "uq_sources_workspace_id_namespace", "sources", ["workspace_id", "id", "namespace_id"]
    )
    op.create_foreign_key(
        "fk_vector_items_chunk_document",
        _TABLE,
        "chunks",
        ["workspace_id", "chunk_uuid", "document_uuid"],
        ["workspace_id", "id", "document_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_vector_items_document_source",
        _TABLE,
        "documents",
        ["workspace_id", "document_uuid", "source_uuid"],
        ["workspace_id", "id", "source_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_vector_items_source_namespace",
        _TABLE,
        "sources",
        ["workspace_id", "source_uuid", "namespace_id"],
        ["workspace_id", "id", "namespace_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_vector_items_knowledge_scope",
        _TABLE,
        ["workspace_id", "namespace_id", "embedding_model", "embedding_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_vector_items_knowledge_scope", table_name=_TABLE)
    for constraint in (
        "fk_vector_items_source_namespace",
        "fk_vector_items_document_source",
        "fk_vector_items_chunk_document",
        "fk_vector_items_namespace_workspace",
        op.f("ck_vector_items_knowledge_identity_complete"),
    ):
        op.drop_constraint(constraint, _TABLE)
    op.drop_constraint("uq_sources_workspace_id_namespace", "sources")
    op.drop_constraint("uq_documents_workspace_id_source", "documents")
    op.drop_constraint("uq_chunks_workspace_id_document", "chunks")
    for column in (
        "created_at",
        "embedding_version",
        "embedding_model",
        "source_uuid",
        "document_uuid",
        "chunk_uuid",
        "namespace_id",
    ):
        op.drop_column(_TABLE, column)
