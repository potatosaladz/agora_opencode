"""T4-05 bounded Temporal policy, classification, heartbeat, and identity tests."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from temporalio.exceptions import ApplicationError

from app.adapters.temporal.activity_policy import (
    activity_options,
    run_activity,
    temporal_retry_policy,
)
from app.domain.orchestration_policy import (
    AGENT_TURN_POLICY,
    STATE_COMMIT_POLICY,
    ActivityPolicy,
    activity_operation_id,
)
from app.ports.errors import PermanentPortError, TransientPortError
from tests.traceability import req


@req("NFR-016")
def test_declared_policies_are_bounded_and_long_work_heartbeats() -> None:
    state = activity_options(STATE_COMMIT_POLICY)
    agent = activity_options(AGENT_TURN_POLICY)
    retry = temporal_retry_policy(STATE_COMMIT_POLICY)

    assert state.start_to_close_timeout == timedelta(seconds=15)
    assert state.schedule_to_close_timeout == timedelta(minutes=5)
    assert state.heartbeat_timeout is None
    assert agent.start_to_close_timeout == timedelta(minutes=2)
    assert agent.heartbeat_timeout == timedelta(seconds=30)
    assert retry.maximum_attempts == 10
    assert retry.maximum_interval == timedelta(seconds=30)
    assert retry.non_retryable_error_types == ("AGORA_PERMANENT_ACTIVITY_FAILURE",)


@req("NFR-016")
@pytest.mark.parametrize(
    "policy",
    [
        ActivityPolicy(start_to_close_s=15, schedule_to_close_s=300, maximum_attempts=3),
    ],
)
def test_valid_activity_policy_is_immutable(policy: ActivityPolicy) -> None:
    with pytest.raises(AttributeError):
        policy.maximum_attempts = 4  # type: ignore[misc]


@req("NFR-016")
@pytest.mark.parametrize(
    ("values", "message"),
    [
        ((0, 300, 3, 2.0, None), "positive"),
        ((15, 1, 3, 2.0, None), "cover at least one"),
        ((15, 300, 0, 2.0, None), "positive"),
        ((15, 300, 3, 0.5, None), "at least 1"),
        ((15, 300, 3, 2.0, 0), "positive when set"),
    ],
)
def test_invalid_activity_policy_is_rejected(
    values: tuple[int, int, int, float, int | None],
    message: str,
) -> None:
    start, schedule, attempts, backoff, heartbeat = values
    with pytest.raises(ValueError, match=message):
        ActivityPolicy(
            start_to_close_s=start,
            schedule_to_close_s=schedule,
            maximum_attempts=attempts,
            backoff_coefficient=backoff,
            heartbeat_timeout_s=heartbeat,
        )


@req("NFR-016")
def test_activity_operation_identity_is_stable_and_strict() -> None:
    assert activity_operation_id("session", "commit", "event") == "session:commit:event"
    with pytest.raises(ValueError, match="must not be blank"):
        activity_operation_id("session", " ", "event")


@req("NFR-016")
@pytest.mark.parametrize(
    ("failure", "error_type", "non_retryable"),
    [
        (PermanentPortError("bad input", port="test"), "AGORA_PERMANENT_ACTIVITY_FAILURE", True),
        (
            TransientPortError("temporarily down", port="test"),
            "AGORA_TRANSIENT_ACTIVITY_FAILURE",
            False,
        ),
        (RuntimeError("unknown"), "AGORA_TRANSIENT_ACTIVITY_FAILURE", False),
    ],
)
async def test_activity_failure_taxonomy_maps_to_temporal(
    failure: Exception, error_type: str, non_retryable: bool
) -> None:
    async def fail() -> None:
        raise failure

    with pytest.raises(ApplicationError) as captured:
        await run_activity(fail)

    assert captured.value.type == error_type
    assert captured.value.non_retryable is non_retryable
    assert captured.value.details[0]["error_class"] == type(failure).__name__


@req("NFR-016")
async def test_long_activity_heartbeats_until_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    beats: list[str] = []

    async def complete() -> str:
        await asyncio.sleep(0.03)
        return "done"

    monkeypatch.setattr(
        "app.adapters.temporal.activity_policy.activity.heartbeat",
        lambda: beats.append("beat"),
    )

    assert await run_activity(complete, heartbeat_every_s=0.01) == "done"
    assert beats


@req("NFR-016")
async def test_activity_cancellation_cancels_and_drains_inner_operation() -> None:
    started = asyncio.Event()
    drained = asyncio.Event()

    async def pending() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    wrapper = asyncio.create_task(run_activity(pending, heartbeat_every_s=60))
    await started.wait()
    wrapper.cancel()

    with pytest.raises(asyncio.CancelledError):
        await wrapper

    assert drained.is_set()
