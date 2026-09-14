"""Add immutable, tenant-safe reproducibility manifests.

Revision ID: 20260914_0026
Revises: 20260912_0025
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0026"
down_revision: str | None = "20260912_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# trace: NFR-003, NFR-014
def upgrade() -> None:
    op.create_table(
        "reproducibility_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("manifest_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("manifest_bucket", sa.Text(), nullable=True),
        sa.Column("manifest_ref", sa.Text(), nullable=True),
        sa.Column("manifest_hash", sa.Text(), nullable=True),
        sa.Column("manifest_size", sa.Integer(), nullable=True),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("image_digests", postgresql.JSONB(), nullable=False),
        sa.Column("model_pins", postgresql.JSONB(), nullable=False),
        sa.Column("prompt_hashes", postgresql.JSONB(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "manifest_version > 0", name=op.f("ck_reproducibility_manifests_manifest_version")
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','FINALIZED')", name=op.f("ck_reproducibility_manifests_status")
        ),
        sa.CheckConstraint(
            "length(btrim(git_sha)) > 0", name=op.f("ck_reproducibility_manifests_git_sha")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(image_digests) = 'object'",
            name=op.f("ck_reproducibility_manifests_image_digests_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(model_pins) = 'object'",
            name=op.f("ck_reproducibility_manifests_model_pins_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(prompt_hashes) = 'object'",
            name=op.f("ck_reproducibility_manifests_prompt_hashes_object"),
        ),
        sa.CheckConstraint(
            "(status = 'CREATED' AND manifest_ref IS NULL AND manifest_hash IS NULL "
            "AND manifest_bucket IS NULL AND manifest_size IS NULL AND finalized_at IS NULL) OR "
            "(status = 'FINALIZED' AND manifest_ref IS NOT NULL AND manifest_hash IS NOT NULL "
            "AND manifest_bucket IS NOT NULL AND manifest_size IS NOT NULL "
            "AND finalized_at IS NOT NULL)",
            name=op.f("ck_reproducibility_manifests_lifecycle_shape"),
        ),
        sa.CheckConstraint(
            "manifest_hash IS NULL OR manifest_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_reproducibility_manifests_manifest_hash"),
        ),
        sa.CheckConstraint(
            "source_session_id IS NULL OR source_session_id <> session_id",
            name=op.f("ck_reproducibility_manifests_source_differs"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_reproducibility_manifests_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_reproducibility_manifests_source_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reproducibility_manifests")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_reproducibility_manifests_workspace_id")
        ),
        sa.UniqueConstraint(
            "workspace_id", "session_id", name=op.f("uq_reproducibility_manifests_session")
        ),
    )
    op.create_index(
        "ix_reproducibility_manifests_source",
        "reproducibility_manifests",
        ["workspace_id", "source_session_id", "created_at", "id"],
    )
    op.execute("""
        CREATE FUNCTION enforce_manifest_lifecycle() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'run manifests cannot be deleted' USING ERRCODE = '27000';
          END IF;
          IF OLD.status = 'FINALIZED' THEN
            RAISE EXCEPTION 'finalized run manifests are immutable' USING ERRCODE = '27000';
          END IF;
          IF NEW.status <> 'FINALIZED'
             OR NEW.id IS DISTINCT FROM OLD.id
             OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
             OR NEW.session_id IS DISTINCT FROM OLD.session_id
             OR NEW.source_session_id IS DISTINCT FROM OLD.source_session_id
             OR NEW.manifest_version IS DISTINCT FROM OLD.manifest_version
             OR NEW.git_sha IS DISTINCT FROM OLD.git_sha
             OR NEW.image_digests IS DISTINCT FROM OLD.image_digests
             OR NEW.model_pins IS DISTINCT FROM OLD.model_pins
             OR NEW.prompt_hashes IS DISTINCT FROM OLD.prompt_hashes
             OR NEW.seed IS DISTINCT FROM OLD.seed
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'only exact manifest finalization is allowed' USING ERRCODE = '27000';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER trg_reproducibility_manifests_lifecycle "
        "BEFORE UPDATE OR DELETE ON reproducibility_manifests "
        "FOR EACH ROW EXECUTE FUNCTION enforce_manifest_lifecycle()"
    )
    op.execute("REVOKE DELETE ON reproducibility_manifests FROM PUBLIC")
    op.execute("ALTER TABLE reproducibility_manifests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reproducibility_manifests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY reproducibility_manifests_workspace_isolation "
        "ON reproducibility_manifests "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_reproducibility_manifests_lifecycle "
        "ON reproducibility_manifests"
    )
    op.drop_table("reproducibility_manifests")
    op.execute("DROP FUNCTION enforce_manifest_lifecycle()")
