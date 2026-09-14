"""SDK-free retry, timeout, idempotency, checkpoint, and dead-letter policy."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "AGENT_TURN_POLICY",
    "INGESTION_POLICY",
    "STATE_COMMIT_POLICY",
    "ActivityPolicy",
    "activity_operation_id",
]


@dataclass(frozen=True, slots=True)
class ActivityPolicy:
    """Portable activity policy expressed in primitive seconds and attempt counts."""

    start_to_close_s: int
    schedule_to_close_s: int
    maximum_attempts: int
    initial_interval_s: int = 1
    backoff_coefficient: float = 2.0
    maximum_interval_s: int = 30
    heartbeat_timeout_s: int | None = None

    def __post_init__(self) -> None:
        positive = (
            self.start_to_close_s,
            self.schedule_to_close_s,
            self.maximum_attempts,
            self.initial_interval_s,
            self.maximum_interval_s,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("activity policy values must be positive")
        if self.schedule_to_close_s < self.start_to_close_s:
            raise ValueError("schedule_to_close_s must cover at least one activity attempt")
        if self.backoff_coefficient < 1:
            raise ValueError("backoff_coefficient must be at least 1")
        if self.heartbeat_timeout_s is not None and self.heartbeat_timeout_s <= 0:
            raise ValueError("heartbeat_timeout_s must be positive when set")


STATE_COMMIT_POLICY = ActivityPolicy(
    start_to_close_s=15,
    schedule_to_close_s=300,
    maximum_attempts=10,
)

AGENT_TURN_POLICY = ActivityPolicy(
    start_to_close_s=120,
    schedule_to_close_s=300,
    maximum_attempts=3,
    heartbeat_timeout_s=30,
)

INGESTION_POLICY = ActivityPolicy(
    start_to_close_s=300,
    schedule_to_close_s=900,
    maximum_attempts=3,
    heartbeat_timeout_s=30,
)


def activity_operation_id(session_id: str, activity_type: str, idempotency_key: str) -> str:
    """Build stable operation identity reused unchanged by every activity attempt."""
    values = (session_id, activity_type, idempotency_key)
    if any(not value.strip() for value in values):
        raise ValueError("activity operation identity parts must not be blank")
    return ":".join(values)
