"""Injectable clock.

`docs/PORTS.md` §0 forbids adapters reading the clock implicitly, and
`docs/REPRODUCIBILITY.md` requires that a replay can reconstruct the original timeline.
Both are served by the same mechanism: production code takes a `Clock`, tests take
`FrozenClock`, and nothing calls `datetime.now` directly.

Enforced by `tests/test_layering.py`, which fails on a direct wall-clock read outside
this module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

__all__ = ["Clock", "FrozenClock", "SystemClock", "utc_now"]


def utc_now() -> datetime:
    """The single permitted wall-clock read in the codebase. Do not call from domain code."""
    return datetime.now(UTC)


class Clock(Protocol):
    """Anything that can tell the time. All platform time arrives through this."""

    def now(self) -> datetime: ...


class SystemClock:
    """Real time, always UTC-aware."""

    def now(self) -> datetime:
        return utc_now()


class FrozenClock:
    """A clock that does not move. Used by tests and by strict replay.

    `advance` exists because some tests need time to pass without waiting for it.
    """

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance(self, *, seconds: float) -> None:
        from datetime import timedelta

        self._moment += timedelta(seconds=seconds)
