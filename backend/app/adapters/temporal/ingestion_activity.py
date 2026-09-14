"""Temporal adapter for durable source ingestion."""

from __future__ import annotations

import json
from typing import Any

from temporalio import activity

from app.domain.ingestion_activity import (
    INGEST_SOURCE_ACTIVITY,
    IngestionActivityRunner,
    IngestSourceInput,
    IngestSourceResult,
)
from app.domain.orchestration_policy import INGESTION_POLICY

from .activity_policy import run_activity

__all__ = ["IngestionActivities"]


class IngestionActivities:
    def __init__(self, runner: IngestionActivityRunner) -> None:
        self._runner = runner

    @activity.defn(name=INGEST_SOURCE_ACTIVITY)
    async def ingest_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        async def run() -> IngestSourceResult:
            command = IngestSourceInput.model_validate_json(json.dumps(raw))
            return await self._runner.run(command)

        heartbeat_every_s = INGESTION_POLICY.heartbeat_timeout_s
        assert heartbeat_every_s is not None
        result = await run_activity(run, heartbeat_every_s=heartbeat_every_s // 2)
        return result.model_dump(mode="json")
