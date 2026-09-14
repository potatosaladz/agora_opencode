"""Enable pgvector and add the tenant-scoped vector store.

Revision ID: 20260904_0002
Revises: 20260904_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.adapters.pgvector.types import Vector

revision: str = "20260904_0002"
down_revision: str | None = "20260904_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "vector_items",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("chunk_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_vector_items_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "namespace", "chunk_id", name=op.f("pk_vector_items")
        ),
    )
    op.create_index(
        "ix_vector_items_workspace_namespace", "vector_items", ["workspace_id", "namespace"]
    )
    op.create_index(
        "ix_vector_items_embedding_cosine",
        "vector_items",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 10},
    )
    op.execute("ALTER TABLE vector_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vector_items FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY vector_items_workspace_isolation ON vector_items "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_table("vector_items")
    op.execute("DROP EXTENSION IF EXISTS vector")
