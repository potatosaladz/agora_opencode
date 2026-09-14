"""Side-effect-free requirement metadata decorators for tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

T = TypeVar("T", bound=Callable[..., object])


def req(*requirement_ids: str) -> Callable[[T], T]:
    """Attach requirement ids without altering the decorated test's execution semantics."""
    if not requirement_ids or any(
        not isinstance(item, str) or not item for item in requirement_ids
    ):
        raise ValueError("req() requires one or more non-empty requirement ids")

    def decorate(function: T) -> T:
        existing = cast(tuple[str, ...], getattr(function, "__requirement_ids__", ()))
        setattr(  # noqa: B010 - metadata attribute is intentionally dynamic
            function,
            "__requirement_ids__",
            tuple(dict.fromkeys((*existing, *requirement_ids))),
        )
        return function

    return decorate
