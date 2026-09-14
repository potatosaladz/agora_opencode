"""Temporal activity adapter for typed logical-agent turns."""

from __future__ import annotations

import json
from typing import Any

from temporalio import activity

from app.domain.agent_activity import (
    AGENT_TURN_ACTIVITY,
    AgentActivityRunner,
    AgentTurnInput,
    AgentTurnResult,
)
from app.domain.orchestration_policy import AGENT_TURN_POLICY

from .activity_policy import run_activity

__all__ = ["AgentActivities"]


class AgentActivities:
    def __init__(self, runner: AgentActivityRunner) -> None:
        self._runner = runner

    @activity.defn(name=AGENT_TURN_ACTIVITY)
    async def run_turn(self, raw: dict[str, Any]) -> dict[str, Any]:
        async def run() -> AgentTurnResult:
            command = AgentTurnInput.model_validate_json(json.dumps(raw))
            return await self._runner.run(command)

        heartbeat_every_s = AGENT_TURN_POLICY.heartbeat_timeout_s
        assert heartbeat_every_s is not None
        result = await run_activity(run, heartbeat_every_s=heartbeat_every_s // 2)
        return result.model_dump(mode="json")
