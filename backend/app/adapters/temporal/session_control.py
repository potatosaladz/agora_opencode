"""Temporal activity boundary for PostgreSQL-authoritative session controls."""

from __future__ import annotations

import json
from typing import Any

from temporalio import activity

from app.domain.session_control import (
    SessionControlTransition,
    SessionControlTransitionCommitter,
)
from app.domain.session_lifecycle import SessionLifecycle

from .activity_policy import run_activity

__all__ = ["SessionControlActivities"]

SESSION_CONTROL_ACTIVITY = "commit_session_control_transition"


class SessionControlActivities:
    def __init__(self, committer: SessionControlTransitionCommitter) -> None:
        self._committer = committer

    @activity.defn(name=SESSION_CONTROL_ACTIVITY)
    async def commit_transition(self, raw: dict[str, Any]) -> dict[str, Any]:
        async def commit() -> SessionLifecycle:
            transition = SessionControlTransition.model_validate_json(json.dumps(raw))
            return await self._committer.commit(transition)

        projection = await run_activity(commit)
        return projection.model_dump(mode="json")
