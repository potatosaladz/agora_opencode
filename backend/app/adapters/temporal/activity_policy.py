"""Temporal mapping for portable activity policy and port failure taxonomy."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta

from pydantic import ValidationError
from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from app.domain.orchestration_policy import ActivityPolicy
from app.domain.reasoning_ledger import LedgerIntegrityError
from app.domain.session_lifecycle import InvalidSessionTransition
from app.ports.errors import PermanentPortError, TransientPortError

__all__ = ["activity_options", "run_activity", "temporal_retry_policy"]


@dataclass(frozen=True, slots=True)
class TemporalActivityOptions:
    start_to_close_timeout: timedelta
    schedule_to_close_timeout: timedelta
    heartbeat_timeout: timedelta | None


_PERMANENT_FAILURE = "AGORA_PERMANENT_ACTIVITY_FAILURE"
_TRANSIENT_FAILURE = "AGORA_TRANSIENT_ACTIVITY_FAILURE"


def temporal_retry_policy(policy: ActivityPolicy) -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=policy.initial_interval_s),
        backoff_coefficient=policy.backoff_coefficient,
        maximum_interval=timedelta(seconds=policy.maximum_interval_s),
        maximum_attempts=policy.maximum_attempts,
        non_retryable_error_types=(_PERMANENT_FAILURE,),
    )


def activity_options(policy: ActivityPolicy) -> TemporalActivityOptions:
    return TemporalActivityOptions(
        start_to_close_timeout=timedelta(seconds=policy.start_to_close_s),
        schedule_to_close_timeout=timedelta(seconds=policy.schedule_to_close_s),
        heartbeat_timeout=(
            timedelta(seconds=policy.heartbeat_timeout_s)
            if policy.heartbeat_timeout_s is not None
            else None
        ),
    )


async def run_activity[T](
    operation: Callable[[], Awaitable[T]], *, heartbeat_every_s: float | None = None
) -> T:
    """Translate failures and heartbeat long asynchronous work without changing its identity."""
    task: asyncio.Future[T] | None = None
    try:
        task = asyncio.ensure_future(operation())
        if heartbeat_every_s is None:
            return await task
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_every_s)
            if done:
                return task.result()
            activity.heartbeat()
    except asyncio.CancelledError:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        raise
    except (
        PermanentPortError,
        ValidationError,
        InvalidSessionTransition,
        LedgerIntegrityError,
    ) as exc:
        raise ApplicationError(
            "activity rejected permanent input or state",
            {"error_class": type(exc).__name__},
            type=_PERMANENT_FAILURE,
            non_retryable=True,
        ) from exc
    except TransientPortError as exc:
        raise ApplicationError(
            "activity dependency is temporarily unavailable",
            {"error_class": type(exc).__name__, "port": exc.port},
            type=_TRANSIENT_FAILURE,
        ) from exc
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError(
            "activity failed unexpectedly",
            {"error_class": type(exc).__name__},
            type=_TRANSIENT_FAILURE,
        ) from exc
