"""Tenant-safe run-manifest row for Phase 13 T13-04."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["RunManifestRow"]


# trace: NFR-003, NFR-014
class RunManifestRow(Base):
    __tablename__ = "reproducibility_manifests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_reproducibility_manifests_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_reproducibility_manifests_source_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint("manifest_version > 0", name="manifest_version"),
        CheckConstraint("status IN ('CREATED','FINALIZED')", name="status"),
        CheckConstraint("length(btrim(git_sha)) > 0", name="git_sha"),
        CheckConstraint("jsonb_typeof(image_digests) = 'object'", name="image_digests_object"),
        CheckConstraint("jsonb_typeof(model_pins) = 'object'", name="model_pins_object"),
        CheckConstraint("jsonb_typeof(prompt_hashes) = 'object'", name="prompt_hashes_object"),
        CheckConstraint(
            "(status = 'CREATED' AND manifest_ref IS NULL AND manifest_hash IS NULL "
            "AND manifest_bucket IS NULL AND manifest_size IS NULL AND finalized_at IS NULL) OR "
            "(status = 'FINALIZED' AND manifest_ref IS NOT NULL AND manifest_hash IS NOT NULL "
            "AND manifest_bucket IS NOT NULL AND manifest_size IS NOT NULL "
            "AND finalized_at IS NOT NULL)",
            name="lifecycle_shape",
        ),
        CheckConstraint(
            "manifest_hash IS NULL OR manifest_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="manifest_hash",
        ),
        CheckConstraint(
            "source_session_id IS NULL OR source_session_id <> session_id",
            name="source_differs",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_reproducibility_manifests_workspace_id"),
        UniqueConstraint("workspace_id", "session_id", name="uq_reproducibility_manifests_session"),
        Index(
            "ix_reproducibility_manifests_source",
            "workspace_id",
            "source_session_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    manifest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_bucket: Mapped[str | None] = mapped_column(Text)
    manifest_ref: Mapped[str | None] = mapped_column(Text)
    manifest_hash: Mapped[str | None] = mapped_column(Text)
    manifest_size: Mapped[int | None] = mapped_column(Integer)
    git_sha: Mapped[str] = mapped_column(Text, nullable=False)
    image_digests: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_pins: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prompt_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
