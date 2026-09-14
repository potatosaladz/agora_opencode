"""Strict public contracts for replay controls."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.replay import ReplayMode

__all__ = [
    "ManifestData",
    "ManifestResponse",
    "ReplayData",
    "ReplayDifferenceContract",
    "ReplayManifestRefContract",
    "ReplayMeta",
    "ReplayMismatchContract",
    "ReplayRequestContract",
    "ReplayResponse",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplayManifestRefContract(_Strict):
    manifest_id: str = Field(pattern=r"^man_[0-9a-f]{32}$")
    manifest_version: int = Field(gt=0)
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReplayRequestContract(_Strict):
    manifest: ReplayManifestRefContract
    mode: ReplayMode
    confirm_live: bool = False


class ReplayMismatchContract(_Strict):
    reason: str
    detail: str
    order: int | None = None
    step_id: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None


class ReplayDifferenceContract(_Strict):
    order: int
    step_id: str
    kind: str
    difference: str
    field: str
    expected: str | None
    actual: str | None


class ReplayData(_Strict):
    mode: ReplayMode
    outcome: str
    source_session_id: str
    source_manifest: ReplayManifestRefContract
    integrity_valid: bool
    byte_identical: bool
    checked_steps: int
    differences: tuple[ReplayDifferenceContract, ...]
    first_mismatch: ReplayMismatchContract | None
    replay_session_id: str | None
    replay_manifest_id: str | None
    replay_event_ids: tuple[str, ...]
    replay_result_ids: tuple[str, ...]
    links: dict[str, str]


class ReplayMeta(_Strict):
    request_id: str
    schema_version: int
    workspace_id: str


class ReplayResponse(_Strict):
    data: ReplayData
    meta: ReplayMeta


class ManifestData(_Strict):
    session_id: str
    manifest_id: str
    manifest_version: int
    manifest_hash: str
    status: str
    source_session_id: str | None
    finalized_at: str | None
    git_sha: str
    image_digests: dict[str, str]


class ManifestResponse(_Strict):
    data: ManifestData
    meta: ReplayMeta
