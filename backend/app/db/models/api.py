"""Durable tenant-scoped HTTP idempotency records."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["IdempotencyRecordRow"]


class IdempotencyRecordRow(Base):
    __tablename__ = "api_idempotency_records"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_id", "operation", "key", name="pk_api_idempotency_records"),
        CheckConstraint("length(btrim(operation)) > 0", name="operation_not_blank"),
        CheckConstraint("length(btrim(key)) > 0", name="key_not_blank"),
        CheckConstraint("request_hash ~ '^sha256:[0-9a-f]{64}$'", name="request_hash_format"),
        CheckConstraint("status_code BETWEEN 200 AND 299", name="success_status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
