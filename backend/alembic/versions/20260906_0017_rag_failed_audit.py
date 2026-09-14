"""Record retrieval failures distinctly from successful no-match results.

Revision ID: 20260906_0017
Revises: 20260906_0016
Migration type: expand
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260906_0017"
down_revision: str | None = "20260906_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_retrieval_attempts_outcome_census", "retrieval_attempts")
    op.drop_constraint("ck_retrieval_attempts_outcome", "retrieval_attempts")
    op.create_check_constraint(
        "outcome",
        "retrieval_attempts",
        "outcome IN ('ALLOWED','DENIED','RAG_FAILED')",
    )
    op.create_check_constraint(
        "outcome_census",
        "retrieval_attempts",
        "(outcome = 'ALLOWED' AND degradation IS NOT NULL) OR "
        "(outcome = 'DENIED' AND degradation IS NULL "
        "AND cardinality(searched_namespace_ids) = 0 "
        "AND lexical_count = 0 AND vector_count = 0 AND result_count = 0) OR "
        "(outcome = 'RAG_FAILED' AND result_count = 0)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM retrieval_attempts WHERE outcome = 'RAG_FAILED') THEN
            RAISE EXCEPTION 'cannot downgrade while RAG_FAILED retrieval audits exist';
          END IF;
        END
        $$
        """
    )
    op.drop_constraint("ck_retrieval_attempts_outcome_census", "retrieval_attempts")
    op.drop_constraint("ck_retrieval_attempts_outcome", "retrieval_attempts")
    op.create_check_constraint(
        "outcome",
        "retrieval_attempts",
        "outcome IN ('ALLOWED','DENIED')",
    )
    op.create_check_constraint(
        "outcome_census",
        "retrieval_attempts",
        "(outcome = 'ALLOWED' AND degradation IS NOT NULL) OR "
        "(outcome = 'DENIED' AND degradation IS NULL "
        "AND cardinality(searched_namespace_ids) = 0 "
        "AND lexical_count = 0 AND vector_count = 0 AND result_count = 0)",
    )
