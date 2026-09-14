"""Canonical, immutable run manifests for Phase 13 T13-04."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid5

from pydantic import AliasChoices, Field, field_validator, model_validator

from app.domain.reasoning import FrozenModel, canonical_json, content_hash
from app.domain.replay import MarlReplayBundle, ReplayManifestRef, ReplayStep
from app.ports.storage import ObjectRef

__all__ = [
    "AgentPin",
    "CodePin",
    "ConsensusPin",
    "ContentPin",
    "InferencePin",
    "MarlPin",
    "MetricPin",
    "RandomnessPin",
    "RetrievalPin",
    "RunManifest",
    "RunManifestConflict",
    "RunManifestDocument",
    "RunManifestRepository",
    "RunManifestStatus",
    "SchemaPin",
    "SimulationPin",
    "SymbolicPin",
    "run_manifest_bytes",
    "run_manifest_hash",
    "run_manifest_id",
]

_MANIFEST_NAMESPACE = UUID("28ba96d9-cdea-4e80-b7fe-9cbdf8907344")


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class CodePin(FrozenModel):
    git_sha: str
    image_digests: dict[str, str]

    _git_sha = field_validator("git_sha")(_not_blank)

    @field_validator("image_digests")
    @classmethod
    def valid_images(cls, values: dict[str, str]) -> dict[str, str]:
        if not values:
            raise ValueError("at least one image digest is required")
        if any(not name.strip() for name in values):
            raise ValueError("image names must not be blank")
        if any(not value.startswith("sha256:") or len(value) != 71 for value in values.values()):
            raise ValueError("image digests must use sha256 content identity")
        return dict(sorted(values.items()))


class SchemaPin(FrozenModel):
    migration_head: str
    artifact_schema_version: int = Field(gt=0)

    _head = field_validator("migration_head")(_not_blank)


class ConsensusPin(FrozenModel):
    strategy_id: str
    strategy_version: str
    parameters: dict[str, Any]
    input_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    _id = field_validator("strategy_id")(_not_blank)
    _version = field_validator("strategy_version")(_not_blank)


class InferencePin(FrozenModel):
    provider: str
    model: str
    api_version: str | None = None
    temperature: Decimal = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0)
    stop: tuple[str, ...] = ()
    timeout_s: Decimal = Field(gt=0)
    seed: int | None = None

    _provider = field_validator("provider")(_not_blank)
    _model = field_validator("model")(_not_blank)


class AgentPin(FrozenModel):
    definition_id: UUID
    definition_version: int = Field(gt=0)
    prompt_ref: str
    prompt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    strategy_id: str
    strategy_version: str
    inference: InferencePin | None = None

    _prompt_ref = field_validator("prompt_ref")(_not_blank)
    _strategy_id = field_validator("strategy_id")(_not_blank)
    _strategy_version = field_validator("strategy_version")(_not_blank)


class RetrievalPin(FrozenModel):
    query_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    namespace_ids: tuple[UUID, ...]
    index_version: str
    embedding_model: str
    embedding_version: str
    reranker_version: str | None = None

    _index = field_validator("index_version")(_not_blank)
    _embedding_model = field_validator("embedding_model")(_not_blank)
    _embedding_version = field_validator("embedding_version")(_not_blank)


class MetricPin(FrozenModel):
    metric_id: str
    metric_version: str
    inputs_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    code_version: str | None = None

    _metric_id = field_validator("metric_id")(_not_blank)
    _metric_version = field_validator("metric_version")(_not_blank)


class SymbolicPin(FrozenModel):
    formalization_revision_id: UUID
    ast_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    engine: str
    engine_version: str
    timeout_ms: int = Field(gt=0)
    configuration_id: str
    evidence_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    _engine = field_validator("engine")(_not_blank)
    _engine_version = field_validator("engine_version")(_not_blank)
    _configuration = field_validator("configuration_id")(_not_blank)


class SimulationPin(FrozenModel):
    run_id: UUID
    spec_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    engine: str
    engine_version: str
    seed: int

    _engine = field_validator("engine")(_not_blank)
    _engine_version = field_validator("engine_version")(_not_blank)


class MarlPin(FrozenModel):
    episode_id: UUID
    environment_version: str
    code_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    trajectory_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    episode_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    _environment = field_validator("environment_version")(_not_blank)


class ContentPin(FrozenModel):
    content_id: UUID
    kind: Literal["SOURCE", "CHUNK", "ARTIFACT", "PROVIDER_RESPONSE"]
    version: int | None = Field(default=None, gt=0)
    ref: str | None = None
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RandomnessPin(FrozenModel):
    use: str
    seed: int
    stream: int = Field(ge=0)

    _use = field_validator("use")(_not_blank)


class RunManifestDocument(FrozenModel):
    manifest_version: Literal[1] = 1
    workspace_id: UUID
    session_id: UUID
    source_session_id: UUID | None = None
    code: CodePin
    schema_pin: SchemaPin = Field(
        validation_alias=AliasChoices("schema", "schema_pin"), serialization_alias="schema"
    )
    configuration_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    protocol: str
    rounds: int = Field(gt=0)
    budget: dict[str, Any]
    consensus: ConsensusPin
    agents: tuple[AgentPin, ...]
    retrieval: tuple[RetrievalPin, ...] = ()
    metrics: tuple[MetricPin, ...]
    symbolic: tuple[SymbolicPin, ...] = ()
    simulations: tuple[SimulationPin, ...] = ()
    marl: tuple[MarlPin, ...] = ()
    contents: tuple[ContentPin, ...]
    randomness: tuple[RandomnessPin, ...] = ()
    replay_steps: tuple[ReplayStep, ...]
    marl_bundles: tuple[MarlReplayBundle, ...] = ()
    started_at: datetime
    ordering: Literal["ledger_seq"] = "ledger_seq"

    _protocol = field_validator("protocol")(_not_blank)

    @field_validator("started_at")
    @classmethod
    def started_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def required_pins(self) -> RunManifestDocument:
        if self.source_session_id == self.session_id:
            raise ValueError("source session must differ from run session")
        if not self.agents or not self.metrics or not self.contents or not self.replay_steps:
            raise ValueError("agents, metrics, contents and replay steps are required")
        identities = (
            (
                tuple((item.definition_id, item.definition_version) for item in self.agents),
                "agent definitions",
            ),
            (
                tuple((item.metric_id, item.metric_version) for item in self.metrics),
                "metric definitions",
            ),
            (
                tuple((item.kind, item.content_id, item.version) for item in self.contents),
                "content identities",
            ),
            (tuple(item.step_id for item in self.replay_steps), "replay steps"),
        )
        for values, label in identities:
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        if tuple(step.order for step in self.replay_steps) != tuple(
            sorted(step.order for step in self.replay_steps)
        ):
            raise ValueError("replay steps must be deterministically ordered")
        return self


def run_manifest_bytes(document: RunManifestDocument) -> bytes:
    return canonical_json(document.model_dump(mode="json", by_alias=True))


def run_manifest_hash(document: RunManifestDocument) -> str:
    return content_hash(document.model_dump(mode="json", by_alias=True))


def run_manifest_id(document: RunManifestDocument) -> UUID:
    return uuid5(_MANIFEST_NAMESPACE, run_manifest_hash(document))


class RunManifestStatus(StrEnum):
    CREATED = "CREATED"
    FINALIZED = "FINALIZED"


class RunManifest(FrozenModel):
    id: UUID
    workspace_id: UUID
    session_id: UUID
    source_session_id: UUID | None = None
    manifest_version: int = Field(gt=0)
    status: RunManifestStatus
    manifest_ref: ObjectRef | None = None
    manifest_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    git_sha: str
    image_digests: dict[str, str]
    model_pins: dict[str, Any]
    prompt_hashes: dict[str, str]
    seed: int | None = None
    created_at: datetime
    finalized_at: datetime | None = None

    _git_sha = field_validator("git_sha")(_not_blank)

    @field_validator("created_at", "finalized_at")
    @classmethod
    def timestamps_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("manifest timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def lifecycle_shape(self) -> RunManifest:
        if self.source_session_id == self.session_id:
            raise ValueError("source session must differ from run session")
        if self.status is RunManifestStatus.CREATED:
            if self.manifest_ref is not None or self.manifest_hash is not None or self.finalized_at:
                raise ValueError("created manifest cannot contain finalized fields")
        elif self.manifest_ref is None or self.manifest_hash is None or self.finalized_at is None:
            raise ValueError("finalized manifest requires ref, hash and finalized_at")
        return self

    def ref(self) -> ReplayManifestRef:
        if self.status is not RunManifestStatus.FINALIZED or self.manifest_hash is None:
            raise ValueError("only a finalized manifest is replayable")
        return ReplayManifestRef(
            manifest_id=self.id,
            manifest_version=self.manifest_version,
            manifest_hash=self.manifest_hash,
        )


class RunManifestConflict(ValueError):
    """A manifest identity or finalized session was reused inconsistently."""


@runtime_checkable
class RunManifestRepository(Protocol):
    async def create(self, manifest: RunManifest) -> RunManifest: ...

    async def get_for_session(
        self, workspace_id: UUID, session_id: UUID, *, for_update: bool = False
    ) -> RunManifest | None: ...

    async def get_finalized(
        self, workspace_id: UUID, session_id: UUID, reference: ReplayManifestRef
    ) -> RunManifest | None: ...

    async def finalize(self, manifest: RunManifest) -> RunManifest: ...
