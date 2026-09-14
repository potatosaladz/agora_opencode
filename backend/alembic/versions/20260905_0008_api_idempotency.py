"""Add durable tenant-scoped API idempotency records.

Revision ID: 20260905_0008
Revises: 20260905_0007
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0008"
down_revision: str | None = "20260905_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_idempotency_records",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(operation)) > 0",
            name=op.f("ck_api_idempotency_records_operation_not_blank"),
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0", name=op.f("ck_api_idempotency_records_key_not_blank")
        ),
        sa.CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_api_idempotency_records_request_hash_format"),
        ),
        sa.CheckConstraint(
            "status_code BETWEEN 200 AND 299",
            name=op.f("ck_api_idempotency_records_success_status"),
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "operation", "key", name="pk_api_idempotency_records"
        ),
    )
    op.execute("ALTER TABLE api_idempotency_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_idempotency_records FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY api_idempotency_records_workspace_isolation ON api_idempotency_records "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_table("api_idempotency_records")
